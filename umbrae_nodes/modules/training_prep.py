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
    alternate behave exactly as in Simple Crop; this node adds saving.

    Takes LISTS (INPUT_IS_LIST): the crop list from crop image [umbrae], the
    caption list from vlm generate [umbrae], the loader's filenames. Captions
    pair with crops by index (one per crop, or one per source image, or one for
    all). Every crop is saved at its native size; nothing is padded."""

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
                "upscale_model": ("UPSCALE_MODEL", {
                    "tooltip": "Optional. When the resize stage enlarges a crop (direction Up / Both), "
                               "the model does the enlarging instead of Lanczos; the final size is "
                               "unchanged. Ignored for downscaling.",
                }),
                "caption": ("STRING", {
                    "default": "", "multiline": True, "forceInput": False,
                    "tooltip": "Caption text, usually vlm generate's `text` list (one caption per crop, "
                               "paired by index; a single caption applies to every crop). When Save Text "
                               "is on it is written as <stem>.txt next to the image, same filename.",
                }),
            },
            "hidden": {"ui_state": ("STRING", {"default": "{}"})},
        }

    RETURN_TYPES   = ("IMAGE", "MASK", "STRING")
    RETURN_NAMES   = ("image", "mask", "saved_paths")
    INPUT_IS_LIST  = True
    OUTPUT_IS_LIST = (True, True, False)
    FUNCTION       = "run"
    CATEGORY       = "umbrae/image"
    OUTPUT_NODE    = True

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
            source_filename=None, caption=None, ui_state=None, upscale_model=None):
        ui_list = core.as_list(ui_state)
        try:
            state = json.loads(ui_list[0] or "{}") if ui_list else {}
        except Exception:
            state = {}

        # ── crop every frame of every incoming image ───────────────────────────
        entries = core.expand_inputs(image, region, region_alternate)
        n_frames = len(entries)
        ups = core.as_list(upscale_model)
        upscaler = scs.model_upscaler(ups[0]) if ups else None
        crops = []
        for fi, e in enumerate(entries):
            for c in core.process_frame(e["frame"], e["region"], e["alt"], state, log=print,
                                        upscaler=upscaler)["crops"]:
                c["frame_idx"] = fi
                crops.append(c)
        n_crops = len(crops)

        # ── pair captions: per crop, per source frame, or one for all ─────────
        captions = [str(c or "").strip() for c in core.as_list(caption)]
        def caption_for(crop, ci):
            if not captions:
                return ""
            if len(captions) == n_crops:
                return captions[ci]
            if len(captions) == n_frames:
                return captions[crop["frame_idx"]]
            return captions[0]

        # ── pair source filenames (one per frame, or one for all) ─────────────
        names = []
        for s in core.as_list(source_filename):
            names.extend(f.strip() for f in str(s or "").split("\n") if f.strip())
        if not hasattr(self, "_batch_pos"):
            self._batch_pos = 0
        def name_for(crop):
            if not names:
                return ""
            if len(names) == n_frames:
                return names[crop["frame_idx"]]
            if len(names) == 1:
                return names[0]
            # Legacy: more names than frames (old multi-execution wiring) -> cycle.
            if self._batch_pos >= len(names):
                self._batch_pos = 0
            n = names[self._batch_pos]; self._batch_pos += 1
            return n

        save_image = bool(state.get("save_image", True))
        save_mask  = bool(state.get("save_mask", True))
        save_text  = bool(state.get("save_text", True))
        saved_paths = []

        if save_image or save_mask or (save_text and any(captions)):
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

            if not hasattr(self, "_img_index"):
                self._img_index = int(state.get("start_index", 0))
            idx_str = f"{self._img_index:0{digits}d}"
            self._img_index += 1

            # Paths written in THIS run. Two crops of one source that resolve to the
            # same stem (e.g. no label) must not overwrite each other, whatever the
            # Overwrite setting says about files from earlier runs.
            written = set()

            for ci, crop in enumerate(crops):
                src_name = name_for(crop)
                base = os.path.splitext(os.path.basename(src_name))[0] if src_name else None
                src_folder = os.path.basename(os.path.dirname(src_name)) if src_name else None
                cap = caption_for(crop, ci)
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
                    if img_path is not None and img_path in written:
                        img_path = self._resolve_path(folder, stem, ext, False, "append")
                    if img_path is None:
                        print(f"[TrainingPrep] image exists, skip: {stem}{ext}")
                    else:
                        kw = {}
                        quality = max(1, min(100, int(state.get("quality", 95))))
                        if ext == ".jpg":  kw = {"quality": quality, "subsampling": 0}
                        if ext == ".webp": kw = {"quality": quality}
                        img_pil.save(img_path, **kw)
                        written.add(img_path)
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

        if not crops:
            return {"ui": {"saved": [0]}, "result": ([], [], "")}
        return {"ui": {"saved": [len(saved_paths)]},
                "result": ([c["image"] for c in crops], [c["mask"] for c in crops],
                           "\n".join(saved_paths))}


NODE_CLASS_MAPPINGS        = {"UmbraeTrainingPrep": UmbraeTrainingPrep}
NODE_DISPLAY_NAME_MAPPINGS = {"UmbraeTrainingPrep": "Training Prep [umbrae]"}
