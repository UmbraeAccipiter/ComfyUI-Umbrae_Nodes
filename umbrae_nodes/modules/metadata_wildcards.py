# metadata_wildcards.py — UNP v0.8
#
# Shared metadata extraction and wildcard resolution.
#
# Reads ComfyUI-embedded generation metadata from saved images:
#   PNG  — text chunks "prompt" (flattened API prompt) and "workflow" (graph)
#   WEBP/JPG — EXIF Make (0x010F) = "workflow:{json}", Model (0x0110) = "prompt:{json}"
# and extracts named fields by walking the flattened prompt graph, so values
# like {model} come from the loader actually wired into the sampler rather
# than from a class-type guess.
#
# Wildcard tokens resolved here (metadata + date/time only — index tokens
# {i}/{z#}/{seq}/{zseq#}/{stem}/{base} remain the save node's concern):
#   {model} {diffusion_model} {checkpoint} {seed} {steps} {cfg} {sampler}
#   {scheduler} {denoise} {vae} {clip} {lora} {upscale_model} {controlnet}
#   {loaded_image} {width} {height} {size}
#   Every metadata token also has indexed forms — {model2} {seed2} {clip2}
#   {lora3} … — for workflows with multiple samplers/loaders. Sampler-bound
#   fields (model/seed/steps/cfg/sampler/scheduler/denoise) are numbered in
#   execution order (a refiner sampler fed by another sampler is 2); loader
#   fields (checkpoint/diffusion_model/vae/clip/lora/controlnet/
#   upscale_model/loaded_image) are numbered in node-id order, with dual
#   loaders (DualCLIPLoader, Power Lora Loader) contributing one entry per
#   file. Bare {name} means instance 1, except {model}/{vae}/{clip} which
#   follow the wire actually feeding the first sampler / VAEDecode /
#   CLIPTextEncode when traceable.
#   {date} {date:FMT}            FMT tokens: YYYY YYY YY MM DD  (default YYYY-MM-DD)
#   {time} {time:12} {time:24} {time:12:FMT} {time:24:FMT}
#                                FMT tokens: HH MM SS (default HH-MM-SS, 24h;
#                                12h appends -AM / -PM)
# Missing metadata resolves to "unknown-<name>-". Unrecognized token names
# are left untouched. All substituted values are sanitized so a wildcard can
# never introduce path separators — folder structure comes only from literal
# / or \ in the pattern itself.

import json
import os
import re
from datetime import datetime

from PIL import Image

MODEL_EXTS = (".safetensors", ".ckpt", ".gguf", ".sft", ".pt", ".pth")

METADATA_FIELDS = (
    "model", "diffusion_model", "checkpoint", "seed", "steps", "cfg",
    "sampler", "scheduler", "denoise", "vae", "clip", "lora",
    "upscale_model", "controlnet", "loaded_image", "width", "height", "size",
)

_TOKEN_RX = re.compile(r"\{([A-Za-z_]+\d*)(?::([^{}]*))?\}")


# ── file reading ──────────────────────────────────────────────────────────────

def read_embedded(path):
    """Return {"prompt": dict|None, "workflow": dict|None,
               "prompt_raw": str|None, "workflow_raw": str|None}."""
    out = {"prompt": None, "workflow": None, "prompt_raw": None, "workflow_raw": None}
    try:
        with Image.open(path) as im:
            info = dict(getattr(im, "text", {}) or {})
            info.update({k: v for k, v in im.info.items() if isinstance(v, str)})
            pr = info.get("prompt")
            wf = info.get("workflow")
            if pr is None or wf is None:
                try:
                    exif = im.getexif()
                    make  = exif.get(0x010F)  # "workflow:{...}"
                    model = exif.get(0x0110)  # "prompt:{...}"
                    if wf is None and isinstance(make, str) and make.startswith("workflow:"):
                        wf = make[len("workflow:"):]
                    if pr is None and isinstance(model, str) and model.startswith("prompt:"):
                        pr = model[len("prompt:"):]
                except Exception:
                    pass
            if pr:
                out["prompt_raw"] = pr
                try:
                    out["prompt"] = json.loads(pr)
                except Exception:
                    pass
            if wf:
                out["workflow_raw"] = wf
                try:
                    out["workflow"] = json.loads(wf)
                except Exception:
                    pass
    except Exception:
        pass
    return out


def file_times(path):
    """(created, modified) epoch seconds. Creation: st_birthtime where the
    platform exposes it, st_ctime on Windows (creation there), else mtime
    (Linux st_ctime is inode-change time, not creation)."""
    st = os.stat(path)
    if hasattr(st, "st_birthtime"):
        created = st.st_birthtime
    elif os.name == "nt":
        created = st.st_ctime
    else:
        created = st.st_mtime
    return created, st.st_mtime


# ── prompt graph walking ──────────────────────────────────────────────────────

def _is_link(v):
    return isinstance(v, (list, tuple)) and len(v) == 2 and str(v[0]).isdigit() is not False


def _node(prompt, link):
    try:
        return prompt.get(str(link[0]))
    except Exception:
        return None


def _model_name(value):
    if isinstance(value, str) and value.lower().endswith(MODEL_EXTS):
        return os.path.splitext(os.path.basename(value.replace("\\", "/")))[0]
    return None


def _loader_name(node):
    """If node carries a model-file input, return its stripped name."""
    if not node:
        return None
    ins = node.get("inputs", {})
    for key in ("unet_name", "ckpt_name", "model_name", "vae_name",
                "clip_name", "control_net_name"):
        n = _model_name(ins.get(key))
        if n:
            return n
    # DualCLIPLoader-style clip_name1/clip_name2
    multi = [_model_name(ins[k]) for k in sorted(ins) if k.startswith("clip_name")]
    multi = [m for m in multi if m]
    if multi:
        return "+".join(multi)
    for v in ins.values():
        n = _model_name(v)
        if n:
            return n
    return None


def _walk(prompt, link, keys, max_depth=32):
    """Follow named inputs upstream from `link` to the end of the chain and
    return the model name found there. Pass-through nodes (LoRA loaders,
    ModelSampling, guiders, etc.) are traversed — a node only counts as the
    loader once it has no further link to follow, so a LoraLoader's
    lora_name can never shadow the model behind it."""
    seen = set()
    for _ in range(max_depth):
        node = _node(prompt, link)
        if node is None or id(node) in seen:
            return None
        seen.add(id(node))
        ins = node.get("inputs", {})
        nxt = None
        for k in keys:
            v = ins.get(k)
            if _is_link(v):
                nxt = v
                break
        if nxt is None:
            return _loader_name(node)
        link = nxt
    return None


def _first_by_class(prompt, class_names):
    for nid in sorted(prompt, key=lambda s: int(s) if str(s).isdigit() else 0):
        node = prompt[nid]
        if node.get("class_type") in class_names:
            return node
    return None


def _all_by_class(prompt, class_names):
    return [(nid, prompt[nid])
            for nid in sorted(prompt, key=lambda s: int(s) if str(s).isdigit() else 0)
            if prompt[nid].get("class_type") in class_names]


_SAMPLER_CLASSES = ("KSampler", "KSamplerAdvanced", "SamplerCustomAdvanced",
                    "SamplerCustom", "KSampler (Efficient)")


def _upstream_sampler_count(prompt, nid, sampler_ids):
    """Number of distinct sampler nodes reachable upstream of `nid` — gives
    execution order: a refiner fed by another sampler counts higher."""
    seen, found, stack = set(), set(), [str(nid)]
    while stack:
        cur = stack.pop()
        node = prompt.get(cur)
        if node is None:
            continue
        for v in node.get("inputs", {}).values():
            if _is_link(v):
                up = str(v[0])
                if up in seen:
                    continue
                seen.add(up)
                if up in sampler_ids and up != str(nid):
                    found.add(up)
                stack.append(up)
    return len(found)


def _sampler_field(prompt, sampler, direct_keys, hop_key=None, hop_field=None):
    """Value from the sampler node itself, or one hop upstream (e.g. steps
    lives on BasicScheduler behind the `sigmas` input of SamplerCustom)."""
    ins = sampler.get("inputs", {})
    for k in direct_keys:
        v = ins.get(k)
        if v is not None and not _is_link(v):
            return v
    if hop_key and _is_link(ins.get(hop_key)):
        hop = _node(prompt, ins[hop_key])
        if hop:
            v = hop.get("inputs", {}).get(hop_field)
            if v is not None and not _is_link(v):
                return v
    return None


def _trailing_int(key):
    m = re.search(r"(\d+)$", key)
    return int(m.group(1)) if m else 0


def _lora_names(node):
    """LoRA file names from a loader node, in slot order. Handles plain
    LoraLoader (lora_name) and Power Lora Loader (rgthree) style inputs
    (lora_1/lora_2/… dicts with on/lora keys — disabled entries skipped)."""
    ins = node.get("inputs", {})
    names = []
    n = _model_name(ins.get("lora_name"))
    if n:
        names.append(n)
    for key in sorted((k for k, v in ins.items() if isinstance(v, dict) and "lora" in v),
                      key=_trailing_int):
        entry = ins[key]
        if entry.get("on") is False:
            continue
        n = _model_name(entry.get("lora"))
        if n:
            names.append(n)
    return names


def _emit(out, name, values, bare=None):
    """Write name1..nameN for `values`, and bare `name` (walked value if
    given, else first instance)."""
    for i, v in enumerate(values, 1):
        out[f"{name}{i}"] = v
    bare = bare if bare not in (None, "") else (values[0] if values else None)
    if bare not in (None, ""):
        out[name] = bare


def extract_fields(prompt):
    """Extract generation fields from a flattened prompt dict. Missing values
    are simply absent from the result."""
    out = {}
    if not isinstance(prompt, dict):
        return out

    # ---- samplers, in execution order ----
    samplers = _all_by_class(prompt, _SAMPLER_CLASSES)
    sampler_ids = {nid for nid, _ in samplers}
    samplers.sort(key=lambda p: (_upstream_sampler_count(prompt, p[0], sampler_ids),
                                 int(p[0]) if str(p[0]).isdigit() else 0))

    models, seeds, steps_l, cfgs, smps, schs, dens = [], [], [], [], [], [], []
    for nid, sampler in samplers:
        ins = sampler.get("inputs", {})
        name = None
        for entry_key in ("model", "guider"):
            if _is_link(ins.get(entry_key)):
                name = _walk(prompt, ins[entry_key], ("model", "guider"))
                if name:
                    break
        models.append(name)
        seeds.append(_sampler_field(prompt, sampler, ("seed", "noise_seed"),
                                    hop_key="noise", hop_field="noise_seed"))
        steps_l.append(_sampler_field(prompt, sampler, ("steps",),
                                      hop_key="sigmas", hop_field="steps"))
        cfgs.append(_sampler_field(prompt, sampler, ("cfg",),
                                   hop_key="guider", hop_field="cfg"))
        smps.append(_sampler_field(prompt, sampler, ("sampler_name",),
                                   hop_key="sampler", hop_field="sampler_name"))
        schs.append(_sampler_field(prompt, sampler, ("scheduler",),
                                   hop_key="sigmas", hop_field="scheduler"))
        dens.append(_sampler_field(prompt, sampler, ("denoise",),
                                   hop_key="sigmas", hop_field="denoise"))

    def _emit_sampler(name, values):
        for i, v in enumerate(values, 1):
            if v is not None:
                out[f"{name}{i}"] = v
        first = next((v for v in values if v is not None), None)
        if values and values[0] is not None:
            out[name] = values[0]
        elif first is not None:
            out[name] = first

    _emit_sampler("model", models)
    _emit_sampler("seed", seeds)
    _emit_sampler("steps", steps_l)
    _emit_sampler("cfg", cfgs)
    _emit_sampler("sampler", smps)
    _emit_sampler("scheduler", schs)
    _emit_sampler("denoise", dens)

    # ---- loaders, in node-id order ----
    ckpts = [n for _, nd in _all_by_class(prompt, ("CheckpointLoaderSimple", "CheckpointLoader",
                                                    "CheckpointLoaderNF4"))
             if (n := _loader_name(nd))]
    _emit(out, "checkpoint", ckpts)

    unets = [n for _, nd in _all_by_class(prompt, ("UNETLoader", "UnetLoaderGGUF"))
             if (n := _loader_name(nd))]
    _emit(out, "diffusion_model", unets)

    if "model" not in out:
        n = out.get("checkpoint") or out.get("diffusion_model")
        if n:
            out["model"] = n

    vaes = [n for _, nd in _all_by_class(prompt, ("VAELoader",)) if (n := _loader_name(nd))]
    vae_bare = None
    vae_user = _first_by_class(prompt, ("VAEDecode", "VAEDecodeTiled", "VAEEncode"))
    if vae_user and _is_link(vae_user.get("inputs", {}).get("vae")):
        vae_bare = _walk(prompt, vae_user["inputs"]["vae"], ("vae",))
    _emit(out, "vae", vaes, bare=vae_bare)

    clips = []
    for _, nd in _all_by_class(prompt, ("CLIPLoader", "DualCLIPLoader", "TripleCLIPLoader",
                                         "CLIPLoaderGGUF", "DualCLIPLoaderGGUF")):
        ins = nd.get("inputs", {})
        keys = sorted((k for k in ins if k.startswith("clip_name")), key=_trailing_int)
        for k in keys or ("clip_name",):
            n = _model_name(ins.get(k))
            if n:
                clips.append(n)
    clip_bare = None
    clip_user = _first_by_class(prompt, ("CLIPTextEncode",))
    if clip_user and _is_link(clip_user.get("inputs", {}).get("clip")):
        clip_bare = _walk(prompt, clip_user["inputs"]["clip"], ("clip",))
    _emit(out, "clip", clips, bare=clip_bare)

    loras = []
    for _, nd in _all_by_class(prompt, ("LoraLoader", "LoraLoaderModelOnly",
                                         "Power Lora Loader (rgthree)")):
        loras.extend(_lora_names(nd))
    _emit(out, "lora", loras)

    ups = [n for _, nd in _all_by_class(prompt, ("UpscaleModelLoader",)) if (n := _loader_name(nd))]
    _emit(out, "upscale_model", ups)

    cns = [n for _, nd in _all_by_class(prompt, ("ControlNetLoader", "DiffControlNetLoader"))
           if (n := _loader_name(nd))]
    _emit(out, "controlnet", cns)
    imgs = []
    for _, nd in _all_by_class(prompt, ("LoadImage", "LoadImageMask")):
        v = nd.get("inputs", {}).get("image")
        if isinstance(v, str) and v:
            imgs.append(os.path.splitext(os.path.basename(v.replace("\\", "/")))[0])
    _emit(out, "loaded_image", imgs)

    return out


def metadata_for_file(path):
    """Full per-file metadata dict as emitted by the batch loader:
    extracted fields + source_path + created/modified epochs."""
    meta = {}
    emb = read_embedded(path)
    if emb["prompt"]:
        meta.update(extract_fields(emb["prompt"]))
    try:
        created, modified = file_times(path)
        meta["created"], meta["modified"] = created, modified
    except Exception:
        pass
    meta["source_path"] = os.path.abspath(path)
    return meta


# ── wildcard resolution ───────────────────────────────────────────────────────

def _sanitize_component(s):
    s = re.sub(r"[\x00-\x1f\x7f]", "", str(s))
    s = re.sub(r'[\\/:*?"<>|]', "_", s)
    return s.strip(" .")


def _fmt_date(fmt, dt):
    fmt = fmt or "YYYY-MM-DD"
    out = fmt.replace("YYYY", f"{dt.year:04d}")
    out = out.replace("YYY", f"{dt.year % 1000:03d}")
    out = out.replace("YY", f"{dt.year % 100:02d}")
    out = out.replace("MM", f"{dt.month:02d}")
    out = out.replace("DD", f"{dt.day:02d}")
    return out


def _fmt_time(spec, dt):
    mode, fmt = "24", "HH-MM-SS"
    if spec:
        head, _, rest = spec.partition(":")
        if head in ("12", "24"):
            mode = head
            if rest:
                fmt = rest
        else:
            fmt = spec
    h = dt.hour
    suffix = ""
    if mode == "12":
        suffix = "-AM" if h < 12 else "-PM"
        h = h % 12 or 12
    out = fmt.replace("HH", f"{h:02d}")
    out = out.replace("MM", f"{dt.minute:02d}")
    out = out.replace("SS", f"{dt.second:02d}")
    return out + suffix


def resolve(pattern, meta=None, when=None):
    """Substitute metadata + date/time tokens in `pattern`. `meta` is a field
    dict (extract_fields / metadata_for_file / merged). `when` is the datetime
    used by {date}/{time}; defaults to meta["created"] if present, else now.
    Unknown names in METADATA_FIELDS → "unknown-<name>-"; other {tokens} are
    left for downstream passes (index tokens etc.)."""
    meta = meta or {}
    if when is None:
        ts = meta.get("created")
        try:
            when = datetime.fromtimestamp(float(ts)) if ts else datetime.now()
        except Exception:
            when = datetime.now()

    def _sub(m):
        name, arg = m.group(1), m.group(2)
        if name == "date":
            return _sanitize_component(_fmt_date(arg, when))
        if name == "time":
            return _sanitize_component(_fmt_time(arg, when))
        base = re.sub(r"\d+$", "", name)
        if base in METADATA_FIELDS:
            v = meta.get(name)
            if v is None or v == "":
                return f"unknown-{name}-"
            return _sanitize_component(v)
        return m.group(0)

    return _TOKEN_RX.sub(_sub, pattern or "")


def resolve_folder(pattern, meta=None, when=None):
    """Resolve wildcards inside a folder pattern. Literal / or \\ split into
    subfolders (joined with os.sep); wildcards themselves can never create
    separators. Returns "" for an empty pattern."""
    if not (pattern or "").strip():
        return ""
    parts = re.split(r"[\\/]+", pattern.strip())
    resolved = []
    for p in parts:
        if not p:
            continue
        # keep drive letters ("C:") and absolute-root intent intact on the
        # first component; sanitize only resolved wildcard output per token
        resolved.append(resolve(p, meta, when))
    # preserve leading root for absolute posix paths
    lead = os.sep if pattern.strip().startswith(("/", "\\")) else ""
    return lead + os.sep.join(x for x in resolved if x)
