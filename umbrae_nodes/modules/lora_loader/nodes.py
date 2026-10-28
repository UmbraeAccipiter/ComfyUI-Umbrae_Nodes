# umbrae_nodes/modules/lora_loader/nodes.py — umbrae_nodes v0.9.3
#
# "lora loader [umbrae]": stack many LoRAs in one node. The rows (file, on/off,
# strengths, picked trigger words) live in the hidden `state` widget as JSON;
# the frontend (web/lora_loader/) owns it. Python applies every switched-on row
# to MODEL (and CLIP) in order and joins the picked words into `triggers`.
import os

try:
    import folder_paths
    import comfy.sd
    import comfy.utils
except ImportError:  # dev server outside ComfyUI: the class registers, never runs
    folder_paths = comfy = None

from . import helpers as H


class UmbraeLoraLoader:
    DESCRIPTION = (
        "Stack as many LoRAs as you want in one node, each with an on/off switch and "
        "a strength (model and clip can be split in the settings). The name box opens "
        "a picker with three tabs: your local files, a Civitai search and a Hugging "
        "Face search; a found LoRA can be downloaded straight into models/loras.\n\n"
        "The i on a row opens the info panel: the full Civitai gallery, description, "
        "base model, trigger words (tick the ones you want, or type your own) and a "
        "preview picture. Ticked words from switched-on rows come out of the "
        "triggers output as plain text for your prompt."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL", {"tooltip": "The diffusion model every switched-on LoRA is applied to."}),
                "state": ("STRING", {"default": "{}", "multiline": False,
                                     "tooltip": "Managed by the node's own panel; nothing to edit here."}),
            },
            "optional": {
                "clip": ("CLIP", {"tooltip": "Optional CLIP. Connect it so LoRAs can also tune how your trigger words are read."}),
            },
        }

    RETURN_TYPES = ("MODEL", "CLIP", "STRING")
    RETURN_NAMES = ("MODEL", "CLIP", "triggers")
    OUTPUT_TOOLTIPS = (
        "The model with every switched-on LoRA applied, in row order.",
        "The CLIP with every switched-on LoRA applied (unchanged if none was connected).",
        "The ticked trigger words of the switched-on rows, joined with the separator from the settings.",
    )
    FUNCTION = "apply"
    CATEGORY = "umbrae/loaders"

    def __init__(self):
        self._cache = {}      # path -> (lora, metadata)
        self._last_path = None

    def _get_lora(self, path):
        cached = self._cache.get(path)
        if cached is not None:
            return cached
        try:
            lora, meta = comfy.utils.load_torch_file(path, safe_load=True, return_metadata=True)
        except TypeError:
            lora, meta = comfy.utils.load_torch_file(path, safe_load=True), None
        self._cache[path] = (lora, meta)
        return (lora, meta)

    def apply(self, model, state="{}", clip=None):
        st = H.parse_state(state)
        cache_mode = st["cacheMode"]
        resolved, used, applied = [], set(), 0
        last_this_run = None
        for row in st["loras"]:
            if not row["on"]:
                continue
            try:
                path = folder_paths.get_full_path("loras", row["name"])
            except Exception:
                path = None
            if not path or not os.path.isfile(path):
                print("[lora loader umbrae] skipped (not found): {}".format(row["name"]))
                continue
            sm = row["sm"]
            sc = row["sc"] if clip is not None else 0.0
            if sm == 0 and sc == 0:
                used.add(path)
                resolved.append(row)
                continue
            try:
                lora, meta = self._get_lora(path)
                try:
                    model, clip = comfy.sd.load_lora_for_models(model, clip, lora, sm, sc, lora_metadata=meta)
                except TypeError:
                    model, clip = comfy.sd.load_lora_for_models(model, clip, lora, sm, sc)
                used.add(path)
                applied += 1
                resolved.append(row)
                if cache_mode != "all":
                    if last_this_run is not None and last_this_run != path:
                        self._cache.pop(last_this_run, None)
                    last_this_run = path
            except Exception as exc:
                print("[lora loader umbrae] failed to apply {}: {}".format(row["name"], exc))

        triggers = H.collect_triggers(resolved, st["sep"])

        if cache_mode == "none":
            self._cache.clear()
            self._last_path = None
        elif cache_mode == "all":
            for p in list(self._cache):
                if p not in used:
                    del self._cache[p]
        else:
            keep = last_this_run
            if keep is None and self._last_path in used:
                keep = self._last_path
            for p in list(self._cache):
                if p != keep:
                    del self._cache[p]
            self._last_path = keep

        print("[lora loader umbrae] applied {} LoRA(s).".format(applied))
        return (model, clip, triggers)


NODE_CLASS_MAPPINGS = {"UmbraeLoraLoader": UmbraeLoraLoader}
NODE_DISPLAY_NAME_MAPPINGS = {"UmbraeLoraLoader": "lora loader [umbrae]"}
