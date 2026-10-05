import json, os, re, torch
import numpy as np
import folder_paths
from PIL import Image

from . import scale_crop_shared as scs

anytype = scs.ANYTYPE

class CropImageRegion:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image":         ("IMAGE",),
                "bounding_boxes": (anytype,),
            },
            "optional": {
                "source_filename": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "Optional. Wire from the batch loader's filenames output, or leave "
                               "blank. Used to name the saved crop when Save Image is on.",
                }),
                "bbox_override": (anytype, {
                    "tooltip": "Optional fixed bounding box used as the crop anchor for every "
                               "image, overriding whichever anchor mode is selected.",
                }),
                "mask": ("MASK", {
                    "tooltip": "Optional. A mask paired 1:1 to the image; it is cropped and "
                               "resized with the exact same geometry as the image, output on the "
                               "mask socket, and (when Save Image is on) written to a masks/ "
                               "subfolder with the same filename.",
                }),
            },
            "hidden": {
                "ui_state": ("STRING", {"default": "{}"}),
            },
        }

    RETURN_TYPES  = ("IMAGE", "STRING", "MASK")
    RETURN_NAMES  = ("image", "image_path", "mask")
    FUNCTION      = "clip_region"
    CATEGORY      = "umbrae/image"
    OUTPUT_NODE   = True   # always executes even if outputs aren't wired further

    # ── Save helpers (mirrors SaveTrainingPair) ────────────────────────────────
    @staticmethod
    def _sanitize(s):
        s = re.sub(r"[\x00-\x1f\x7f]", "", str(s))
        s = re.sub(r'[\\/:*?"<>|]', "_", s)
        return s.strip(" .")

    @staticmethod
    def _comfyui_output_dir():
        return folder_paths.get_output_directory()

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    # ── Bounding-box parsing ───────────────────────────────────────────────────
    def _parse_boxes(self, bb):
        """Return list of (x1,y1,x2,y2) floats from whatever SAM3 gives us.
        Handles: raw tensor (N,4), list of dicts (native ComfyUI SAM3),
        dict with boxes key, KJ format {x,y,w,h}, flat list, SEGS."""
        if bb is None:
            return []

        # ── torch.Tensor (N,4) ────────────────────────────────────────────────
        if isinstance(bb, torch.Tensor):
            t = bb.cpu().float()
            if t.dim() == 1:
                return [tuple(t.tolist()[:4])] if t.shape[0] >= 4 else []
            while t.dim() > 2:
                t = t[0]
            if t.shape[-1] < 4:
                return []
            return [tuple(t[i].tolist()[:4]) for i in range(t.shape[0])]

        # ── dict ──────────────────────────────────────────────────────────────
        if isinstance(bb, dict):
            for key in ("boxes", "bboxes", "input_boxes", "bbox", "bounding_boxes"):
                if key in bb:
                    return self._parse_boxes(bb[key])
            # KJ / x,y,w,h format
            if "x" in bb and "y" in bb:
                x, y = float(bb["x"]), float(bb["y"])
                if "w" in bb and "h" in bb:
                    return [(x, y, x + float(bb["w"]), y + float(bb["h"]))]
                if "width" in bb and "height" in bb:
                    return [(x, y, x + float(bb["width"]), y + float(bb["height"]))]
                if "x2" in bb and "y2" in bb:
                    return [(x, y, float(bb["x2"]), float(bb["y2"]))]
            return []

        # ── list / tuple ──────────────────────────────────────────────────────
        if isinstance(bb, (list, tuple)):
            if len(bb) == 0:
                return []
            first = bb[0]

            # Flat [x1,y1,x2,y2]
            if isinstance(first, (int, float)):
                return [tuple(float(v) for v in bb[:4])] if len(bb) >= 4 else []

            # List of dicts (native ComfyUI SAM3: one dict per frame)
            if isinstance(first, dict):
                result = []
                for item in bb:
                    result.extend(self._parse_boxes(item))
                return result

            # List of tensors
            if isinstance(first, torch.Tensor):
                result = []
                for t in bb:
                    result.extend(self._parse_boxes(t))
                return result

            # List of lists / tuples
            if isinstance(first, (list, tuple)):
                result = []
                for item in bb:
                    result.extend(self._parse_boxes(item))
                return result

            # Impact Pack SEGS: (segs_header, [SEG, ...])
            if hasattr(first, "bbox"):
                result = []
                for seg in bb:
                    b = seg.bbox
                    if isinstance(b, (list, tuple)) and len(b) >= 4:
                        result.append(tuple(float(v) for v in b[:4]))
                return result

        # Impact Pack SEGS tuple: (header, [SEG, ...])
        if isinstance(bb, tuple) and len(bb) == 2 and isinstance(bb[1], list):
            result = []
            for seg in bb[1]:
                if hasattr(seg, "bbox"):
                    b = seg.bbox
                    if isinstance(b, (list, tuple)) and len(b) >= 4:
                        result.append(tuple(float(v) for v in b[:4]))
            return result

        return []

    # ── Resize (uses the shared module — same mode set as the other nodes) ─────
    def _resize_params(self, state):
        return {
            "mode":        state.get("resize_mode", "LARGEST_EDGE").upper(),
            "direction":   state.get("scale_direction", "down"),
            "target_size": int(state.get("target_size", 1024)),
            "target_mp":   float(state.get("max_mp", 1.0)),
            "width":       int(state.get("width", 1024)),
            "height":      int(state.get("height", 1024)),
            "fill":        bool(state.get("fill", True)),
            "crop_on":     bool(state.get("crop_on", True)),
            "ratio_w":     float(state.get("ratio_w", 1)),
            "ratio_h":     float(state.get("ratio_h", 1)),
        }

    def _compute_anchor(self, pil, state, bbox_override=None):
        """Anchor is derived from the IMAGE content (face/entropy/etc). Computed
        once and reused for both image and mask so their geometry is identical."""
        mode    = state.get("resize_mode", "LARGEST_EDGE").upper()
        crop_on = bool(state.get("crop_on", True))
        if mode == "CROP" and crop_on:
            advanced = {
                "torso_bias":            float(state.get("torso_bias", 0.0)),
                "headroom":              float(state.get("headroom", -0.20)),
                "face_margin_pct":       float(state.get("face_margin_pct", 0.22)),
                "top_guard_pct":         float(state.get("top_guard_pct", 0.16)),
                "face_top_guard_pct":    float(state.get("face_top_guard_pct", 0.25)),
                "min_face_frac":         float(state.get("min_face_frac", 0.06)),
                "max_face_frac":         float(state.get("max_face_frac", 0.55)),
                "reject_too_low_faces":  bool(state.get("reject_too_low_faces", True)),
                "too_low_threshold_pct": float(state.get("too_low_threshold_pct", 0.74)),
                "use_profile":           True,
                "fallback_if_no_face":   state.get("fallback_if_no_face", "entropy"),
            }
            return scs.resolve_anchor(pil, state.get("anchor_mode", "grid"),
                                       state.get("anchor_grid", "center"),
                                       state.get("anchor_xy", [0.5, 0.5]),
                                       bbox_override, advanced)
        return None

    def _apply_resize(self, pil, state, anchor, interp=Image.LANCZOS):
        p = self._resize_params(state)
        return scs.apply_resize(pil, p["mode"], interp, p["direction"], p["width"], p["height"],
                                 target_size=p["target_size"], target_mp=p["target_mp"],
                                 fill=p["fill"], crop_on=p["crop_on"],
                                 ratio_w=p["ratio_w"], ratio_h=p["ratio_h"], anchor=anchor)

    def clip_region(self, image, bounding_boxes, source_filename="", bbox_override=None, mask=None, ui_state="{}"):
        try:
            state = json.loads(ui_state or "{}")
        except Exception:
            state = {}

        padding      = float(state.get("padding",  10.0))
        padding_unit = state.get("padding_unit", "percentage")
        save_image   = state.get("save_image", True)
        output_folder= state.get("output_folder", "cropped_images")
        fmt          = state.get("format", "png")
        prefix       = state.get("prefix", "")
        suffix       = state.get("suffix", "")
        overwrite    = state.get("overwrite", True)

        # ── Convert tensor to PIL ──────────────────────────────────────────────
        img_t = image[0]  # first image in batch
        img_np = (img_t.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        pil = Image.fromarray(img_np)
        iw, ih = pil.size

        # ── Union all bounding boxes ──────────────────────────────────────────
        # Debug: print what SAM3 actually gives us
        print(f"[CropImageRegion] bounding_boxes type: {type(bounding_boxes)}")
        if hasattr(bounding_boxes, 'shape'):
            print(f"[CropImageRegion] tensor shape: {bounding_boxes.shape}, dtype: {bounding_boxes.dtype}")
            print(f"[CropImageRegion] values: {bounding_boxes}")
        else:
            print(f"[CropImageRegion] value: {repr(bounding_boxes)[:500]}")
        boxes = self._parse_boxes(bounding_boxes)
        print(f"[CropImageRegion] parsed boxes: {boxes}")
        if boxes:
            x1 = min(b[0] for b in boxes)
            y1 = min(b[1] for b in boxes)
            x2 = max(b[2] for b in boxes)
            y2 = max(b[3] for b in boxes)

            # Add padding
            bw, bh = x2 - x1, y2 - y1
            if padding_unit == "percentage":
                px = bw * (padding / 100.0)
                py = bh * (padding / 100.0)
            else:
                px = py = padding

            x1 = max(0,  x1 - px)
            y1 = max(0,  y1 - py)
            x2 = min(iw, x2 + px)
            y2 = min(ih, y2 + py)

            pil = pil.crop((int(x1), int(y1), int(x2), int(y2)))
        else:
            print("[CropImageRegion] No bounding boxes — returning full image resized.")

        # ── Resize ────────────────────────────────────────────────────────────
        anchor = self._compute_anchor(pil, state, bbox_override)
        result = self._apply_resize(pil, state, anchor, Image.LANCZOS)
        out = torch.from_numpy(
            np.array(result).astype(np.float32) / 255.0
        ).unsqueeze(0)

        # ── Mask: identical geometry (same crop rect + same anchor/resize) ─────
        mask_interp = Image.NEAREST if state.get("mask_interpolation", "nearest") == "nearest" else Image.BILINEAR
        m_res = None
        if mask is not None:
            m_t  = mask[0] if hasattr(mask, "dim") and mask.dim() == 3 else mask
            m_np = (m_t.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
            m_pil = Image.fromarray(m_np, mode="L").convert("RGB")
            if boxes:
                m_pil = m_pil.crop((int(x1), int(y1), int(x2), int(y2)))
            m_res = self._apply_resize(m_pil, state, anchor, mask_interp).convert("L")
            mask_out = torch.from_numpy(
                np.array(m_res).astype(np.float32) / 255.0
            ).unsqueeze(0)
        else:
            mask_out = torch.zeros((1, out.shape[1], out.shape[2]), dtype=torch.float32)

        # ── Save to disk ──────────────────────────────────────────────────────
        saved_path = ""
        if save_image:
            if fmt not in ("png", "jpg", "webp"):
                fmt = "png"

            folder = (output_folder or "cropped_images").strip()
            if not os.path.isabs(folder):
                folder = os.path.join(self._comfyui_output_dir(), folder)
            folder = os.path.abspath(folder)
            os.makedirs(folder, exist_ok=True)

            # source_filename may be a newline-separated list (batch mode) —
            # use an instance counter to pick the right one per call.
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

            ext = {"png": ".png", "jpg": ".jpg", "webp": ".webp"}[fmt]

            def unique(s, e):
                p = os.path.join(folder, s + e)
                if overwrite or not os.path.exists(p):
                    return p
                i = 1
                while True:
                    ns = f"{s}_{i:03d}"
                    p  = os.path.join(folder, ns + e)
                    if not os.path.exists(p):
                        return p
                    i += 1

            saved_path = unique(stem, ext)
            kw = {}
            if ext == ".jpg":  kw = {"quality": 95, "subsampling": 0}
            if ext == ".webp": kw = {"quality": 95}
            result.save(saved_path, **kw)
            print(f"[CropImageRegion] ✓ {saved_path}")

            # Paired mask → masks/ subfolder, same filename stem. PNG by default;
            # lossless formats matched; JPG only if explicitly forced (lossy is
            # bad for masks).
            if m_res is not None:
                if fmt == "webp":
                    m_ext, m_kw = ".webp", {"lossless": True}
                elif fmt == "jpg" and bool(state.get("mask_force_jpg", False)):
                    m_ext, m_kw = ".jpg", {"quality": 95, "subsampling": 0}
                else:
                    m_ext, m_kw = ".png", {}
                mask_folder = os.path.join(folder, "masks")
                os.makedirs(mask_folder, exist_ok=True)
                final_stem = os.path.splitext(os.path.basename(saved_path))[0]
                mask_path = os.path.join(mask_folder, final_stem + m_ext)
                m_res.save(mask_path, **m_kw)
                print(f"[CropImageRegion] ✓ mask {mask_path}")

        return {"ui": {"saved": [bool(save_image)]}, "result": (out, saved_path, mask_out)}
