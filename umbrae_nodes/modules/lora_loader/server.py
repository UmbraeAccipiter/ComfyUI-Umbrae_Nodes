# umbrae_nodes/modules/lora_loader/server.py — umbrae_nodes v0.9.3
#
# Routes for "lora loader [umbrae]". The handle_* functions are plain (dict in,
# dict out) so dev/lora_dev_server.py can serve the same panel without ComfyUI;
# register() wraps them as aiohttp routes on PromptServer. Slow work (hashing,
# network) runs in the default executor so the server loop is never blocked.
#
#   GET  /umbrae/lora/list                         {loras:[names], roots:[dirs]}
#   GET  /umbrae/lora/info?name=                   offline info + sidecar + custom words + preview
#   GET  /umbrae/lora/thumb?name=&v=               the preview picture (own picture wins)
#   GET  /umbrae/lora/civitai?name=&force=1        hash lookup -> saves <base>.civitai.info
#   GET  /umbrae/lora/civitai/search?q=&base=&sort=&nsfw=&cursor=&period=
#   GET  /umbrae/lora/hf/search?q=&sort=
#   GET  /umbrae/lora/hf/repo?repo=
#   POST /umbrae/lora/download {source, url, filename, subdir, overwrite, sidecar}
#   GET  /umbrae/lora/download/status?job=        | GET /umbrae/lora/downloads
#   POST /umbrae/lora/download/cancel {job}
#   GET/POST /umbrae/lora/account                  keys (never echoed), host, adult, download_dir
#   POST /umbrae/lora/custom_triggers {name, words}
#   POST /umbrae/lora/preview {name, dataUrl | url} | POST /umbrae/lora/preview_delete {name}
#   POST /umbrae/lora/civitai_delete {name}
import base64
import json
import logging
import os

from . import helpers as H
from . import remote as R

logger = logging.getLogger(__name__)

try:
    import folder_paths
except Exception:  # dev server
    folder_paths = None

# ── where things are (the dev server overrides these two) ────────────────────

_dev_lora_dirs = None
_dev_user_dir = None


def lora_dirs():
    if _dev_lora_dirs is not None:
        return list(_dev_lora_dirs)
    try:
        return [d for d in folder_paths.get_folder_paths("loras") if os.path.isdir(d)]
    except Exception:
        return []


def user_dir():
    base = _dev_user_dir
    if base is None:
        try:
            base = folder_paths.get_user_directory()
        except Exception:
            base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "user")
    d = os.path.join(base, "umbrae")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def _account_file():
    return os.path.join(user_dir(), "lora_account.json")


def _custom_file():
    return os.path.join(user_dir(), "lora_triggers.json")


def _previews_dir():
    return os.path.join(user_dir(), "lora_previews")


def _hash_cache():
    global _hc
    try:
        return _hc
    except NameError:
        _hc = H.HashCache(os.path.join(user_dir(), "lora_hashes.json"))
        return _hc


def account():
    acc = H.read_json(_account_file(), {})
    return acc if isinstance(acc, dict) else {}


# ── file resolution ──────────────────────────────────────────────────────────

def list_loras():
    if folder_paths is not None and _dev_lora_dirs is None:
        try:
            return list(folder_paths.get_filename_list("loras"))
        except Exception:
            pass
    out = []
    for root in lora_dirs():
        for dp, _dn, fns in os.walk(root):
            for fn in fns:
                if fn.lower().endswith(H.LORA_EXTS):
                    out.append(os.path.relpath(os.path.join(dp, fn), root))
    return sorted(set(out), key=str.lower)


def resolve(name):
    """A listed LoRA name -> a real path inside a loras dir, or None."""
    if not isinstance(name, str) or not name or ".." in name.replace("\\", "/").split("/"):
        return None
    roots = lora_dirs()
    if not roots:
        return None
    p = None
    if folder_paths is not None and _dev_lora_dirs is None:
        try:
            p = folder_paths.get_full_path("loras", name)
        except Exception:
            p = None
    if not p:
        for root in roots:
            cand = os.path.join(root, name)
            if os.path.isfile(cand):
                p = cand
                break
    if not p or not os.path.isfile(p) or not H.is_under(p, *roots):
        return None
    return p


def _rel_name(path):
    for root in lora_dirs():
        if H.is_under(path, root):
            return os.path.relpath(path, root)
    return os.path.basename(path)


# ── handlers ─────────────────────────────────────────────────────────────────

def handle_list():
    try:
        return {"ok": True, "loras": list_loras(), "roots": lora_dirs()}
    except Exception as e:
        return {"ok": False, "loras": [], "error": str(e)}


def _custom_store():
    s = H.read_json(_custom_file(), {})
    return s if isinstance(s, dict) else {}


def _preview_version(name):
    p = os.path.join(_previews_dir(), H.preview_filename(name))
    try:
        return int(os.path.getmtime(p)) if os.path.isfile(p) else 0
    except Exception:
        return 0


def handle_info(q):
    name = q.get("name", "")
    path = resolve(name)
    if not path:
        return {"ok": False, "message": "LoRA not found."}
    acc = account()
    try:
        info = H.build_lora_info(path, allow_adult=bool(acc.get("adult")))
    except Exception as e:
        return {"ok": False, "message": "Could not read: {}".format(e)}
    info["name"] = name
    info["custom_triggers"] = H.sanitize_words(_custom_store().get(H.custom_key(name), []))
    info["preview_v"] = _preview_version(name)
    info["custom_preview"] = info["preview_v"] > 0
    if info["custom_preview"]:
        info["has_preview"] = True
    return {"ok": True, "info": info}


def thumb_path(name):
    path = resolve(name)
    if not path:
        return None
    own = os.path.join(_previews_dir(), H.preview_filename(name))
    if os.path.isfile(own):
        return own
    prev = H.find_preview_path(path)
    return prev if prev and H.is_under(prev, *lora_dirs()) else None


def handle_civitai(q):
    name = q.get("name", "")
    path = resolve(name)
    if not path:
        return {"ok": False, "reason": "notfound", "message": "LoRA not found."}
    acc = account()
    if not q.get("force"):
        side = H.read_sidecar(path)
        if side:
            return {"ok": True, "found": True, "cached": True,
                    "info": H.parse_version(side, allow_adult=bool(acc.get("adult")))}
    try:
        sha = _hash_cache().get(path)
    except Exception as e:
        return {"ok": False, "reason": "offline", "message": "Could not read the file: {}".format(e)}
    try:
        ver = R.civitai_by_hash(sha, acc)
    except R.RemoteError as e:
        return {"ok": False, "reason": "offline", "message": str(e)}
    if not ver:
        return {"ok": True, "found": False, "reason": "notfound", "sha256": sha}
    H.save_sidecar(path, ver)
    return {"ok": True, "found": True, "info": H.parse_version(ver, allow_adult=bool(acc.get("adult")))}


def handle_civitai_search(q):
    acc = account()
    nsfw = q.get("nsfw")
    nsfw = None if nsfw in (None, "", "any") else (nsfw in ("1", "true", "True"))
    try:
        return {"ok": True, **R.civitai_search(
            q.get("q", ""), acc, base=q.get("base", ""), sort=q.get("sort", ""),
            nsfw=nsfw, cursor=q.get("cursor", ""), limit=q.get("limit", 24), period=q.get("period", ""))}
    except R.RemoteError as e:
        return {"ok": False, "message": str(e)}


def handle_hf_search(q):
    try:
        return {"ok": True, **R.hf_search(q.get("q", ""), account(), limit=q.get("limit", 24), sort=q.get("sort", "downloads"))}
    except R.RemoteError as e:
        return {"ok": False, "message": str(e)}


def handle_hf_repo(q):
    try:
        return {"ok": True, "repo": R.hf_repo(q.get("repo", ""), account())}
    except R.RemoteError as e:
        return {"ok": False, "message": str(e)}


def _download_root():
    roots = lora_dirs()
    return roots[0] if roots else None


def handle_download(data):
    root = _download_root()
    if not root:
        return {"ok": False, "message": "No loras folder is configured."}
    acc = account()
    source = "hf" if data.get("source") == "hf" else "civitai"
    url = str(data.get("url") or "")
    filename = H.safe_filename(data.get("filename") or os.path.basename(url.split("?")[0]) or "")
    subdir = H.safe_subdir(data.get("subdir") if data.get("subdir") is not None else acc.get("download_dir", ""))
    dest = os.path.join(root, *([subdir] if subdir else []), filename)
    if not H.is_under(dest, root):
        return {"ok": False, "message": "Bad destination."}
    if os.path.exists(dest) and not data.get("overwrite"):
        return {"ok": False, "exists": True, "name": _rel_name(dest),
                "message": "A file with that name is already there."}
    sidecar = data.get("sidecar") if isinstance(data.get("sidecar"), dict) else None
    try:
        jid = R.start_download(url, dest, acc, source=source, sidecar=sidecar)
    except R.RemoteError as e:
        return {"ok": False, "message": str(e)}
    return {"ok": True, "job": jid, "name": _rel_name(dest)}


def handle_download_status(q):
    st = R.job_status(q.get("job", ""))
    if st.get("ok") and st.get("state") == "done":
        st["name"] = _rel_name(R._jobs[st["id"]]["path"])
    return st


def handle_download_cancel(data):
    return {"ok": R.cancel_job(str(data.get("job") or ""))}


def handle_downloads():
    return {"ok": True, "jobs": R.active_jobs()}


def handle_account_get():
    return H.public_account(account())


def handle_account_set(data):
    acc = account()
    for field, key in (("civitai_key", "civitai_key"), ("hf_key", "hf_key")):
        if field in data:
            raw = data.get(field)
            if isinstance(raw, str) and raw.strip() == "":
                acc[key] = ""
            else:
                k = H.sanitize_key(raw)
                if not k:
                    return {"ok": False, "message": "That does not look like an API key."}
                acc[key] = k
    if data.get("host") in ("com", "red"):
        acc["host"] = data["host"]
    if "adult" in data:
        acc["adult"] = bool(data.get("adult"))
    if "download_dir" in data:
        acc["download_dir"] = H.safe_subdir(data.get("download_dir"))
    if not H.write_json(_account_file(), acc):
        return {"ok": False, "message": "Could not save the settings file."}
    return H.public_account(acc)


def handle_custom_triggers(data):
    name = str(data.get("name") or "")
    if not resolve(name):
        return {"ok": False, "message": "LoRA not found."}
    store = _custom_store()
    words = H.sanitize_words(data.get("words"))
    key = H.custom_key(name)
    if words:
        store[key] = words
    else:
        store.pop(key, None)
    if not H.write_json(_custom_file(), store):
        return {"ok": False, "message": "Could not save."}
    return {"ok": True, "words": words}


_MAGIC = (b"\x89PNG", b"\xff\xd8\xff", b"RIFF", b"GIF8")


def handle_preview_set(data):
    name = str(data.get("name") or "")
    if not resolve(name):
        return {"ok": False, "message": "LoRA not found."}
    raw = None
    if data.get("url"):
        try:
            raw = R.fetch_image(str(data["url"]))
        except Exception as e:
            return {"ok": False, "message": "Could not fetch the picture: {}".format(e)}
    else:
        du = str(data.get("dataUrl") or "")
        if "," not in du:
            return {"ok": False, "message": "Nothing to save."}
        try:
            raw = base64.b64decode(du.split(",", 1)[1])
        except Exception:
            return {"ok": False, "message": "That picture could not be read."}
    if not raw or len(raw) > 12 * 1024 * 1024 or not raw.startswith(_MAGIC):
        return {"ok": False, "message": "That is not a picture the browser can show."}
    folder = _previews_dir()
    try:
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, H.preview_filename(name)), "wb") as f:
            f.write(raw)
    except Exception as e:
        return {"ok": False, "message": "Could not save: {}".format(e)}
    return {"ok": True, "v": _preview_version(name)}


def handle_preview_delete(data):
    name = str(data.get("name") or "")
    if not resolve(name):
        return {"ok": False, "message": "LoRA not found."}
    p = os.path.join(_previews_dir(), H.preview_filename(name))
    try:
        if os.path.isfile(p):
            os.remove(p)
    except Exception as e:
        return {"ok": False, "message": "Could not remove: {}".format(e)}
    return {"ok": True}


def handle_civitai_delete(data):
    path = resolve(str(data.get("name") or ""))
    if not path:
        return {"ok": False, "message": "LoRA not found."}
    return {"ok": H.delete_sidecar(path)}


# ── aiohttp registration (ComfyUI) ───────────────────────────────────────────

def register():
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception as e:
        logger.warning("[umbrae lora loader] server not available (%s); routes disabled.", e)
        return False
    import asyncio

    routes = PromptServer.instance.routes
    NO_STORE = {"Cache-Control": "no-store"}

    def q_of(request):
        return {k: v for k, v in request.query.items()}

    async def body_of(request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        return data if isinstance(data, dict) else {}

    def get(path, fn, slow=False, with_query=True):
        async def _h(request):
            q = q_of(request)
            if slow:
                res = await asyncio.get_event_loop().run_in_executor(None, (lambda: fn(q)) if with_query else fn)
            else:
                res = fn(q) if with_query else fn()
            return web.json_response(res, headers=NO_STORE)
        routes.get(path)(_h)

    def post(path, fn, slow=False):
        async def _h(request):
            data = await body_of(request)
            if slow:
                res = await asyncio.get_event_loop().run_in_executor(None, lambda: fn(data))
            else:
                res = fn(data)
            return web.json_response(res, headers=NO_STORE)
        routes.post(path)(_h)

    get("/umbrae/lora/list", handle_list, with_query=False)
    get("/umbrae/lora/info", handle_info, slow=True)
    get("/umbrae/lora/civitai", handle_civitai, slow=True)
    get("/umbrae/lora/civitai/search", handle_civitai_search, slow=True)
    get("/umbrae/lora/hf/search", handle_hf_search, slow=True)
    get("/umbrae/lora/hf/repo", handle_hf_repo, slow=True)
    post("/umbrae/lora/download", handle_download)
    get("/umbrae/lora/download/status", handle_download_status)
    get("/umbrae/lora/downloads", handle_downloads, with_query=False)
    post("/umbrae/lora/download/cancel", handle_download_cancel)
    get("/umbrae/lora/account", handle_account_get, with_query=False)
    post("/umbrae/lora/account", handle_account_set)
    post("/umbrae/lora/custom_triggers", handle_custom_triggers)
    post("/umbrae/lora/preview", handle_preview_set, slow=True)
    post("/umbrae/lora/preview_delete", handle_preview_delete)
    post("/umbrae/lora/civitai_delete", handle_civitai_delete)

    @routes.get("/umbrae/lora/thumb")
    async def _thumb(request):
        p = thumb_path(request.query.get("name", ""))
        if not p:
            return web.Response(status=404)
        return web.FileResponse(p, headers={"Cache-Control": "public, max-age=3600"})

    logger.info("[umbrae lora loader] routes registered.")
    return True
