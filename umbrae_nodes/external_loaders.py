"""
External Loaders for ComfyUI.

Functional clones of the stock model loaders. The ONLY difference from the
stock nodes is path selection: each node takes an `external_root` string that
is treated like a parallel `ComfyUI/models/` tree. The node scans only the
relevant type-named subfolder(s) under that root (recursively), and loads the
selected file with the exact same underlying comfy.* call the stock node uses.

Empty/blank root  -> falls back to the normal ComfyUI folders (stock behavior).
Root set, files   -> uses the custom folder.
Root set, empty   -> falls back to the normal ComfyUI folders.

The dropdown is populated/refreshed per-node by the companion JS via the
`/external_loaders/scan` route. Backend combo validation for the file input is
bypassed with VALIDATE_INPUTS so JS-injected custom filenames are accepted.
"""

import os
import logging

import torch

import folder_paths
import comfy.sd
import comfy.utils
import comfy.clip_vision

logger = logging.getLogger("external_loaders")

# ---------------------------------------------------------------------------
# Type -> subfolder mapping (only the folder types we expose nodes for).
# "diffusion_models" intentionally also scans the legacy "unet" subfolder.
# ---------------------------------------------------------------------------
TYPE_SUBFOLDERS = {
    "checkpoints": ["checkpoints"],
    "diffusion_models": ["diffusion_models", "unet"],
    "vae": ["vae"],
    "text_encoders": ["text_encoders"],
    "clip_vision": ["clip_vision"],
    "loras": ["loras"],
    "upscale_models": ["upscale_models"],
}


# ---------------------------------------------------------------------------
# Scanning / resolution helpers
# ---------------------------------------------------------------------------
def _extensions_for(folder_type):
    """Valid extensions for a folder type, reused from ComfyUI so we always
    match its accepted set. Falls back to the global supported set."""
    try:
        exts = folder_paths.folder_names_and_paths[folder_type][1]
        if exts:
            return {e.lower() for e in exts}
    except Exception:
        pass
    return {e.lower() for e in folder_paths.supported_pt_extensions}


def _scan_subfolder(root, subfolder, exts):
    """Recursive scan of <root>/<subfolder> for files with valid extensions.
    Returns relative paths (forward-slash), like the native file list."""
    base = os.path.join(root, subfolder)
    results = []
    if not os.path.isdir(base):
        return results
    for dirpath, subdirs, filenames in os.walk(base, followlinks=True, topdown=True):
        subdirs[:] = [d for d in subdirs if d != ".git"]
        for fn in filenames:
            if os.path.splitext(fn)[1].lower() in exts:
                rel = os.path.relpath(os.path.join(dirpath, fn), base)
                results.append(rel.replace(os.sep, "/"))
    return results


def _custom_list(root, folder_type):
    exts = _extensions_for(folder_type)
    out = set()
    for sub in TYPE_SUBFOLDERS.get(folder_type, [folder_type]):
        for rel in _scan_subfolder(root, sub, exts):
            out.add(rel)
    return sorted(out)


def effective_list(root, folder_type):
    """Returns (files, source, count_or_None).
    source is one of: 'custom', 'default', 'default_empty'."""
    root = (root or "").strip()
    if root:
        files = _custom_list(root, folder_type)
        if files:
            return files, "custom", len(files)
        return sorted(folder_paths.get_filename_list(folder_type)), "default_empty", 0
    return sorted(folder_paths.get_filename_list(folder_type)), "default", None


def resolve_path(root, folder_type, name):
    """Resolve a selected name to an absolute path.

    If root is set, try each type subfolder under it (with a basic traversal
    guard). Fall back to the normal ComfyUI folders otherwise / on miss."""
    root = (root or "").strip()
    if root and name:
        for sub in TYPE_SUBFOLDERS.get(folder_type, [folder_type]):
            base = os.path.abspath(os.path.join(root, sub))
            cand = os.path.abspath(os.path.join(base, name))
            try:
                inside = os.path.commonpath([base, cand]) == base
            except ValueError:
                inside = False  # different drive, etc.
            if inside and os.path.isfile(cand):
                return cand
    # Fallback: behave like the stock loader.
    return folder_paths.get_full_path_or_raise(folder_type, name)


def _initial_options(folder_type):
    """Server-evaluated initial combo options (stock list). The JS replaces
    these per-node once it knows the node's external_root."""
    try:
        return folder_paths.get_filename_list(folder_type)
    except Exception:
        return []


def _root_input():
    return ("STRING", {
        "default": "",
        "multiline": False,
        "tooltip": ("External models-style root folder (a parallel ComfyUI/models tree). "
                    "Blank = use the normal ComfyUI folders. Edit, then click Refresh files."),
    })


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
class ExternalCheckpointLoaderSimple:
    CATEGORY = "umbrae/loaders"

    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "external_root": _root_input(),
            "ckpt_name": (_initial_options("checkpoints"),
                          {"tooltip": "The name of the checkpoint (model) to load."}),
        }}

    RETURN_TYPES = ("MODEL", "CLIP", "VAE")
    OUTPUT_TOOLTIPS = ("The model used for denoising latents.",
                       "The CLIP model used for encoding text prompts.",
                       "The VAE model used for encoding and decoding images to and from latent space.")
    FUNCTION = "load_checkpoint"

    @classmethod
    def VALIDATE_INPUTS(s, ckpt_name):
        return True

    def load_checkpoint(self, external_root, ckpt_name):
        ckpt_path = resolve_path(external_root, "checkpoints", ckpt_name)
        out = comfy.sd.load_checkpoint_guess_config(
            ckpt_path, output_vae=True, output_clip=True,
            embedding_directory=folder_paths.get_folder_paths("embeddings"))
        return out[:3]


class ExternalUNETLoader:
    CATEGORY = "umbrae/loaders"

    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "external_root": _root_input(),
            "unet_name": (_initial_options("diffusion_models"), ),
            "weight_dtype": (["default", "fp8_e4m3fn", "fp8_e4m3fn_fast", "fp8_e5m2"], {"advanced": True}),
        }}

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "load_unet"

    @classmethod
    def VALIDATE_INPUTS(s, unet_name):
        return True

    def load_unet(self, external_root, unet_name, weight_dtype):
        model_options = {}
        if weight_dtype == "fp8_e4m3fn":
            model_options["dtype"] = torch.float8_e4m3fn
        elif weight_dtype == "fp8_e4m3fn_fast":
            model_options["dtype"] = torch.float8_e4m3fn
            model_options["fp8_optimizations"] = True
        elif weight_dtype == "fp8_e5m2":
            model_options["dtype"] = torch.float8_e5m2

        unet_path = resolve_path(external_root, "diffusion_models", unet_name)
        model = comfy.sd.load_diffusion_model(unet_path, model_options=model_options)
        return (model,)


class ExternalVAELoader:
    CATEGORY = "umbrae/loaders"

    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "external_root": _root_input(),
            "vae_name": (_initial_options("vae"), ),
        }}

    RETURN_TYPES = ("VAE",)
    FUNCTION = "load_vae"

    @classmethod
    def VALIDATE_INPUTS(s, vae_name):
        return True

    def load_vae(self, external_root, vae_name):
        # External files are loaded via the standard single-file path. The
        # stock node's taesd / pixel_space / taef2 special cases reference
        # ComfyUI's vae_approx list and synthetic state dicts, which do not
        # apply to arbitrary external files, so they are intentionally omitted.
        vae_path = resolve_path(external_root, "vae", vae_name)
        sd, metadata = comfy.utils.load_torch_file(vae_path, return_metadata=True)
        vae = comfy.sd.VAE(sd=sd, metadata=metadata)
        vae.throw_exception_if_invalid()
        if vae_path is not None:
            vae.patcher.cached_patcher_init = (comfy.sd.load_vae_patcher, (vae_path, metadata, None))
        return (vae,)


class ExternalCLIPLoader:
    CATEGORY = "umbrae/loaders"

    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "external_root": _root_input(),
            "clip_name": (_initial_options("text_encoders"), ),
            "type": (["stable_diffusion", "stable_cascade", "sd3", "stable_audio", "mochi", "ltxv",
                      "pixart", "cosmos", "lumina2", "wan", "hidream", "chroma", "ace", "omnigen2",
                      "qwen_image", "hunyuan_image", "flux2", "ovis", "longcat_image", "cogvideox",
                      "lens", "pixeldit", "ideogram4", "boogu"], ),
        }, "optional": {
            "device": (["default", "cpu"], {"advanced": True}),
        }}

    RETURN_TYPES = ("CLIP",)
    FUNCTION = "load_clip"

    DESCRIPTION = ("Recipes:\nsd: clip-l\nstable cascade: clip-g\nsd3: t5 xxl / clip-g / clip-l\n"
                   "stable audio: t5 base\nmochi: t5 xxl\ncogvideox: t5 xxl (226-token padding)\n"
                   "cosmos: old t5 xxl\nlumina2: gemma 2 2B\nwan: umt5 xxl\n"
                   "hidream: llama-3.1 (Recommend) or t5\nomnigen2: qwen vl 2.5 3B\nlens: gpt-oss-20b\n"
                   "pixeldit: gemma 2 2B elm")

    @classmethod
    def VALIDATE_INPUTS(s, clip_name):
        return True

    def load_clip(self, external_root, clip_name, type="stable_diffusion", device="default"):
        clip_type = getattr(comfy.sd.CLIPType, type.upper(), comfy.sd.CLIPType.STABLE_DIFFUSION)

        model_options = {}
        if device == "cpu":
            model_options["load_device"] = model_options["offload_device"] = torch.device("cpu")

        clip_path = resolve_path(external_root, "text_encoders", clip_name)
        clip = comfy.sd.load_clip(
            ckpt_paths=[clip_path],
            embedding_directory=folder_paths.get_folder_paths("embeddings"),
            clip_type=clip_type, model_options=model_options)
        return (clip,)


class ExternalCLIPVisionLoader:
    CATEGORY = "umbrae/loaders"

    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "external_root": _root_input(),
            "clip_name": (_initial_options("clip_vision"), ),
        }}

    RETURN_TYPES = ("CLIP_VISION",)
    FUNCTION = "load_clip"

    @classmethod
    def VALIDATE_INPUTS(s, clip_name):
        return True

    def load_clip(self, external_root, clip_name):
        clip_path = resolve_path(external_root, "clip_vision", clip_name)
        clip_vision = comfy.clip_vision.load(clip_path)
        if clip_vision is None:
            raise RuntimeError("ERROR: clip vision file is invalid and does not contain a valid vision model.")
        return (clip_vision,)


class ExternalLoraLoader:
    CATEGORY = "umbrae/loaders"

    def __init__(self):
        self.loaded_lora = None

    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "model": ("MODEL", {"tooltip": "The diffusion model the LoRA will be applied to."}),
            "clip": ("CLIP", {"tooltip": "The CLIP model the LoRA will be applied to."}),
            "external_root": _root_input(),
            "lora_name": (_initial_options("loras"), {"tooltip": "The name of the LoRA."}),
            "strength_model": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01,
                                         "tooltip": "How strongly to modify the diffusion model. This value can be negative."}),
            "strength_clip": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01,
                                        "tooltip": "How strongly to modify the CLIP model. This value can be negative."}),
        }}

    RETURN_TYPES = ("MODEL", "CLIP")
    OUTPUT_TOOLTIPS = ("The modified diffusion model.", "The modified CLIP model.")
    FUNCTION = "load_lora"

    @classmethod
    def VALIDATE_INPUTS(s, lora_name):
        return True

    def load_lora(self, model, clip, external_root, lora_name, strength_model, strength_clip):
        if strength_model == 0 and strength_clip == 0:
            return (model, clip)

        lora_path = resolve_path(external_root, "loras", lora_name)
        lora = None
        lora_metadata = None
        if self.loaded_lora is not None:
            if self.loaded_lora[0] == lora_path:
                lora = self.loaded_lora[1]
                lora_metadata = self.loaded_lora[2] if len(self.loaded_lora) > 2 else None
            else:
                self.loaded_lora = None

        if lora is None:
            lora, lora_metadata = comfy.utils.load_torch_file(lora_path, safe_load=True, return_metadata=True)
            self.loaded_lora = (lora_path, lora, lora_metadata)

        model_lora, clip_lora = comfy.sd.load_lora_for_models(
            model, clip, lora, strength_model, strength_clip, lora_metadata=lora_metadata)
        return (model_lora, clip_lora)


class ExternalLoraLoaderModelOnly(ExternalLoraLoader):
    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "model": ("MODEL",),
            "external_root": _root_input(),
            "lora_name": (_initial_options("loras"), ),
            "strength_model": ("FLOAT", {"default": 1.0, "min": -100.0, "max": 100.0, "step": 0.01}),
        }}

    RETURN_TYPES = ("MODEL",)
    FUNCTION = "load_lora_model_only"

    @classmethod
    def VALIDATE_INPUTS(s, lora_name):
        return True

    def load_lora_model_only(self, model, external_root, lora_name, strength_model):
        return (self.load_lora(model, None, external_root, lora_name, strength_model, 0)[0],)


# Upscale loader uses spandrel (same as the stock comfy_extras node). Import is
# guarded so a missing spandrel does not break the rest of the pack.
try:
    from spandrel import ModelLoader, ImageModelDescriptor
    try:
        from spandrel_extra_arches import EXTRA_REGISTRY
        from spandrel import MAIN_REGISTRY
        MAIN_REGISTRY.add(*EXTRA_REGISTRY)
        logger.info("external_loaders: spandrel_extra_arches registered.")
    except Exception:
        pass
    _SPANDREL_OK = True
except Exception:
    _SPANDREL_OK = False


class ExternalUpscaleModelLoader:
    CATEGORY = "umbrae/loaders"

    @classmethod
    def INPUT_TYPES(s):
        return {"required": {
            "external_root": _root_input(),
            "model_name": (_initial_options("upscale_models"), ),
        }}

    RETURN_TYPES = ("UPSCALE_MODEL",)
    FUNCTION = "load_model"

    @classmethod
    def VALIDATE_INPUTS(s, model_name):
        return True

    def load_model(self, external_root, model_name):
        if not _SPANDREL_OK:
            raise RuntimeError("spandrel is not available; cannot load upscale models.")
        model_path = resolve_path(external_root, "upscale_models", model_name)
        sd = comfy.utils.load_torch_file(model_path, safe_load=True)
        if "module.layers.0.residual_group.blocks.0.norm1.weight" in sd:
            sd = comfy.utils.state_dict_prefix_replace(sd, {"module.": ""})
        out = ModelLoader().load_from_state_dict(sd).eval()
        if not isinstance(out, ImageModelDescriptor):
            raise Exception("Upscale model must be a single-image model.")
        return (out,)


# ---------------------------------------------------------------------------
# Server route used by the JS to scan a node's external_root on demand.
# ---------------------------------------------------------------------------
def _register_route():
    try:
        from server import PromptServer
        from aiohttp import web
    except Exception as e:
        logger.warning("external_loaders: could not import server/aiohttp (%s); scan route disabled.", e)
        return

    if getattr(PromptServer.instance, "_external_loaders_route", False):
        return

    @PromptServer.instance.routes.get("/external_loaders/scan")
    async def _scan(request):
        root = request.rel_url.query.get("root", "")
        folder_type = request.rel_url.query.get("type", "")
        if folder_type not in TYPE_SUBFOLDERS:
            return web.json_response(
                {"files": [], "source": "error", "status": "unknown type"}, status=400)
        files, source, count = effective_list(root, folder_type)
        label = {
            "custom": "Custom: %d file(s)" % (count or 0),
            "default": "Default folders",
            "default_empty": "Custom path empty \u2014 using default",
        }.get(source, source)
        return web.json_response({"files": files, "source": source, "status": label})

    PromptServer.instance._external_loaders_route = True
    logger.info("external_loaders: scan route registered.")


_register_route()


# ---------------------------------------------------------------------------
# Mappings
# ---------------------------------------------------------------------------
NODE_CLASS_MAPPINGS = {
    "ExternalCheckpointLoaderSimple": ExternalCheckpointLoaderSimple,
    "ExternalUNETLoader": ExternalUNETLoader,
    "ExternalVAELoader": ExternalVAELoader,
    "ExternalCLIPLoader": ExternalCLIPLoader,
    "ExternalCLIPVisionLoader": ExternalCLIPVisionLoader,
    "ExternalLoraLoader": ExternalLoraLoader,
    "ExternalLoraLoaderModelOnly": ExternalLoraLoaderModelOnly,
    "ExternalUpscaleModelLoader": ExternalUpscaleModelLoader,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ExternalCheckpointLoaderSimple": "load checkpoint external [umbrae]",
    "ExternalUNETLoader": "load diffusion model external [umbrae]",
    "ExternalVAELoader": "load vae external [umbrae]",
    "ExternalCLIPLoader": "load clip external [umbrae]",
    "ExternalCLIPVisionLoader": "load clip vision external [umbrae]",
    "ExternalLoraLoader": "load lora external [umbrae]",
    "ExternalLoraLoaderModelOnly": "load lora model only external [umbrae]",
    "ExternalUpscaleModelLoader": "load upscale model external [umbrae]",
}
