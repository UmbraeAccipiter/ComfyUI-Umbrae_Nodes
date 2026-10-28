# umbrae_nodes/modules/lora_loader/remote.py — umbrae_nodes v0.9.3
#
# The only module here that opens sockets: Civitai + Hugging Face lookups,
# searches and downloads. Stdlib urllib so it runs in a worker thread under
# ComfyUI (the routes call it through run_in_executor) and under the dev server
# alike. Keys go in the Authorization header, never in a URL.
#
# Downloads run in a background thread per job; progress is polled by id.
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import helpers as H

UA = "umbrae_nodes lora loader"
TIMEOUT = 30
MAX_JSON = 8 * 1024 * 1024


class RemoteError(Exception):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def _get_json(url, headers=None):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json", "Accept-Encoding": "identity",
        **(headers or {}),
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip()
            body = r.read(MAX_JSON + 1)
            if len(body) > MAX_JSON:
                raise RemoteError("Reply too large.")
            try:
                return json.loads(body)
            except Exception:
                raise RemoteError("Replied with {} instead of data (a block or sign-in page?)."
                                  .format(ctype or "an unknown format"))
    except urllib.error.HTTPError as e:
        raise RemoteError("HTTP {}".format(e.code), e.code)
    except urllib.error.URLError as e:
        raise RemoteError("Could not connect ({}).".format(getattr(e, "reason", e)))
    except RemoteError:
        raise
    except Exception as e:
        raise RemoteError("{}: {}".format(type(e).__name__, e))


# ── Civitai ──────────────────────────────────────────────────────────────────

def _civ_headers(acc):
    h = {}
    if acc.get("civitai_key"):
        h["Authorization"] = "Bearer " + acc["civitai_key"]
    return h


def civitai_try_hosts(acc, path_fn):
    """Call path_fn(host) on each host in preference order. A 404 counts only on
    the last host (the unrestricted host may know a model the main one hides)."""
    last = None
    for i, host in enumerate(H.civitai_hosts(acc.get("host"))):
        try:
            return _get_json("https://{}{}".format(host, path_fn(host)), _civ_headers(acc))
        except RemoteError as e:
            last = e
            if e.status == 404 and i == 0:
                continue
            if e.status in (401, 403):
                last = RemoteError("Civitai refused the request ({}). {}".format(
                    e.status, "Check the API key in the settings." if acc.get("civitai_key")
                    else "Your network may block Civitai, or this model needs an API key."), e.status)
                continue
            continue
    raise last or RemoteError("Could not reach Civitai.")


def civitai_by_hash(sha256, acc):
    """Version object for a file hash, enriched with umbrae_model (name, description,
    tags, creator, stats) from /models/{id}. None when not on Civitai."""
    try:
        ver = civitai_try_hosts(acc, lambda h: "/api/v1/model-versions/by-hash/" + sha256)
    except RemoteError as e:
        if e.status == 404:
            return None
        raise
    if not isinstance(ver, dict) or not ver.get("id"):
        return None
    mid = ver.get("modelId")
    if mid:
        try:
            model = civitai_try_hosts(acc, lambda h: "/api/v1/models/{}".format(int(mid)))
            ver["umbrae_model"] = H.model_summary(model)
        except Exception:
            pass
    return ver


def civitai_search(q, acc, base="", sort="", nsfw=None, cursor="", limit=24, period=""):
    params = {"types": "LORA", "limit": max(1, min(100, int(limit or 24)))}
    if q:
        params["query"] = q
    if base:
        params["baseModels"] = base
    if sort in ("Highest Rated", "Most Downloaded", "Newest"):
        params["sort"] = sort
    if period in ("AllTime", "Year", "Month", "Week", "Day"):
        params["period"] = period
    if nsfw is not None:
        params["nsfw"] = "true" if nsfw else "false"
    if cursor:
        params["cursor"] = cursor
    qs = urllib.parse.urlencode(params)
    data = civitai_try_hosts(acc, lambda h: "/api/v1/models?" + qs)
    return H.parse_search(data, allow_adult=bool(acc.get("adult")) or bool(nsfw))


# ── Hugging Face ─────────────────────────────────────────────────────────────

def _hf_headers(acc):
    return {"Authorization": "Bearer " + acc["hf_key"]} if acc.get("hf_key") else {}


def hf_search(q, acc, limit=24, sort="downloads"):
    params = {"search": q or "lora", "filter": "lora", "limit": max(1, min(100, int(limit or 24))),
              "full": "true", "sort": sort if sort in ("downloads", "likes", "lastModified", "trendingScore") else "downloads",
              "direction": "-1"}
    data = _get_json("https://huggingface.co/api/models?" + urllib.parse.urlencode(params), _hf_headers(acc))
    return H.parse_hf_search(data)


def hf_repo(repo, acc):
    repo = str(repo or "").strip("/ ")
    if not repo or repo.count("/") != 1 or ".." in repo:
        raise RemoteError("Bad repo id.")
    data = _get_json("https://huggingface.co/api/models/{}?blobs=true".format(urllib.parse.quote(repo)), _hf_headers(acc))
    return H.parse_hf_repo(data)


# ── image fetch (for the preview store) ──────────────────────────────────────

_IMAGE_HOSTS = ("image.civitai.com", "huggingface.co", "cdn-lfs.huggingface.co", "cdn-lfs-us-1.huggingface.co")


def fetch_image(url, max_bytes=12 * 1024 * 1024):
    u = urllib.parse.urlparse(str(url or ""))
    if u.scheme != "https" or not any(u.netloc == h or u.netloc.endswith("." + h) for h in _IMAGE_HOSTS):
        raise RemoteError("Only Civitai / Hugging Face image links are accepted.")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = r.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise RemoteError("Picture too large.")
    return data


# ── downloads ────────────────────────────────────────────────────────────────

_jobs = {}
_jobs_lock = threading.Lock()
_DOWNLOAD_HOSTS = ("civitai.com", "civitai.red", "huggingface.co", "hf.co")


def _job_id():
    return "d{}".format(int(time.time() * 1000))


def start_download(url, dest_path, acc, source="civitai", sidecar=None):
    """Begin a streaming download to dest_path (written as .part, renamed on
    success). Returns the job id. `sidecar` (a Civitai version object) is written
    next to the file when the download completes."""
    u = urllib.parse.urlparse(str(url or ""))
    if u.scheme != "https" or not any(u.netloc == h or u.netloc.endswith("." + h) for h in _DOWNLOAD_HOSTS):
        raise RemoteError("Only Civitai / Hugging Face download links are accepted.")
    jid = _job_id()
    job = {"id": jid, "state": "running", "bytes": 0, "total": None, "path": dest_path,
           "name": os.path.basename(dest_path), "error": "", "cancel": False, "started": time.time()}
    with _jobs_lock:
        while jid in _jobs:
            jid += "x"
        job["id"] = jid
        _jobs[jid] = job
    headers = {"User-Agent": UA}
    if source == "civitai" and acc.get("civitai_key"):
        headers["Authorization"] = "Bearer " + acc["civitai_key"]
    elif source == "hf" and acc.get("hf_key"):
        headers["Authorization"] = "Bearer " + acc["hf_key"]
    t = threading.Thread(target=_run_download, args=(job, url, headers, sidecar), daemon=True)
    t.start()
    return jid


class _NoAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """Civitai redirects to a signed CDN URL; the bearer must not follow it there."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            host = urllib.parse.urlparse(newurl).netloc
            if not any(host == h or host.endswith("." + h) for h in _DOWNLOAD_HOSTS):
                new.remove_header("Authorization")
        return new


def _run_download(job, url, headers, sidecar):
    part = job["path"] + ".part"
    try:
        os.makedirs(os.path.dirname(job["path"]), exist_ok=True)
        opener = urllib.request.build_opener(_NoAuthOnRedirect())
        req = urllib.request.Request(url, headers=headers)
        with opener.open(req, timeout=TIMEOUT) as r:
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip()
            if ctype in ("text/html", "application/json") and job["total"] is None:
                raise RemoteError("The server sent a page instead of a file (sign-in or API key needed?).")
            try:
                job["total"] = int(r.headers.get("Content-Length") or 0) or None
            except Exception:
                job["total"] = None
            # the real filename from Content-Disposition, if the caller left it to us
            cd = r.headers.get("Content-Disposition") or ""
            if job.get("auto_name") and "filename=" in cd:
                fn = cd.split("filename=", 1)[1].strip().strip('"').split(";")[0]
                fn = H.safe_filename(fn)
                job["path"] = os.path.join(os.path.dirname(job["path"]), fn)
                job["name"] = fn
            with open(part, "wb") as f:
                while True:
                    if job["cancel"]:
                        raise RemoteError("Cancelled.")
                    chunk = r.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
                    job["bytes"] += len(chunk)
        if job["bytes"] < 1024:
            raise RemoteError("The download was empty (sign-in or API key needed?).")
        if os.path.exists(job["path"]):
            os.remove(job["path"])
        os.replace(part, job["path"])
        if sidecar:
            H.save_sidecar(job["path"], sidecar)
        job["state"] = "done"
    except Exception as e:
        job["state"] = "cancelled" if job["cancel"] else "error"
        job["error"] = str(e)
        try:
            if os.path.exists(part):
                os.remove(part)
        except Exception:
            pass


def job_status(jid):
    with _jobs_lock:
        job = _jobs.get(jid)
        if not job:
            return {"ok": False, "state": "missing"}
        return {"ok": True, "id": jid, "state": job["state"], "bytes": job["bytes"],
                "total": job["total"], "name": job["name"], "error": job["error"]}


def cancel_job(jid):
    with _jobs_lock:
        job = _jobs.get(jid)
        if job and job["state"] == "running":
            job["cancel"] = True
            return True
    return False


def active_jobs():
    with _jobs_lock:
        return [job_status(j) for j in list(_jobs)]
