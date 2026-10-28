# umbrae_nodes/modules/lora_loader/helpers.py — umbrae_nodes v0.9.3
#
# Pure helpers for "lora loader [umbrae]". Stdlib only: no comfy, no torch, no
# folder_paths, no sockets. Everything reads a file or a dict and returns data,
# so it runs under dev/lora_dev_server.py without ComfyUI.
#
#   safetensors header   read_safetensors_metadata / derive_trigger_words /
#                        explicit_trigger_words / base_model_family / build_lora_info
#   sidecars             read_sidecar / save_sidecar / delete_sidecar  (<base>.civitai.info,
#                        the same file other Civitai helpers write, so they share it)
#   previews             find_preview_path, custom preview store (user dir)
#   Civitai parsing      parse_version (one model-version -> info dict),
#                        parse_search (models search -> cards), strip_html
#   HF parsing           parse_hf_search / parse_hf_repo
#   node state           parse_state / collect_triggers
#   small stores         account (API keys + prefs), custom trigger words
import hashlib
import html
import json
import os
import re
import struct
import threading
import urllib.parse

_MAX_HEADER_BYTES = 200 * 1024 * 1024
_MAX_TRIGGERS = 24
_MAX_WORD_LEN = 200
_MAX_WORDS = 64

PREVIEW_EXTS = (
    ".preview.png", ".preview.jpeg", ".preview.jpg", ".preview.webp",
    ".png", ".jpg", ".jpeg", ".webp",
)
LORA_EXTS = (".safetensors", ".sft", ".ckpt", ".pt", ".pth", ".bin")

_lock = threading.Lock()


# ── safetensors header ───────────────────────────────────────────────────────

def read_safetensors_metadata(path):
    """The file's __metadata__ dict (str->str), or {} on any problem. Reads only the
    header, never the tensors."""
    try:
        with open(path, "rb") as f:
            raw = f.read(8)
            if len(raw) != 8:
                return {}
            n = struct.unpack("<Q", raw)[0]
            if n <= 0 or n > _MAX_HEADER_BYTES:
                return {}
            head = f.read(n)
            if len(head) != n:
                return {}
        obj = json.loads(head)
    except Exception:
        return {}
    meta = obj.get("__metadata__") if isinstance(obj, dict) else None
    if not isinstance(meta, dict):
        return {}
    return {str(k): (v if isinstance(v, str) else json.dumps(v)) for k, v in meta.items()}


def _as_json(val):
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return None
    return None


def _split_phrase(phrase):
    out = []
    for w in re.split(r"[,\n]", phrase or ""):
        w = w.strip()
        if w:
            out.append(w[:_MAX_WORD_LEN])
    return out


def explicit_trigger_words(meta, limit=_MAX_TRIGGERS):
    """Only the words the author declared (modelspec.trigger_phrase / ss_trigger_words)."""
    phrase = meta.get("modelspec.trigger_phrase") or meta.get("ss_trigger_words") or ""
    out, seen = [], set()
    for w in _split_phrase(phrase):
        k = w.lower()
        if k not in seen:
            seen.add(k)
            out.append(w)
        if len(out) >= limit:
            break
    return out


def derive_trigger_words(meta, limit=_MAX_TRIGGERS):
    """Declared phrase first, then the most frequent training tags (ss_tag_frequency)."""
    out = list(explicit_trigger_words(meta, limit))
    seen = {w.lower() for w in out}
    freq = _as_json(meta.get("ss_tag_frequency"))
    counts = {}
    if isinstance(freq, dict):
        for _ds, tags in freq.items():
            if not isinstance(tags, dict):
                continue
            for tag, n in tags.items():
                try:
                    counts[str(tag).strip()] = counts.get(str(tag).strip(), 0) + int(n)
                except Exception:
                    pass
    for tag, _n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        if not tag or tag.lower() in seen:
            continue
        seen.add(tag.lower())
        out.append(tag[:_MAX_WORD_LEN])
        if len(out) >= limit:
            break
    return out


def base_model_family(meta):
    arch = str(meta.get("modelspec.architecture") or "").lower()
    base = str(meta.get("ss_base_model_version") or "").lower()
    s = arch + " " + base
    for key, label in (
        ("flux", "Flux"), ("sd3", "SD 3"), ("sdxl", "SDXL"), ("pony", "Pony"),
        ("illustrious", "Illustrious"), ("sd-v2", "SD 2"), ("sd_v2", "SD 2"),
        ("sd-v1", "SD 1.5"), ("sd_v1", "SD 1.5"), ("v1-5", "SD 1.5"),
        ("hunyuan", "Hunyuan"), ("wan", "Wan"), ("lumina", "Lumina"), ("qwen", "Qwen"),
    ):
        if key in s:
            return label
    if arch:
        return arch.split("/")[0]
    return ""


def _title_from_meta(meta, lora_path):
    for k in ("modelspec.title", "ss_output_name"):
        v = meta.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return os.path.splitext(os.path.basename(lora_path))[0]


# ── sidecar (<base>.civitai.info) ────────────────────────────────────────────

def sidecar_path(lora_path):
    return os.path.splitext(lora_path)[0] + ".civitai.info"


def read_sidecar(lora_path):
    """The raw Civitai model-version JSON saved next to the LoRA, or None."""
    for p in (sidecar_path(lora_path), os.path.splitext(lora_path)[0] + ".json"):
        if not os.path.isfile(p):
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                obj = json.load(f)
        except Exception:
            continue
        if isinstance(obj, dict) and (obj.get("trainedWords") is not None or obj.get("modelId")
                                      or obj.get("model") or obj.get("images")):
            return obj
    return None


def save_sidecar(lora_path, obj):
    try:
        with open(sidecar_path(lora_path), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        return True
    except Exception:
        return False


def delete_sidecar(lora_path):
    try:
        p = sidecar_path(lora_path)
        if os.path.isfile(p):
            os.remove(p)
        return True
    except Exception:
        return False


def find_preview_path(lora_path):
    base = os.path.splitext(lora_path)[0]
    for ext in PREVIEW_EXTS:
        p = base + ext
        if os.path.isfile(p):
            return p
    return None


# ── Civitai parsing ──────────────────────────────────────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<\s*(br|/p|/div|/li|/h\d)\s*/?>", re.I)


def strip_html(s, limit=4000):
    if not isinstance(s, str) or not s:
        return ""
    s = _BR_RE.sub("\n", s)
    s = _TAG_RE.sub("", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    return s[:limit]


_ORIGINAL_SEG_RE = re.compile(r"/original=true(?:,[^/]*)?/")
_WIDTH_SEG_RE = re.compile(r"/width=\d+(?:,[^/]*)?/")


def image_url(url, width=None):
    """Civitai image URL at a given width (None = full size)."""
    if not isinstance(url, str):
        return url
    seg = "/original=true/" if width is None else "/width={}/".format(int(width))
    if _ORIGINAL_SEG_RE.search(url):
        return _ORIGINAL_SEG_RE.sub(seg, url, count=1)
    if _WIDTH_SEG_RE.search(url):
        return _WIDTH_SEG_RE.sub(seg, url, count=1)
    return url


def _int(v):
    try:
        return int(v)
    except Exception:
        return None


def nsfw_level(im):
    lv = _int(im.get("nsfwLevel"))
    if lv is not None:
        return lv
    n = im.get("nsfw")
    if n in (True, "X", "XXX"):
        return 8
    if n in ("Mature", "R"):
        return 4
    if n == "Soft":
        return 2
    return 1


def parse_images(imgs, allow_adult=True, limit=24):
    out = []
    for im in imgs or []:
        if not isinstance(im, dict) or not im.get("url"):
            continue
        lv = nsfw_level(im)
        if not allow_adult and lv >= 4:
            continue
        meta = im.get("meta") if isinstance(im.get("meta"), dict) else {}
        out.append({
            "url": image_url(im["url"], None),
            "thumb": image_url(im["url"], 320),
            "medium": image_url(im["url"], 1024),
            "nsfw": lv,
            "w": _int(im.get("width")), "h": _int(im.get("height")),
            "type": im.get("type") or "image",
            "prompt": str(meta.get("prompt") or "")[:2000] if meta else "",
        })
        if len(out) >= limit:
            break
    return out


def parse_version(obj, allow_adult=True):
    """One Civitai model-version object (by-hash answer, or one entry of a model's
    modelVersions) -> the info dict the panel shows. Never raises."""
    if not isinstance(obj, dict):
        return {}
    model = obj.get("model") if isinstance(obj.get("model"), dict) else {}
    extra = obj.get("umbrae_model") if isinstance(obj.get("umbrae_model"), dict) else {}
    tw = obj.get("trainedWords")
    files = []
    for f in obj.get("files") or []:
        if not isinstance(f, dict):
            continue
        files.append({
            "id": _int(f.get("id")), "name": str(f.get("name") or ""),
            "sizeKB": f.get("sizeKB"), "type": f.get("type"),
            "primary": bool(f.get("primary")),
            "url": f.get("downloadUrl") or obj.get("downloadUrl"),
            "sha256": ((f.get("hashes") or {}).get("SHA256") or "").lower(),
            "fp": (f.get("metadata") or {}).get("fp"), "format": (f.get("metadata") or {}).get("format"),
        })
    stats = obj.get("stats") if isinstance(obj.get("stats"), dict) else {}
    info = {
        "name": str(model.get("name") or extra.get("name") or ""),
        "version_name": str(obj.get("name") or ""),
        "type": str(model.get("type") or extra.get("type") or ""),
        "base_model": str(obj.get("baseModel") or ""),
        "triggers": [str(w).strip() for w in tw if str(w).strip()] if isinstance(tw, list) else [],
        "model_id": _int(obj.get("modelId")),
        "version_id": _int(obj.get("id")),
        "description": strip_html(extra.get("description") or ""),
        "version_notes": strip_html(obj.get("description") or "", 1500),
        "tags": [str(t) for t in (extra.get("tags") or [])][:20],
        "creator": str((extra.get("creator") or {}).get("username") or ""),
        "nsfw": bool(model.get("nsfw") or extra.get("nsfw")),
        "published": str(obj.get("publishedAt") or obj.get("createdAt") or "")[:10],
        "downloads": _int(stats.get("downloadCount")),
        "likes": _int(stats.get("thumbsUpCount")),
        "images": parse_images(obj.get("images"), allow_adult=allow_adult),
        "files": files,
        "download_url": obj.get("downloadUrl"),
    }
    if info["model_id"]:
        info["url"] = "https://civitai.com/models/{}".format(info["model_id"]) + (
            "?modelVersionId={}".format(info["version_id"]) if info["version_id"] else "")
    elif isinstance(obj.get("umbrae_url"), str) and obj["umbrae_url"].startswith("https://"):
        info["url"] = obj["umbrae_url"][:300]
    info["source"] = str(obj.get("umbrae_source") or "civitai")
    return info


def model_summary(model_obj):
    """The parts of a /models/{id} (or search item) answer worth keeping in the sidecar."""
    if not isinstance(model_obj, dict):
        return {}
    return {
        "name": model_obj.get("name"), "type": model_obj.get("type"),
        "description": model_obj.get("description"), "tags": model_obj.get("tags"),
        "creator": model_obj.get("creator"), "nsfw": model_obj.get("nsfw"),
        "stats": model_obj.get("stats"),
    }


def parse_search(data, allow_adult=True):
    """Civitai /models search -> {items:[card], next}. Each card carries its versions
    (with files and images) so the detail view needs no second request."""
    items = []
    for m in (data or {}).get("items") or []:
        if not isinstance(m, dict):
            continue
        versions = []
        for v in m.get("modelVersions") or []:
            if not isinstance(v, dict):
                continue
            vv = dict(v)
            vv.setdefault("modelId", m.get("id"))
            vv["model"] = {"name": m.get("name"), "type": m.get("type"), "nsfw": m.get("nsfw")}
            vv["umbrae_model"] = model_summary(m)
            versions.append(parse_version(vv, allow_adult=allow_adult))
        thumb = ""
        for v in versions:
            if v.get("images"):
                thumb = v["images"][0]["thumb"]
                break
        stats = m.get("stats") if isinstance(m.get("stats"), dict) else {}
        items.append({
            "id": _int(m.get("id")), "name": str(m.get("name") or ""),
            "type": str(m.get("type") or ""), "nsfw": bool(m.get("nsfw")),
            "nsfw_level": _int(m.get("nsfwLevel")),
            "base_models": [str(b) for b in (m.get("baseModels") or [])] or
                           sorted({v["base_model"] for v in versions if v.get("base_model")}),
            "tags": [str(t) for t in (m.get("tags") or [])][:12],
            "creator": str((m.get("creator") or {}).get("username") or ""),
            "downloads": _int(stats.get("downloadCount")), "likes": _int(stats.get("thumbsUpCount")),
            "thumb": thumb,
            "description": strip_html(m.get("description") or "", 3000),
            "url": "https://civitai.com/models/{}".format(m.get("id")),
            "versions": versions,
        })
    meta = (data or {}).get("metadata") or {}
    return {"items": items, "next": meta.get("nextCursor") or ""}


# ── Hugging Face parsing ─────────────────────────────────────────────────────

def _hf_base(tags):
    out = []
    for t in tags or []:
        t = str(t)
        if t.startswith("base_model:") and ":adapter:" not in t:
            out.append(t.split(":", 1)[1])
    return out


def parse_hf_search(data):
    items = []
    for m in data or []:
        if not isinstance(m, dict):
            continue
        rid = str(m.get("id") or m.get("modelId") or "")
        if not rid:
            continue
        files = [str(s.get("rfilename")) for s in (m.get("siblings") or [])
                 if isinstance(s, dict) and str(s.get("rfilename", "")).lower().endswith(LORA_EXTS)]
        items.append({
            "id": rid, "name": rid.split("/")[-1], "author": str(m.get("author") or rid.split("/")[0]),
            "likes": _int(m.get("likes")), "downloads": _int(m.get("downloads")),
            "updated": str(m.get("lastModified") or "")[:10],
            "base_models": _hf_base(m.get("tags")),
            "tags": [str(t) for t in (m.get("tags") or []) if ":" not in str(t)][:12],
            "gated": bool(m.get("gated")), "private": bool(m.get("private")),
            "files": files,
            "url": "https://huggingface.co/" + rid,
        })
    return {"items": items}


def parse_hf_repo(data):
    """/api/models/{repo}?blobs=true -> files with sizes, card text, preview images."""
    if not isinstance(data, dict):
        return {}
    rid = str(data.get("id") or data.get("modelId") or "")
    files, images = [], []
    for s in data.get("siblings") or []:
        if not isinstance(s, dict):
            continue
        name = str(s.get("rfilename") or "")
        low = name.lower()
        url = "https://huggingface.co/{}/resolve/main/{}".format(rid, urllib.parse.quote(name))
        if low.endswith(LORA_EXTS):
            files.append({"name": name, "size": _int(s.get("size")), "url": url})
        elif low.endswith((".png", ".jpg", ".jpeg", ".webp")) and len(images) < 12:
            images.append({"url": url, "thumb": url, "medium": url, "nsfw": 1, "type": "image"})
    card = data.get("cardData") if isinstance(data.get("cardData"), dict) else {}
    words = card.get("instance_prompt") or card.get("trigger_words") or card.get("widget", [{}])
    triggers = []
    if isinstance(words, str):
        triggers = _split_phrase(words)
    elif isinstance(words, list):
        for w in words:
            if isinstance(w, dict) and w.get("text"):
                triggers.append(str(w["text"])[:_MAX_WORD_LEN])
            elif isinstance(w, str):
                triggers.append(w[:_MAX_WORD_LEN])
    return {
        "id": rid, "files": files, "images": images, "triggers": triggers[:_MAX_TRIGGERS],
        "base_models": _hf_base(data.get("tags")),
        "license": str(card.get("license") or ""),
        "gated": bool(data.get("gated")),
        "url": "https://huggingface.co/" + rid,
    }


# ── full offline info for one LoRA ───────────────────────────────────────────

def build_lora_info(lora_path, allow_adult=True):
    meta = read_safetensors_metadata(lora_path)
    file_triggers = derive_trigger_words(meta)
    info = {
        "title": _title_from_meta(meta, lora_path),
        "base_model": base_model_family(meta),
        "rank": meta.get("ss_network_dim", "") or "",
        "alpha": meta.get("ss_network_alpha", "") or "",
        "num_images": meta.get("ss_num_train_images", "") or "",
        "date": (meta.get("modelspec.date", "") or "")[:10],
        "file_triggers": file_triggers,
        "explicit_triggers": explicit_trigger_words(meta),
        "has_meta": bool(meta),
        "has_preview": find_preview_path(lora_path) is not None,
        "size": None,
        "civitai": None,
    }
    try:
        info["size"] = os.path.getsize(lora_path)
    except Exception:
        pass
    side = read_sidecar(lora_path)
    if side:
        civ = parse_version(side, allow_adult=allow_adult)
        if civ:
            info["civitai"] = civ
            if civ.get("name"):
                info["title"] = civ["name"]
            if civ.get("base_model"):
                info["base_model"] = civ["base_model"]
    return info


# ── node state ───────────────────────────────────────────────────────────────

def _strength(v):
    try:
        f = float(v)
    except Exception:
        return 0.0
    if f != f or f in (float("inf"), float("-inf")):
        return 0.0
    return max(-100.0, min(100.0, f))


def parse_state(raw):
    """The hidden state JSON -> {loras:[{name,on,sm,sc,triggers}], sep, cacheMode}."""
    try:
        st = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except Exception:
        st = {}
    if not isinstance(st, dict):
        st = {}
    loras = []
    for e in st.get("loras") or []:
        if not isinstance(e, dict):
            continue
        name = e.get("name")
        if not isinstance(name, str) or not name:
            continue
        tr = e.get("triggers")
        loras.append({
            "name": name, "on": bool(e.get("on", True)),
            "sm": _strength(e.get("sm", 1.0)), "sc": _strength(e.get("sc", e.get("sm", 1.0))),
            "triggers": [str(w).strip() for w in tr if str(w).strip()][:_MAX_WORDS]
                        if isinstance(tr, list) else [],
        })
    sep = st.get("sep")
    cm = st.get("cacheMode")
    return {
        "loras": loras[:64],
        "sep": sep if isinstance(sep, str) else ", ",
        "cacheMode": cm if cm in ("last", "all", "none") else "last",
    }


def collect_triggers(rows, sep=", "):
    out, seen = [], set()
    for e in rows:
        if not e.get("on"):
            continue
        for w in e.get("triggers", []):
            k = w.lower()
            if w and k not in seen:
                seen.add(k)
                out.append(w)
    return sep.join(out)


# ── file hashing with a cache ────────────────────────────────────────────────

def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class HashCache:
    """sha256 per (path, size, mtime), in one JSON file."""

    def __init__(self, path):
        self.path = path
        self.data = None

    def _load(self):
        if self.data is None:
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except Exception:
                self.data = {}
            if not isinstance(self.data, dict):
                self.data = {}

    def get(self, path):
        with _lock:
            self._load()
            try:
                st = os.stat(path)
            except Exception:
                return None
            key = "{}|{}|{}".format(os.path.normcase(path), st.st_size, int(st.st_mtime))
            v = self.data.get(key)
            if isinstance(v, str) and len(v) == 64:
                return v
        sha = file_sha256(path)
        with _lock:
            self.data[key] = sha
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(self.path, "w", encoding="utf-8") as f:
                    json.dump(self.data, f)
            except Exception:
                pass
        return sha


# ── small JSON stores (account, custom words) ────────────────────────────────

def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, type(default)) else default
    except Exception:
        return default


def write_json(path, obj):
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


_KEY_RE = re.compile(r"^[A-Za-z0-9_\-\.]{8,200}$")


def sanitize_key(raw):
    s = str(raw or "").strip()
    return s if _KEY_RE.match(s) else ""


def mask_key(key):
    return ("…" + key[-4:]) if key and len(key) >= 8 else ""


def public_account(acc):
    return {
        "ok": True,
        "civitai": bool(acc.get("civitai_key")), "civitai_hint": mask_key(acc.get("civitai_key", "")),
        "hf": bool(acc.get("hf_key")), "hf_hint": mask_key(acc.get("hf_key", "")),
        "host": acc.get("host") if acc.get("host") in ("com", "red") else "com",
        "adult": bool(acc.get("adult", False)),
        "download_dir": str(acc.get("download_dir") or ""),
    }


def civitai_hosts(pref):
    return ("civitai.red", "civitai.com") if pref == "red" else ("civitai.com", "civitai.red")


def sanitize_words(words):
    out, seen = [], set()
    for w in words if isinstance(words, list) else []:
        w = re.sub(r"\s+", " ", str(w)).strip()[:_MAX_WORD_LEN]
        if w and w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
        if len(out) >= _MAX_WORDS:
            break
    return out


def custom_key(name):
    return str(name or "").replace("\\", "/").strip().lower()


# ── download target names ────────────────────────────────────────────────────

_BAD_CHARS = re.compile(r'[<>:"|?*\x00-\x1f]')


def safe_filename(name, fallback="lora.safetensors"):
    s = _BAD_CHARS.sub("_", str(name or "")).replace("\\", "_").replace("/", "_").strip(" .")
    if not s:
        return fallback
    if not s.lower().endswith(LORA_EXTS):
        s += ".safetensors"
    return s[:180]


def safe_subdir(sub):
    parts = []
    for p in str(sub or "").replace("\\", "/").split("/"):
        p = _BAD_CHARS.sub("_", p).strip(" .")
        if p and p not in (".", ".."):
            parts.append(p[:80])
    return "/".join(parts[:6])


def is_under(path, *roots):
    try:
        rp = os.path.realpath(path)
    except Exception:
        return False
    for r in roots:
        try:
            rr = os.path.realpath(r)
        except Exception:
            continue
        if rp == rr or rp.startswith(rr.rstrip(os.sep) + os.sep):
            return True
    return False


def preview_filename(name):
    return hashlib.sha1(custom_key(name).encode("utf-8")).hexdigest()[:16] + ".jpg"
