# save_training_pair.py — UNP
#
# Saves a single image + its LLM caption as a matched file pair.
# The two output files always share the same stem name, differing only
# in extension: {stem}.png (or .jpg/.webp) and {stem}.txt
#
# Folder resolution
# ─────────────────
#   • Empty          → creates  ComfyUI/output/training_pairs/
#   • Plain name     → creates  ComfyUI/output/{name}/          e.g. "my_dataset"
#   • Relative path  → resolves inside ComfyUI/output/          e.g. "sets/batch1"
#   • Absolute path  → used as-is                               e.g. "D:/data/captions"
#
# Loop notes
# ──────────
# Connect next_index to a ForEachLoopOpen (Impact-Pack) or a repeat
# controller to automate cycling through a batch.  For small sets,
# advance the batch loader preview manually and re-queue each image.

import os
import re

import numpy as np
from PIL import Image


class SaveTrainingPair:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),

                # LLM-generated caption — must be wired, not typed manually
                "caption": ("STRING", {
                    "multiline":  True,
                    "forceInput": True,
                    "tooltip":    "The text to write into the .txt file. "
                                  "Wire this from your LLM/vision node.",
                }),

                # From SelectImageAndName or LoadImagesUniformBatch.filenames
                "source_filename": ("STRING", {
                    "forceInput": True,
                    "tooltip":    "The original image filename (e.g. 'photo_001.jpg'). "
                                  "The stem of this name is used for both saved files. "
                                  "Wire from SelectImageAndName or the batch loader.",
                }),

                # Where to save — see folder resolution rules above
                "output_folder": ("STRING", {
                    "default": "training_pairs",
                    "multiline": False,
                    "tooltip":   "Where to save the files.\n"
                                 "• Plain name  →  created inside ComfyUI/output/  (e.g. 'my_dataset')\n"
                                 "• Relative    →  created inside ComfyUI/output/  (e.g. 'sets/batch1')\n"
                                 "• Absolute    →  used exactly as typed            (e.g. 'D:/data/')\n"
                                 "The folder is created automatically if it doesn't exist.",
                }),
            },
            "optional": {
                "format": (["png", "jpg", "webp"], {
                    "tooltip": "File format for the saved image.",
                }),
                "prefix": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip":   "Text added before the filename stem.\n"
                                 "Example: prefix='train_'  +  source 'photo001.jpg'\n"
                                 "       → saves as 'train_photo001.png'",
                }),
                "suffix": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip":   "Text added after the filename stem (before the extension).\n"
                                 "Example: suffix='_v2'  +  source 'photo001.jpg'\n"
                                 "       → saves as 'photo001_v2.png'",
                }),
                "overwrite": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "If False, appends _001, _002 … to avoid overwriting existing files.",
                }),

            },
        }

    RETURN_TYPES  = ("STRING", "STRING", "STRING", "INT")
    RETURN_NAMES  = ("image_path", "txt_path", "stem", "next_index")
    FUNCTION      = "save_pair"
    CATEGORY      = "umbrae/files"
    OUTPUT_NODE   = True   # always executes even if outputs aren't wired

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _sanitize(s):
        """Strip control chars and characters that are invalid in Windows filenames."""
        s = re.sub(r"[\x00-\x1f\x7f]", "", str(s))
        s = re.sub(r'[\\/:*?"<>|]', "_", s)
        return s.strip(" .")

    @staticmethod
    def _comfyui_output_dir():
        script_dir   = os.path.dirname(os.path.abspath(__file__))
        comfyui_root = os.path.abspath(os.path.join(script_dir, "..", ".."))
        return os.path.join(comfyui_root, "output")

    @staticmethod
    def _tensor_to_pil(tensor):
        arr = tensor[0]
        if hasattr(arr, "detach"):
            arr = arr.detach().cpu()
        arr = np.clip(np.asarray(arr, dtype=np.float32), 0.0, 1.0)
        return Image.fromarray((arr * 255).round().astype(np.uint8), mode="RGB")

    # ── Main execution ────────────────────────────────────────────────────────

    def save_pair(
        self,
        image,
        caption,
        source_filename,
        output_folder,
        format="png",
        prefix="",
        suffix="",
        overwrite=True,
    ):
        # Guard against stale widget state sending an invalid format value
        if format not in ("png", "jpg", "webp"):
            format = "png"

        # ── Resolve output folder ─────────────────────────────────────────────
        folder = (output_folder or "training_pairs").strip()
        if not os.path.isabs(folder):
            # Relative names/paths live inside ComfyUI/output/
            folder = os.path.join(self._comfyui_output_dir(), folder)
        folder = os.path.abspath(folder)
        os.makedirs(folder, exist_ok=True)

        # ── Build stem from source filename ───────────────────────────────────
        # filenames may be a newline-separated list (batch mode).
        # Use an instance counter to pick the correct filename per batch call.
        all_fnames = [f.strip() for f in (source_filename or "").strip().split("\n") if f.strip()]
        if not all_fnames:
            all_fnames = ["image"]
        if len(all_fnames) > 1:
            if not hasattr(self, "_batch_pos") or self._batch_pos >= len(all_fnames):
                self._batch_pos = 0
            fname_for_stem = all_fnames[self._batch_pos]
            self._batch_pos += 1
        else:
            fname_for_stem = all_fnames[0]
            self._batch_pos = 0
        base = os.path.splitext(os.path.basename(fname_for_stem))[0]
        stem = self._sanitize(f"{prefix}{base}{suffix}") or "image"

        # ── Resolve final filenames (handle overwrite=False) ──────────────────
        ext = {"png": ".png", "jpg": ".jpg", "webp": ".webp"}.get(format, ".png")

        def unique(s, e):
            p = os.path.join(folder, s + e)
            if overwrite or not os.path.exists(p):
                return p, s
            i = 1
            while True:
                ns = f"{s}_{i:03d}"
                p  = os.path.join(folder, ns + e)
                if not os.path.exists(p):
                    return p, ns
                i += 1

        img_path, final_stem = unique(stem, ext)
        txt_path             = os.path.join(folder, final_stem + ".txt")

        # ── Save image ────────────────────────────────────────────────────────
        pil = self._tensor_to_pil(image)
        kw  = {}
        if ext == ".jpg":  kw = {"quality": 95, "subsampling": 0}
        if ext == ".webp": kw = {"quality": 95}
        pil.save(img_path, **kw)

        # ── Save caption ──────────────────────────────────────────────────────
        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write(caption.strip())

        print(f"[SaveTrainingPair] ✓ {img_path}")
        print(f"[SaveTrainingPair] ✓ {txt_path}")

        # Pass batch progress back to JS via ui dict.
        # The JS onExecuted handler uses this to advance the iterator and
        # queue the next run — AFTER both files are confirmed saved.
        return {"ui": {"saved": [True]}, "result": (img_path, txt_path, final_stem, 1)}


NODE_CLASS_MAPPINGS        = {"SaveTrainingPair": SaveTrainingPair}
NODE_DISPLAY_NAME_MAPPINGS = {"SaveTrainingPair": "Save Training Pair [umbrae]"}
