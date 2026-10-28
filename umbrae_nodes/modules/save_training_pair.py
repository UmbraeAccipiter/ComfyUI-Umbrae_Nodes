# save_training_pair.py — Umbrae
#
# Saves one image + its caption as a matched pair: {name}.png|jpg|webp and
# {name}.txt, always the same stem.
#
# Naming (shared scheme, see naming.py):
#   filename   template; {stem} = source filename without extension (blank
#              when source_filename is not wired), {n} = number.
#   prefix / suffix wrap the resolved filename.
#   number files + start at + digits: numbered through a batch-loader job.
#   overwrite  on: next job restarts at Start and replaces; off: continue
#              after the highest existing number, never replace.
#   With nothing wired and the default template, files are just the number:
#   0000.png / 0000.txt, 0001.png / 0001.txt …
#
# Folder: empty -> ComfyUI/output/training_pairs; relative -> under
# ComfyUI/output; absolute -> as typed.

import json
import os

import numpy as np
from PIL import Image

from . import naming

try:
    import folder_paths
except Exception:   # dev harness
    folder_paths = None


class SaveTrainingPair:

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "caption": ("STRING", {
                    "multiline": True, "forceInput": True,
                    "tooltip": "The text written to the .txt file. Wire from your captioner.",
                }),
                "output_folder": ("STRING", {
                    "default": "training_pairs", "multiline": False,
                    "tooltip": "Plain name or relative path -> inside ComfyUI/output. Absolute path -> as typed. "
                               "Created if missing.",
                }),
                "filename": ("STRING", {
                    "default": "{stem}", "multiline": False,
                    "tooltip": "Name template. {stem} = source filename without extension (blank when "
                               "source_filename is not wired). {n} places the number ({n4} = 4 digits); "
                               "without it the number is appended as _{n}. Empty result -> number only.",
                }),
                "number_files": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Give every saved file a number that counts up through a batch-loader job.",
                }),
                "start_index": ("INT", {
                    "default": 0, "min": 0, "max": 2_000_000_000,
                    "tooltip": "First number of a job.",
                }),
                "digits": ("INT", {
                    "default": 4, "min": 1, "max": 8,
                    "tooltip": "Zero padding of the number (4 -> 0007).",
                }),
                "overwrite": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "On: the next job restarts at Start and replaces the previous job's files; a "
                               "same-named file is replaced. Off: numbering continues after the highest "
                               "number already in the folder and no file is ever replaced.",
                }),
            },
            "optional": {
                "source_filename": ("STRING", {
                    "forceInput": True,
                    "tooltip": "Optional. The batch loader's filenames output; feeds {stem}.",
                }),
                "format": (["png", "jpg", "webp"], {"tooltip": "Image format."}),
                "prefix": ("STRING", {"default": "", "multiline": False,
                                      "tooltip": "Text before the resolved filename."}),
                "suffix": ("STRING", {"default": "", "multiline": False,
                                      "tooltip": "Text after the resolved filename, before the number/extension."}),
            },
            "hidden": {
                "ui_state": ("STRING", {"default": "{}"}),   # {"job_pos": loader index} from the JS
            },
        }

    RETURN_TYPES  = ("STRING", "STRING", "STRING", "INT")
    RETURN_NAMES  = ("image_path", "txt_path", "stem", "next_index")
    FUNCTION      = "save_pair"
    CATEGORY      = "umbrae/files"
    OUTPUT_NODE   = True

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    # ── helpers ───────────────────────────────────────────────────────────────
    @staticmethod
    def _output_root():
        if folder_paths is not None:
            return folder_paths.get_output_directory()
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(os.path.abspath(os.path.join(here, "..", "..", "..")), "output")

    @staticmethod
    def _tensor_to_pil(tensor):
        arr = tensor[0]
        if hasattr(arr, "detach"):
            arr = arr.detach().cpu()
        arr = np.clip(np.asarray(arr, dtype=np.float32), 0.0, 1.0)
        return Image.fromarray((arr * 255).round().astype(np.uint8), mode="RGB")

    def _source_stem(self, source_filename):
        """First non-empty line's stem. A multi-line list (old batch wiring)
        is cycled per execution, as before."""
        names = [f.strip() for f in (source_filename or "").strip().split("\n") if f.strip()]
        if not names:
            return ""
        if len(names) == 1:
            self._batch_pos = 0
            n = names[0]
        else:
            if not hasattr(self, "_batch_pos") or self._batch_pos >= len(names):
                self._batch_pos = 0
            n = names[self._batch_pos]
            self._batch_pos += 1
        return os.path.splitext(os.path.basename(n.replace("\\", "/")))[0]

    # ── main ──────────────────────────────────────────────────────────────────
    def save_pair(self, image, caption, output_folder, filename="{stem}", number_files=True,
                  start_index=0, digits=4, overwrite=False, source_filename="", format="png",
                  prefix="", suffix="", ui_state="{}"):
        if format not in ("png", "jpg", "webp"):
            format = "png"
        ext = {"png": ".png", "jpg": ".jpg", "webp": ".webp"}[format]
        try:
            job_pos = json.loads(ui_state or "{}").get("job_pos", -1)
        except Exception:
            job_pos = -1

        folder = (output_folder or "training_pairs").strip()
        if not os.path.isabs(folder):
            folder = os.path.join(self._output_root(), folder)
        folder = os.path.abspath(folder)
        os.makedirs(folder, exist_ok=True)

        template = f"{prefix or ''}{filename if filename is not None else '{stem}'}{suffix or ''}"
        tokens = {"stem": self._source_stem(source_filename)}
        digits = max(1, int(digits))

        if number_files:
            if not hasattr(self, "_counter"):
                self._counter = naming.JobCounter()
            self._counter.begin(
                naming.current_prompt_id(), job_pos, int(start_index), bool(overwrite),
                lambda: naming.highest_number(folder, template, tokens, ext, digits))
            number = self._counter.take()
            stem = naming.build_filename(template, tokens, number, digits)
            img_path = os.path.join(folder, stem + ext)
            guard = 0
            while not overwrite and os.path.exists(img_path) and guard < 1_000_000:
                number = self._counter.take()
                stem = naming.build_filename(template, tokens, number, digits)
                img_path = os.path.join(folder, stem + ext)
                guard += 1
            next_index = number + 1
        else:
            stem = naming.build_filename(template, tokens, None, digits)
            if overwrite:
                img_path = os.path.join(folder, stem + ext)
            else:
                img_path, stem = naming.free_path(folder, stem, ext, digits)
            next_index = 1
        txt_path = os.path.join(folder, stem + ".txt")

        pil = self._tensor_to_pil(image)
        kw = {}
        if ext == ".jpg":  kw = {"quality": 95, "subsampling": 0}
        if ext == ".webp": kw = {"quality": 95}
        pil.save(img_path, **kw)
        with open(txt_path, "w", encoding="utf-8") as fh:
            fh.write((caption or "").strip())

        print(f"[SaveTrainingPair] ✓ {img_path}")
        print(f"[SaveTrainingPair] ✓ {txt_path}")
        return {"ui": {"saved": [True]}, "result": (img_path, txt_path, stem, next_index)}


NODE_CLASS_MAPPINGS        = {"SaveTrainingPair": SaveTrainingPair}
NODE_DISPLAY_NAME_MAPPINGS = {"SaveTrainingPair": "Save Training Pair [umbrae]"}
