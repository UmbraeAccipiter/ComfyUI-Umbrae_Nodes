import json, os, re
import numpy as np
import torch
import folder_paths
from PIL import Image

from . import scale_crop_shared as scs
from . import crop_core as core

anytype = scs.ANYTYPE


class UmbraeTrainingPrep:
    """Crop / resize (via crop_core) and save image + mask pairs for training, with
    tokenized filenames and the multi-instance iteration loop. Region and Region
    alternate behave exactly as in Simple Crop; this node adds saving."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
            },
            "optional": {
                "region": (anytype, {
                    "tooltip": "Bounding boxes / SEGS / detector output. Crop geometry; a SEGS also "
                               "carries a per-detection mask.",
                }),
                "region_alternate": (anytype, {
                    "tooltip": "A mask (or a second region source) cut by the same geometry.",
                }),
                "source_filename": ("STRING", {
                    "default": "", "multiline": True, "forceInput": False,
                    "tooltip": "Wire the batch loader's filenames output (or one name). Resolves the "
                               "{filename}/{stem} token. One name per line; the matching line is used "
                               "per loop iteration.",
                }),
                "caption": ("STRING", {
                    "default": "", "multiline": True, "forceInput": False,
                    "tooltip": "Caption text (typically wired from an LLM node). When Save Text is on it "
                               "is written as <stem>.txt next to the image, sharing the exact filename.",
                }),
            },
            "hidden": {"ui_state": ("STRING", {"default": "{}"})},
        }

    RETURN_TYPES = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES = ("image", "mask", "saved_paths")
    FUNCTION     = "run"
    CATEGORY     = "umbrae/image"
    OUTPUT_NODE  = True

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    # ── helpers ────────────────────────────────────────────────────────────────
    @staticmethod
    def _sanitize(s):
        s = re.sub(r"[\x00-\x1f\x7f]", "", str(s))
        s = re.sub(r'[\\/:*?"<>|]', "_", s)
        return s.strip(" .")

    @staticmethod
    def _resolve(template, ctx):
        """Replace {token}s. Known token with no data -> 'NODATA' (never empty, so
        names can't silently collide). Unknown tokens are left untouched."""
        def sub(m):
            key = m.group(1).lower()
            mapping = {
                "filename": ctx.get("stem"), "stem": ctx.get("stem"),
                "segs": ctx.get("label"), "index": ctx.get("index"),
                "ext": ctx.get("ext"), "w": ctx.get("w"), "h": ctx.get("h"),
                "folder": ctx.get("folder"),
            }
            if key not in mapping:
                return m.group(0)
            v = mapping[key]
            return str(v) if v not in (None, "") else "NODATA"
        return re.sub(r"\{([a-zA-Z]+)\}", sub, template or "")

    @staticmethod
    def _to_pil(t):
        a = (t[0].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        return Image.fromarray(a).convert("RGB")

    @staticmethod
    def _mask_to_pil(t):
        a = (t[0].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        return Image.fromarray(a, mode="L")

    @staticmethod
    def _resolve_path(folder, stem, ext, overwrite, rename_mode):
        """Return a path to write to, or None to skip. overwrite -> replace.
        Else append (next free _N at the very end of the stem) or skip."""
        p = os.path.join(folder, stem + ext)
        if overwrite or not os.path.exists(p):
            return p
        if rename_mode == "skip":
            return None
        i = 1
        while True:
            cand = os.path.join(folder, f"{stem}_{i}{ext}")
            if not os.path.exists(cand):
                return cand
            i += 1

    def run(self, image, region=None, region_alternate=None,
            source_filename="", caption="", ui_state="{}"):
        try:
            state = json.loads(ui_state or "{}")
        except Exception:
            state = {}

        res = core.process(image, region, region_alternate, state, log=print)
        crops = res["crops"]

        save_image = bool(state.get("save_image", True))
        save_mask  = bool(state.get("save_mask", True))
        save_text  = bool(state.get("save_text", True))
        cap = (caption or "").strip()
        saved_paths = []

        if save_image or save_mask or (save_text and cap):
            fmt = state.get("format", "png")
            if fmt not in ("png", "jpg", "webp"):
                fmt = "png"
            ext = {"png": ".png", "jpg": ".jpg", "webp": ".webp"}[fmt]

            folder = (state.get("output_folder", "training_data") or "training_data").strip()
            if not os.path.isabs(folder):
                folder = os.path.join(folder_paths.get_output_directory(), folder)
            folder = os.path.abspath(folder)
            os.makedirs(folder, exist_ok=True)

            prefix   = state.get("prefix", "")
            fname_t  = state.get("filename", "{filename}")
            suffix   = state.get("suffix", "_{segs}")
            digits   = max(1, int(state.get("index_digits", 4)))
            overwrite = bool(state.get("overwrite", True))
            rename_mode = state.get("rename_mode", "append")

            names = [f.strip() for f in (source_filename or "").strip().split("\n") if f.strip()]
            if not hasattr(self, "_batch_pos"):
                self._batch_pos = 0
            if len(names) > 1:
                if self._batch_pos >= len(names):
                    self._batch_pos = 0
                src_name = names[self._batch_pos]; self._batch_pos += 1
            else:
                src_name = names[0] if names else ""
            base = os.path.splitext(os.path.basename(src_name))[0] if src_name else None
            src_folder = os.path.basename(os.path.dirname(src_name)) if src_name else None

            if not hasattr(self, "_img_index"):
                self._img_index = int(state.get("start_index", 0))
            idx_str = f"{self._img_index:0{digits}d}"
            self._img_index += 1

            for crop in crops:
                img_pil = self._to_pil(crop["image"])
                w, h = img_pil.size
                ctx = {"stem": base, "label": crop.get("label"), "index": idx_str,
                       "ext": fmt, "w": w, "h": h, "folder": src_folder}
                stem = self._sanitize(self._resolve(prefix, ctx)
                                      + self._resolve(fname_t, ctx)
                                      + self._resolve(suffix, ctx)) or "image"
                final_stem = stem

                # Image
                if save_image:
                    img_path = self._resolve_path(folder, stem, ext, overwrite, rename_mode)
                    if img_path is None:
                        print(f"[TrainingPrep] image exists, skip: {stem}{ext}")
                    else:
                        kw = {}
                        if ext == ".jpg":  kw = {"quality": 95, "subsampling": 0}
                        if ext == ".webp": kw = {"quality": 95}
                        img_pil.save(img_path, **kw)
                        saved_paths.append(img_path)
                        final_stem = os.path.splitext(os.path.basename(img_path))[0]
                        print(f"[TrainingPrep] \u2713 {img_path}")

                # Mask -> masks/, mirrors the image's final stem (no separate renaming)
                mt = crop.get("mask")
                if save_mask and mt is not None and float(mt.float().sum()) > 0:
                    if fmt == "webp":
                        m_ext, m_kw = ".webp", {"lossless": True}
                    elif fmt == "jpg" and bool(state.get("mask_force_jpg", False)):
                        m_ext, m_kw = ".jpg", {"quality": 95, "subsampling": 0}
                    else:
                        m_ext, m_kw = ".png", {}
                    mfolder = os.path.join(folder, "masks")
                    os.makedirs(mfolder, exist_ok=True)
                    mpath = os.path.join(mfolder, final_stem + m_ext)
                    if overwrite or not os.path.exists(mpath):
                        self._mask_to_pil(mt).save(mpath, **m_kw)

                # Text sidecar -> <stem>.txt, same name as the image
                if save_text and cap:
                    tpath = os.path.join(folder, final_stem + ".txt")
                    if overwrite or not os.path.exists(tpath):
                        with open(tpath, "w", encoding="utf-8") as fh:
                            fh.write(cap)
                        saved_paths.append(tpath)
                        print(f"[TrainingPrep] \u2713 text {tpath}")

        return {"ui": {"saved": [len(saved_paths)]},
                "result": (res["images"], res["masks"], "\n".join(saved_paths))}


NODE_CLASS_MAPPINGS        = {"UmbraeTrainingPrep": UmbraeTrainingPrep}
NODE_DISPLAY_NAME_MAPPINGS = {"UmbraeTrainingPrep": "Training Prep [umbrae]"}
