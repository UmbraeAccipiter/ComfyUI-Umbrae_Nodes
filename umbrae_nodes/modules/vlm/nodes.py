"""
nodes.py — umbrae_nodes v0.9.1 (modules/vlm)
Four nodes (JoyCaption-advanced shaped):
  load vlm / llm (hf) [umbrae]          models/LLM folder -> UMBRAE_VLM (ComfyUI-managed)
  vlm generate [umbrae]                 UMBRAE_VLM + prompt (+ image batch) + LLM controls -> text;
                                        system prompt has a working default, override field is optional
  caption prompt (joycaption) [umbrae]  style / length / additions (+ optional extras) -> prompt string
  caption extras (joycaption) [umbrae]  the 27 JoyCaption extra-option toggles + character name
"""

import hashlib
import math

import torch
from PIL import Image

from .loader import (WEIGHT_MODES, ATTENTION_MODES, list_model_dirs, resolve_model_dir,
                     model_dir_signature, load_vlm, register_scan_route)
from .generate import generate_text
from .prompts import (STYLES, LENGTHS, EXTRA_OPTIONS, JOYCAPTION_SYSTEM_PROMPT,
                      build_caption_prompt)

VLM_TYPE = "UMBRAE_VLM"
EXTRAS_TYPE = "UMBRAE_CAPTION_EXTRAS"
NO_MODELS = "(no model folders found under models/LLM)"


def _model_choices():
    dirs = list_model_dirs()
    return dirs if dirs else [NO_MODELS]


def image_facts(width, height):
    """One line of ground truth the VLM cannot see after resizing: size, orientation, ratio."""
    g = math.gcd(width, height) or 1
    w, h = width // g, height // g
    if max(w, h) > 32:                      # odd sizes give ugly ratios (e.g. 1440:901); use the decimal only
        ratio = f"{width / height:.2f}:1"
    else:
        ratio = f"{w}:{h}"
    orientation = "square" if width == height else ("landscape" if width > height else "portrait")
    return f"Image facts: {width}x{height} pixels, {orientation}, aspect ratio {ratio} ({width / height:.2f})."


def tensor_to_pil(img):
    """ComfyUI IMAGE row [H, W, C] float 0..1 -> PIL RGB."""
    arr = (img.detach().cpu().float().clamp(0, 1) * 255).round().to(torch.uint8).numpy()
    if arr.ndim == 2:
        return Image.fromarray(arr, "L").convert("RGB")
    if arr.shape[-1] == 1:
        return Image.fromarray(arr[..., 0], "L").convert("RGB")
    if arr.shape[-1] >= 4:
        return Image.fromarray(arr[..., :4], "RGBA").convert("RGB")
    return Image.fromarray(arr[..., :3], "RGB")


# ---------------------------------------------------------------------------
class UmbraeVLMLoader:
    CATEGORY = "umbrae/loaders"
    FUNCTION = "load"
    RETURN_TYPES = (VLM_TYPE, "STRING")
    RETURN_NAMES = ("vlm", "info")
    DESCRIPTION = ("Load a Hugging Face vision-language or text model. By default from models/LLM; set "
                   "external_root to a model folder anywhere on disk (or a folder of model folders) and press "
                   "Refresh models. The model is handed to ComfyUI's model management, so it shares VRAM with "
                   "diffusion models (evicted and reloaded automatically). Nothing is downloaded.")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "external_root": ("STRING", {"default": "", "multiline": False, "tooltip": (
                    "Blank = ComfyUI/models/LLM. Otherwise a path anywhere on disk: either ONE model folder "
                    "(the folder that holds config.json) or a folder containing several model folders. "
                    "Edit, then click Refresh models.")}),
                "model": (_model_choices(), {
                    "tooltip": "A Hugging Face snapshot folder (contains config.json). '.' = external_root itself is the model."}),
                "weights": (WEIGHT_MODES, {"default": WEIGHT_MODES[0], "tooltip": (
                    "auto: use the checkpoint as stored (bf16, or a pre-quantized FP8/GPTQ/AWQ checkpoint).\n"
                    "bf16 / fp16: cast a float checkpoint.\n"
                    "fp8_e4m3fn / int8 (on the fly): load bf16 and quantize the language model's Linear "
                    "layers per output channel, upcast at compute time. Roughly half the VRAM, any GPU.")}),
                "keep_vision_float": ("BOOLEAN", {"default": True, "tooltip": (
                    "On-the-fly modes only: leave the vision tower, projector and lm_head in bf16. "
                    "They are small and quality-sensitive. Off = quantize them too (lm_head and embeddings always stay float).")}),
                "attention": (ATTENTION_MODES, {"default": "sdpa", "tooltip": "Attention backend passed to transformers."}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, external_root, model, weights, keep_vision_float, attention):
        try:
            sig = model_dir_signature(resolve_model_dir(model, external_root))
        except Exception as e:
            sig = f"missing:{e}"
        return hashlib.sha1(f"{external_root}|{model}|{weights}|{keep_vision_float}|{attention}|{sig}".encode()).hexdigest()

    @classmethod
    def VALIDATE_INPUTS(cls, external_root, model):
        # The dropdown is filled per-node by the JS from external_root, so values the
        # server did not list at startup must be accepted; resolve_model_dir does the real check.
        try:
            resolve_model_dir(model, external_root)
        except FileNotFoundError as e:
            return str(e)
        return True

    def load(self, external_root, model, weights, keep_vision_float, attention):
        path = resolve_model_dir(model, external_root)
        vlm = load_vlm(path, weights, keep_vision_float=keep_vision_float, attention=attention)
        return (vlm, vlm.describe())


# ---------------------------------------------------------------------------
class UmbraeVLMGenerate:
    CATEGORY = "umbrae/text"
    FUNCTION = "run"
    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("text", "text_joined")
    OUTPUT_IS_LIST = (True, False)
    DESCRIPTION = ("Generate text from a loaded VLM/LLM. With an image batch, each image is captioned in turn. "
                   "'text' is a LIST (one string per image; a downstream node runs once per caption). "
                   "'text_joined' is the same captions glued into ONE string. With a single image both are identical.")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "vlm": (VLM_TYPE,),
                "prompt": ("STRING", {"default": "Write a detailed description for this image.", "multiline": True,
                                      "tooltip": "User prompt. Connect the caption prompt node or type anything."}),
                "system_prompt_override": ("STRING", {"default": "", "multiline": True, "tooltip": (
                    "Leave empty to use the built-in captioning system prompt:\n" + JOYCAPTION_SYSTEM_PROMPT +
                    "\nAnything typed here replaces it. A single '-' means no system prompt at all.")}),
                "max_new_tokens": ("INT", {"default": 512, "min": 1, "max": 8192}),
                "temperature": ("FLOAT", {"default": 0.6, "min": 0.0, "max": 2.0, "step": 0.05,
                                          "tooltip": "0 = greedy (deterministic regardless of seed)."}),
                "top_p": ("FLOAT", {"default": 0.9, "min": 0.0, "max": 1.0, "step": 0.01}),
                "top_k": ("INT", {"default": 0, "min": 0, "max": 500, "tooltip": "0 = off."}),
                "repetition_penalty": ("FLOAT", {"default": 1.0, "min": 0.8, "max": 2.0, "step": 0.01, "tooltip": "1.0 = off."}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff, "control_after_generate": True}),
                "after_run": (["keep on gpu", "offload to ram"], {"default": "keep on gpu", "tooltip": (
                    "keep on gpu: fastest for repeated runs; ComfyUI still evicts it when a diffusion model needs the VRAM.\n"
                    "offload to ram: free the VRAM right away, reload (from RAM, a few seconds) on the next run.")}),
                "remove_thinking": ("BOOLEAN", {"default": True, "tooltip": "Strip <think>…</think> blocks from reasoning models' output."}),
                "append_image_facts": ("BOOLEAN", {"default": False, "tooltip": (
                    "Append one line to the prompt with the image's real pixel size, orientation and aspect ratio. "
                    "Models only see a resized copy and guess these badly.")}),
            },
            "optional": {
                "image": ("IMAGE", {"tooltip": "Optional. One generation per image in the batch. Leave unconnected for text-only use."}),
                "joiner": ("STRING", {"default": "\\n\\n", "tooltip": "Separator for text_joined. \\n is a newline."}),
            },
        }

    def run(self, vlm, prompt, system_prompt_override, max_new_tokens, temperature, top_p, top_k,
            repetition_penalty, seed, after_run, remove_thinking, append_image_facts=True, image=None, joiner="\\n\\n"):
        joiner = joiner.replace("\\n", "\n").replace("\\t", "\t")
        override = system_prompt_override.strip()
        system_prompt = "" if override == "-" else (override or JOYCAPTION_SYSTEM_PROMPT)
        images = [tensor_to_pil(image[i]) for i in range(image.shape[0])] if image is not None else [None]
        results = []
        try:
            for i, pil in enumerate(images):
                user_prompt = prompt
                if pil is not None and append_image_facts:
                    user_prompt = prompt.rstrip() + "\n\n" + image_facts(*pil.size)
                results.append(generate_text(
                    vlm, system_prompt, user_prompt, pil,
                    max_new_tokens=max_new_tokens, temperature=temperature, top_p=top_p, top_k=top_k,
                    repetition_penalty=repetition_penalty, seed=seed + i, remove_thinking=remove_thinking))
        finally:
            if after_run == "offload to ram":
                vlm.offload()
        return (results, joiner.join(results))


# ---------------------------------------------------------------------------
class UmbraeCaptionExtras:
    CATEGORY = "umbrae/text"
    FUNCTION = "collect"
    RETURN_TYPES = (EXTRAS_TYPE,)
    RETURN_NAMES = ("extras",)
    DESCRIPTION = "JoyCaption extra options. Plug into caption prompt's 'extras' input."

    @classmethod
    def INPUT_TYPES(cls):
        req = {}
        for key, (_label, sentence) in EXTRA_OPTIONS.items():
            req[key] = ("BOOLEAN", {"default": False, "tooltip": sentence})
        req["character_name"] = ("STRING", {"default": "", "tooltip": "Used by refer_character_name."})
        return {"required": req}

    def collect(self, character_name="", **flags):
        chosen = [k for k in EXTRA_OPTIONS if flags.get(k)]
        return ({"keys": chosen, "character_name": character_name},)


class UmbraeCaptionPrompt:
    CATEGORY = "umbrae/text"
    FUNCTION = "build"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompt",)
    DESCRIPTION = ("JoyCaption-style caption prompt: style + length, optional extras node, plus a free-text field "
                   "for additions. Feed the output into vlm generate's prompt.")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "style": (list(STYLES.keys()), {"default": "Descriptive"}),
                "length": (LENGTHS, {"default": "any"}),
                "word_count": ("INT", {"default": 0, "min": 0, "max": 1000, "tooltip": "0 = off. When set, overrides length."}),
                "additions": ("STRING", {"default": "", "multiline": True,
                                         "tooltip": "Extra instructions appended after the selected extras, verbatim."}),
            },
            "optional": {
                "extras": (EXTRAS_TYPE, {"tooltip": "From caption extras (joycaption)."}),
            },
        }

    def build(self, style, length, word_count, additions, extras=None):
        keys = extras["keys"] if extras else []
        name = extras.get("character_name", "") if extras else ""
        prompt = build_caption_prompt(style, length=length, word_count=word_count, extra_keys=keys,
                                      custom_extra=additions, character_name=name)
        return (prompt,)


register_scan_route()

NODE_CLASS_MAPPINGS = {
    "UmbraeVLMLoader": UmbraeVLMLoader,
    "UmbraeVLMGenerate": UmbraeVLMGenerate,
    "UmbraeCaptionPrompt": UmbraeCaptionPrompt,
    "UmbraeCaptionExtras": UmbraeCaptionExtras,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "UmbraeVLMLoader": "load vlm / llm (hf) [umbrae]",
    "UmbraeVLMGenerate": "vlm generate [umbrae]",
    "UmbraeCaptionPrompt": "caption prompt (joycaption) [umbrae]",
    "UmbraeCaptionExtras": "caption extras (joycaption) [umbrae]",
}
