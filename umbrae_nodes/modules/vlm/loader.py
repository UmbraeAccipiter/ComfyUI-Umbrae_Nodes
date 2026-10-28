"""
loader.py — umbrae_nodes v0.9.1 (modules/vlm)
Load a Hugging Face vision-language (or text-only) model so that ComfyUI's own
model management owns its VRAM, exactly like a diffusion model.

Why this exists: third-party caption nodes load straight onto the GPU through
transformers, outside ComfyUI's bookkeeping. ComfyUI then cannot evict them when
a diffusion model needs the room, and they cannot evict a diffusion model
either. Here the HF model is wrapped in a ModelPatcher: it lives on the offload
device (RAM) between uses, is moved to the GPU on demand with
load_models_gpu(), and is pushed back out by ComfyUI when anything else needs
the memory.

Weights options:
  auto (as stored)         respect the checkpoint (bf16, or a pre-quantized
                           compressed-tensors / GPTQ / AWQ checkpoint)
  bf16 / fp16              cast a float checkpoint
  fp8_e4m3fn / int8        load bf16, quantize the language model's Linear
  (on the fly)             layers per output channel, upcast at compute time
                           (ComfyUI-style weight-only quant; see quant.py)

Model discovery: by default, folders under ComfyUI/models/LLM (and models/llm)
that contain a config.json, scanned three levels deep. An `external_root` can
point anywhere else instead: either straight at one model folder (the one with
config.json in it) or at a folder holding several model folders (scanned the
same way). The node's dropdown is refreshed per-node by web/umbrae_vlm.js via
the /umbrae/vlm/scan route. Nothing is ever downloaded.
"""

import os
import re
import time
import logging

import torch
import torch.nn as nn

import folder_paths
import comfy.model_management as mm
import comfy.model_patcher

from .quant import convert_linears, QuantLinear, MODES as QUANT_MODES

log = logging.getLogger("umbrae.vlm")

GB = 1024 ** 3

WEIGHT_MODES = [
    "auto (as stored)",
    "bf16",
    "fp16",
    "fp8_e4m3fn (on the fly)",
    "int8 (on the fly)",
]

ATTENTION_MODES = ["sdpa", "eager"]

MODEL_FOLDER_NAMES = ("LLM", "llm")
SCAN_DEPTH = 3


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------
def _model_roots():
    roots = []
    for name in MODEL_FOLDER_NAMES:
        try:
            for p in folder_paths.get_folder_paths(name):
                if os.path.isdir(p) and p not in roots:
                    roots.append(p)
        except Exception:
            pass
        p = os.path.join(folder_paths.models_dir, name)
        if os.path.isdir(p) and p not in roots:
            roots.append(p)
    return roots


def _is_model_dir(path):
    return os.path.isfile(os.path.join(path, "config.json"))


def _clean_root(root):
    return (root or "").strip().strip('"').strip("'")


def list_model_dirs(roots=None):
    """Relative folder names (forward slashes) of every HF model folder found."""
    found = []
    for root in (roots if roots is not None else _model_roots()):
        if not os.path.isdir(root):
            continue
        root_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, subdirs, filenames in os.walk(root, followlinks=True):
            depth = dirpath.rstrip(os.sep).count(os.sep) - root_depth
            subdirs[:] = [d for d in subdirs if not d.startswith(".")]
            if "config.json" in filenames:
                rel = os.path.relpath(dirpath, root).replace(os.sep, "/")
                if rel not in found:
                    found.append(rel)
                subdirs[:] = []           # a model folder; don't descend into it
                continue
            if depth >= SCAN_DEPTH:
                subdirs[:] = []
    return sorted(found, key=str.lower)


ROOT_IS_MODEL = "."   # dropdown entry meaning "external_root itself is the model folder"


def effective_model_list(root=""):
    """What the dropdown should show for a given external_root.
    Returns (names, source, status) with source in: 'default', 'root_is_model',
    'custom', 'custom_empty', 'missing'."""
    root = _clean_root(root)
    if not root:
        names = list_model_dirs()
        return names, "default", f"models/LLM: {len(names)} model folder(s)"
    if not os.path.isdir(root):
        names = list_model_dirs()
        return names, "missing", "external_root does not exist - showing models/LLM"
    if _is_model_dir(root):
        return [ROOT_IS_MODEL], "root_is_model", f"external_root is a model folder: {os.path.basename(root.rstrip(os.sep + '/'))}"
    names = list_model_dirs([root])
    if names:
        return names, "custom", f"external_root: {len(names)} model folder(s)"
    names = list_model_dirs()
    return names, "custom_empty", "no model folders under external_root - showing models/LLM"


def resolve_model_dir(name, root=""):
    """Absolute path of the model folder for (dropdown value, external_root).
    Root set: the root itself if it is a model folder, else root/name.
    Otherwise (or on a miss) the normal models/LLM folders."""
    root = _clean_root(root)
    name = (name or "").strip()
    if root and os.path.isdir(root):
        if _is_model_dir(root):
            return os.path.abspath(root)
        if name and name != ROOT_IS_MODEL:
            base = os.path.abspath(root)
            cand = os.path.abspath(os.path.join(base, name.replace("/", os.sep)))
            inside = os.path.commonpath([base, cand]) == base if os.path.splitdrive(base)[0] == os.path.splitdrive(cand)[0] else False
            if inside and _is_model_dir(cand):
                return cand
    for r in _model_roots():
        cand = os.path.join(r, name.replace("/", os.sep))
        if name and name != ROOT_IS_MODEL and _is_model_dir(cand):
            return os.path.abspath(cand)
    where = f"under external_root {root!r}" if root else "under models/LLM"
    raise FileNotFoundError(f"model folder not found {where}: {name!r} (a model folder must contain config.json)")


def model_dir_signature(path):
    """Cheap change signature for IS_CHANGED: config + weight file names, sizes, mtimes."""
    parts = []
    try:
        for fn in sorted(os.listdir(path)):
            if fn.endswith((".json", ".safetensors", ".bin")):
                st = os.stat(os.path.join(path, fn))
                parts.append(f"{fn}:{st.st_size}:{int(st.st_mtime)}")
    except OSError:
        pass
    return "|".join(parts)


def register_scan_route():
    """GET /umbrae/vlm/scan?root=<external_root> -> {"models": [...], "source": ..., "status": ...}"""
    try:
        from server import PromptServer
        from aiohttp import web
    except Exception as e:
        log.warning("[umbrae.vlm] could not import server/aiohttp (%s); scan route disabled.", e)
        return
    if getattr(PromptServer.instance, "_umbrae_vlm_scan_route", False):
        return

    @PromptServer.instance.routes.get("/umbrae/vlm/scan")
    async def _scan(request):
        root = request.rel_url.query.get("root", "")
        names, source, status = effective_model_list(root)
        return web.json_response({"models": names, "source": source, "status": status})

    PromptServer.instance._umbrae_vlm_scan_route = True
    log.info("[umbrae.vlm] scan route registered.")


# ---------------------------------------------------------------------------
# compressed-tensors ignore-list portability (see JoyCaption investigation):
# checkpoints list unquantized modules by path, and those paths changed between
# transformers versions ('vision_tower.vision_model...' -> 'model.vision_tower...',
# 'language_model.lm_head' -> 'lm_head'). Add regexes covering the same families
# so the vision tower / projector / lm_head stay float on any version.
# ---------------------------------------------------------------------------
_IGNORE_FAMILIES = {
    "vision_tower": "re:.*vision_tower.*",
    "visual": "re:.*visual.*",
    "multi_modal_projector": "re:.*multi_modal_projector.*",
    "lm_head": "re:.*lm_head",
}


def widen_quant_ignore(ignore):
    ignore = list(ignore or [])
    extra = [pat for key, pat in _IGNORE_FAMILIES.items()
             if any(key in entry for entry in ignore) and pat not in ignore]
    return ignore + extra


def _ct_config_accepts(name):
    """Does the installed transformers' CompressedTensorsConfig take this keyword?"""
    try:
        import inspect
        from transformers import CompressedTensorsConfig
        return name in inspect.signature(CompressedTensorsConfig.__init__).parameters
    except Exception:
        return False


def is_fp8_compressed(qc):
    """compressed-tensors config dict with at least one 8-bit float weight group."""
    if not isinstance(qc, dict) or qc.get("quant_method") != "compressed-tensors":
        return False
    for group in (qc.get("config_groups") or {}).values():
        w = (group or {}).get("weights") or {}
        if w.get("type") == "float" and int(w.get("num_bits", 0)) == 8:
            return True
    return False


def load_config(path, load_device=None):
    from transformers import AutoConfig
    cfg = AutoConfig.from_pretrained(path)
    qc = getattr(cfg, "quantization_config", None)
    if isinstance(qc, dict) and qc.get("quant_method") == "compressed-tensors":
        qc["ignore"] = widen_quant_ignore(qc.get("ignore"))
        # Current transformers leaves compressed weights compressed at load and then
        # DECOMPRESSES THEM TO bf16 ON THE FIRST FORWARD (hook from compress_model), so an
        # "FP8" checkpoint would run as a 17 GB bf16 model. Ask for the real FP8 path
        # instead: weights stay FP8 and matmuls use torch._scaled_mm (needs SM 8.9+,
        # e.g. a 4090). Both keys are only set when this transformers knows them.
        if _ct_config_accepts("dequantize"):
            qc["dequantize"] = False
        if is_fp8_compressed(qc) and _ct_config_accepts("use_optimized_inference"):
            cap_ok = True
            try:
                if load_device is not None and load_device.type == "cuda":
                    cap_ok = torch.cuda.get_device_capability(load_device) >= (8, 9)
            except Exception:
                pass
            qc["use_optimized_inference"] = bool(cap_ok)
    return cfg


def _is_compressed_quant_module(m):
    """A compressed-tensors module still holding compressed weights (weight + weight_scale)."""
    if not hasattr(m, "quantization_scheme"):
        return False
    w = getattr(m, "weight", None)
    scale = getattr(m, "weight_scale", None)
    if w is None or scale is None or not isinstance(m, nn.Module):
        return False
    return w.dtype in (torch.int8,) + ((torch.float8_e4m3fn,) if hasattr(torch, "float8_e4m3fn") else ())


@torch.no_grad()
def adopt_compressed_linears(model):
    """Turn compressed-tensors modules that still hold (fp8|int8 weight, weight_scale) into
    QuantLinear, so they run dequantize-per-forward at 1 byte/weight instead of being
    decompressed to bf16 by compressed-tensors' first-forward hook. Returns the count.
    Modules with a non-zero zero point are left alone (then nothing is adopted and the
    hook is kept, so the model still runs, just dequantized)."""
    todo = []
    for name, m in list(model.named_modules()):
        if not _is_compressed_quant_module(m):
            continue
        zp = getattr(m, "weight_zero_point", None)
        if zp is not None and torch.count_nonzero(zp).item() != 0:
            log.warning("[umbrae.vlm] %s has a non-zero zero point; leaving compressed-tensors to handle it", name)
            return 0
        todo.append((name, m))
    if not todo:
        return 0
    for name, m in todo:
        parent_name, _, child = name.rpartition(".")
        parent = model.get_submodule(parent_name) if parent_name else model
        mode = "int8" if m.weight.dtype == torch.int8 else "fp8_e4m3fn"
        scale = m.weight_scale.data
        if scale.dim() == 1:
            scale = scale.unsqueeze(-1)              # [out] -> [out, 1]
        elif scale.dim() == 0:
            scale = scale.reshape(1, 1)              # per-tensor
        bias = m.bias.data if getattr(m, "bias", None) is not None else None
        setattr(parent, child, QuantLinear(m.weight.data, scale.to(torch.float32), bias, mode))
    hook = getattr(model, "ct_decompress_hook", None)
    if hook is not None:
        try:
            hook.remove()
        except Exception:
            pass
        try:
            delattr(model, "ct_decompress_hook")
        except Exception:
            pass
    return len(todo)


def count_fp8_kernel_linears(model):
    return sum(1 for m in model.modules() if type(m).__name__ == "CompressedTensorsFP8Linear")


def is_prequantized(cfg):
    return getattr(cfg, "quantization_config", None) is not None


def has_vision(cfg):
    return getattr(cfg, "vision_config", None) is not None


# ---------------------------------------------------------------------------
# ComfyUI integration
# ---------------------------------------------------------------------------
class VLMContainer(nn.Module):
    """Thin wrapper so ModelPatcher can own the HF model.

    ModelPatcher assigns `.device` on the module it manages; HF models expose
    `device` as a read-only property, so the HF model is held as a child here."""

    def __init__(self, hf_model):
        super().__init__()
        self.hf = hf_model
        self.device = torch.device("cpu")


class UmbraeVLM:
    """What travels along the UMBRAE_VLM wire."""

    def __init__(self, patcher, processor, tokenizer, image_token, meta):
        self.patcher = patcher
        self.processor = processor
        self.tokenizer = tokenizer
        self.image_token = image_token
        self.meta = meta

    @property
    def hf(self):
        return self.patcher.model.hf

    @property
    def has_processor(self):
        return self.processor is not self.tokenizer

    @property
    def device(self):
        return next(self.hf.parameters()).device

    @property
    def compute_dtype(self):
        for p in self.hf.parameters():
            if p.dtype in (torch.bfloat16, torch.float16, torch.float32):
                return p.dtype
        return torch.bfloat16

    def ensure_loaded(self, extra_memory=1.5 * GB):
        """Bring the whole model onto the GPU, evicting other models if needed."""
        mm.load_models_gpu([self.patcher], memory_required=extra_memory, force_full_load=True)

    def offload(self):
        """Push the model back to RAM now (ComfyUI would do this lazily when VRAM is needed)."""
        for i, loaded in enumerate(list(mm.current_loaded_models)):
            if loaded.model is self.patcher:
                loaded.model_unload()
                mm.current_loaded_models.pop(i)
                break
        else:
            self.patcher.detach()
        mm.soft_empty_cache()

    def describe(self):
        m = self.meta
        return (f"{m['name']} | {m['weights']} | {'vision+text' if m['has_vision'] else 'text only'} | "
                f"{m['params'] / 1e9:.2f}B params | {m['bytes'] / GB:.2f} GB | loaded in {m['load_seconds']:.1f}s")


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def _dtype_kwarg_name():
    """transformers >= 4.56 takes `dtype=`; older versions take `torch_dtype=` and would
    silently stash an unknown `dtype` kwarg on the config and load in fp32."""
    import transformers
    try:
        major, minor = (int(x) for x in transformers.__version__.split(".")[:2])
    except ValueError:
        return "dtype"
    return "dtype" if (major, minor) >= (4, 56) else "torch_dtype"


def _from_pretrained(path, cfg, dtype, attention):
    """Try the vision-language auto classes first, then plain causal LM."""
    import transformers
    dtype_key = _dtype_kwarg_name()
    candidates = []
    if has_vision(cfg):
        for cls_name in ("AutoModelForImageTextToText", "AutoModelForVision2Seq"):
            cls = getattr(transformers, cls_name, None)
            if cls is not None:
                candidates.append(cls)
    candidates.append(transformers.AutoModelForCausalLM)

    base = {"config": cfg, "low_cpu_mem_usage": True}
    if attention:
        base["attn_implementation"] = attention

    last = None
    for cls in candidates:
        try:
            return cls.from_pretrained(path, **{dtype_key: dtype}, **base)
        except ValueError as e:             # config not supported by this auto class; try the next
            last = e
    raise last


def _processor_and_tokenizer(path):
    from transformers import AutoProcessor, AutoTokenizer
    processor = None
    try:
        processor = AutoProcessor.from_pretrained(path)
    except Exception as e:
        log.info("[umbrae.vlm] no processor for %s (%s); using tokenizer only", path, e)
    tokenizer = getattr(processor, "tokenizer", None)
    if tokenizer is None:
        tokenizer = AutoTokenizer.from_pretrained(path)
    if processor is None:
        processor = tokenizer
    return processor, tokenizer


def _image_token(processor, tokenizer):
    tok = getattr(processor, "image_token", None)
    if isinstance(tok, str) and tok:
        return tok
    for t in (getattr(tokenizer, "additional_special_tokens", None) or []):
        if "image" in t.lower():
            return t
    return None


def load_vlm(model_dir, weights, keep_vision_float=True, attention="sdpa"):
    t0 = time.time()
    name = os.path.basename(model_dir.rstrip("/\\"))
    load_device = mm.get_torch_device()
    offload_device = mm.unet_offload_device()

    phase = time.time()
    cfg = load_config(model_dir, load_device)
    quant_mode = None
    if weights.startswith("fp8_e4m3fn"):
        quant_mode = "fp8_e4m3fn"
    elif weights.startswith("int8"):
        quant_mode = "int8"

    if quant_mode and is_prequantized(cfg):
        qc = cfg.quantization_config
        method = qc.get("quant_method") if isinstance(qc, dict) else getattr(qc, "quant_method", qc)
        raise ValueError(f"{name} is already quantized ({method}); pick 'auto (as stored)' for this checkpoint")

    if weights.startswith("auto"):
        dtype = "auto"
    elif weights == "fp16":
        dtype = torch.float16
    else:                                    # bf16, or the on-the-fly modes (quantize from bf16)
        dtype = torch.bfloat16

    log.info("[umbrae.vlm] loading %s (%s) to %s", name, weights, offload_device)
    hf = _from_pretrained(model_dir, cfg, dtype, attention)
    log.info("[umbrae.vlm] from_pretrained: %.1fs", time.time() - phase); phase = time.time()
    hf.eval()
    hf.requires_grad_(False)
    if offload_device.type != "cpu":
        hf.to(offload_device)

    if is_prequantized(cfg) and getattr(cfg, "quantization_config", {}).get("quant_method") == "compressed-tensors":
        kernels = count_fp8_kernel_linears(hf)
        adopted = adopt_compressed_linears(hf)
        if kernels:
            log.info("[umbrae.vlm] %s: %d FP8 Linear layers on torch._scaled_mm kernels (weights stay FP8)", name, kernels)
        if adopted:
            log.info("[umbrae.vlm] %s: adopted %d compressed layers into QuantLinear (no bf16 decompress)", name, adopted)
        if not kernels and not adopted and not quant_mode:
            # transformers dequantized at load (older versions / dequantize=True): take the
            # footprint back down with the same on-the-fly path a bf16 checkpoint would use.
            log.info("[umbrae.vlm] %s: checkpoint was dequantized to %s at load; re-quantizing on the fly", name, dtype)
            quant_mode = "fp8_e4m3fn" if is_fp8_compressed(cfg.quantization_config) else "int8"
        log.info("[umbrae.vlm] compressed-tensors handling: %.1fs", time.time() - phase); phase = time.time()

    if quant_mode:
        work = load_device if load_device.type == "cuda" else offload_device
        if work.type == "cuda":
            mm.free_memory(1 * GB, work)
        replaced, kept, before, after = convert_linears(
            hf, quant_mode, keep_vision_float=keep_vision_float,
            work_device=work, target_device=offload_device)
        if work.type == "cuda":
            mm.soft_empty_cache()
        log.info("[umbrae.vlm] %s: %d Linear layers -> %s (%d kept float), %.2f GB -> %.2f GB",
                 name, replaced, quant_mode, kept, before / GB, after / GB)

    processor, tokenizer = _processor_and_tokenizer(model_dir)
    image_token = _image_token(processor, tokenizer) if has_vision(cfg) else None
    log.info("[umbrae.vlm] processor/tokenizer: %.1fs", time.time() - phase); phase = time.time()

    container = VLMContainer(hf)
    patcher = comfy.model_patcher.ModelPatcher(container, load_device=load_device, offload_device=offload_device)

    meta = {
        "name": name,
        "path": model_dir,
        "weights": weights,
        "has_vision": has_vision(cfg),
        "params": sum(p.numel() for p in hf.parameters()),
        "bytes": patcher.model_size(),
        "load_seconds": time.time() - t0,
    }
    vlm = UmbraeVLM(patcher, processor, tokenizer, image_token, meta)
    log.info("[umbrae.vlm] ready: %s", vlm.describe())
    return vlm
