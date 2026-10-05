# load_images_uniform_batch.py — UNP
#
# Loads images from a folder with built-in iteration.
# The image_index widget tracks the current position — it advances automatically
# after each save (via SaveTrainingPair) and can be edited manually to resume.
#
# Outputs current_index so SelectImageAndName can pick the right image
# from a full batch in uniform mode.

import json
import mimetypes
import os
import string

import numpy as np
import torch
import folder_paths
from PIL import Image, ImageOps, ImageSequence

from . import scale_crop_shared as scs
from . import metadata_wildcards as mw

try:
    from aiohttp import web
    from server import PromptServer
except Exception:
    web = PromptServer = None


class LoadImagesUniformBatch:

    IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")

    DEFAULT_STATE = {
        "folder_label":    "",
        "custom_path":     "",
        "resize_mode":     "LARGEST_EDGE",   # OFF | LARGEST_EDGE | MAX_MP | FIT_AND_PAD | CROP | FORCE_EXACT
        "target_size":     1024,
        "width":           1024,
        "height":          1024,
        "max_mp":          1.0,
        "interpolation":   "lanczos",
        "scale_direction": "down",   # "down" | "up" | "both"
        "uniform_batch":   False,
        # CROP mode — independent fill/crop toggles
        "fill":            True,
        "crop_on":         True,
        "ratio_w":         1,
        "ratio_h":         1,
        # Anchor — used whenever CROP actually crops
        "anchor_mode":     "grid",   # "grid" | "face" | "entropy" | "xy"
        "anchor_grid":     "center",
        "anchor_xy":       [0.5, 0.5],
        # Advanced (shared fine-tuning, mirrors SaveImageSmart)
        "torso_bias":          0.0,
        "headroom":            -0.20,
        "face_margin_pct":     0.22,
        "top_guard_pct":       0.16,
        "face_top_guard_pct":  0.25,
        "min_face_frac":       0.06,
        "max_face_frac":       0.55,
        "fallback_if_no_face": "entropy",
        "speed_mode":          "balanced",
    }

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image_index": ("INT", {
                    "default": 0, "min": 0,
                    "tooltip": "Current image index. Advances automatically during iteration. "
                               "Edit manually to resume from a specific image.",
                }),
            },
            "optional": {
                "custom_folder_path": ("STRING", {
                    "default": "",
                    "tooltip": "Override the folder browser. Type a path or wire a STRING node.",
                }),
                "bbox_override": (scs.ANYTYPE, {
                    "tooltip": "Optional fixed bounding box used as the crop anchor for every "
                               "image, overriding whichever anchor mode is selected. Useful for "
                               "a fixed camera angle where the subject is always in the same region.",
                }),
            },
            "hidden": {
                "ui_state": ("STRING", {"default": "{}"}),
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    RETURN_TYPES  = ("IMAGE", "STRING", "STRING", "INT", "INT", "INT", "STRING")
    RETURN_NAMES  = ("images", "filenames", "folder_path", "count", "last_index", "current_index", "metadata")
    FUNCTION      = "load_images"
    CATEGORY      = "umbrae/files"

    # Folder-list entry for ComfyUI's input folder itself (the default for a new node).
    ROOT_LABEL = "[input folder]"

    # ── Helpers ───────────────────────────────────────────────────────────────

    @classmethod
    def _default_browse_dir(cls):
        return folder_paths.get_input_directory()

    @classmethod
    def _resolve_folder(cls, folder_label, custom_path=""):
        if custom_path and os.path.isdir(custom_path):
            return os.path.abspath(custom_path)
        rel = str(folder_label).split(" (")[0].strip()
        if not rel or rel == cls.ROOT_LABEL:
            return cls._default_browse_dir()
        return os.path.join(cls._default_browse_dir(), rel)

    @classmethod
    def _sorted_images(cls, folder_path):
        if not os.path.isdir(folder_path):
            return []
        return sorted(
            (f for f in os.listdir(folder_path) if f.lower().endswith(cls.IMAGE_EXTS)),
            key=str.lower,
        )

    def _interp(self, name):
        return {"lanczos": Image.LANCZOS, "bilinear": Image.BILINEAR,
                "bicubic": Image.BICUBIC, "nearest": Image.NEAREST
                }.get(str(name).lower(), Image.LANCZOS)

    def _ui(self, result, total, idx):
        return {"ui": {"file_count": [total], "current_idx": [idx]}, "result": result}

    def _to_tensor(self, pil):
        return torch.from_numpy(
            np.asarray(pil.convert("RGB"), dtype=np.float32) / 255.0
        )[None, ...]

    # ── Main ─────────────────────────────────────────────────────────────────

    def load_images(self, image_index=0, custom_folder_path="", bbox_override=None, ui_state="{}"):
        state = dict(self.DEFAULT_STATE)
        try:
            state.update(json.loads(ui_state or "{}"))
        except Exception:
            pass

        resize_mode    = state.get("resize_mode",    "LARGEST_EDGE").upper()
        target_size    = max(8, int(state.get("target_size", 1024)))
        width          = max(8, int(state.get("width",  1024)))
        height         = max(8, int(state.get("height", 1024)))
        max_mp_val     = max(0.01, float(state.get("max_mp", 1.0)))
        # Migrate older saved workflows that only have the legacy boolean.
        direction      = state.get("scale_direction") or ("down" if state.get("only_downscale", True) else "both")
        uniform_batch  = bool(state.get("uniform_batch",  False))
        interp         = self._interp(state.get("interpolation", "lanczos"))

        fill        = bool(state.get("fill", True))
        crop_on     = bool(state.get("crop_on", True))
        ratio_w     = max(0.01, float(state.get("ratio_w", 1)))
        ratio_h     = max(0.01, float(state.get("ratio_h", 1)))
        anchor_mode = state.get("anchor_mode", "grid")
        anchor_grid = state.get("anchor_grid", "center")
        anchor_xy   = state.get("anchor_xy", [0.5, 0.5])

        speed = state.get("speed_mode", "balanced")
        speed_presets = {
            "fast":    {"det_scale": 0.5, "ent_scale": 0.4, "ent_stride_div": 3},
            "quality": {"det_scale": 1.0, "ent_scale": 1.0, "ent_stride_div": 6},
        }
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
            **speed_presets.get(speed, {"det_scale": 0.6, "ent_scale": 0.5, "ent_stride_div": 4}),
        }

        effective_path = (custom_folder_path or "").strip() or state.get("custom_path", "").strip()
        folder_path    = self._resolve_folder(state.get("folder_label", ""), effective_path)
        all_files      = self._sorted_images(folder_path)
        total          = len(all_files)

        try:
            # ui_state may carry a "next_index" set by SaveTrainingPair JS
            # which is more reliable than the widget value in auto-queue scenarios
            raw_idx = state.get("next_index", image_index)
            idx = max(0, min(int(raw_idx), total - 1)) if total else 0
        except Exception:
            idx = 0

        dynamic = scs.mode_is_dynamic_size(resize_mode, fill, crop_on)

        def meta_line(fname):
            # One compact JSON object per image: extracted generation fields
            # (when the file carries ComfyUI metadata) + source_path/created/
            # modified. Save Image Smart consumes this for metadata wildcards
            # and preserve-metadata mode.
            try:
                return json.dumps(mw.metadata_for_file(os.path.join(folder_path, fname)))
            except Exception as exc:
                print(f"[LoadImagesUniformBatch] Metadata read failed for {fname}: {exc}")
                return json.dumps({"source_path": os.path.abspath(os.path.join(folder_path, fname))})

        def empty(w, h):
            return (torch.zeros((1, h, w, 3)), "", folder_path, total, total - 1, idx, "")

        if not total:
            print(f"[LoadImagesUniformBatch] No images in: {folder_path}")
            ph, ph_h = (target_size, target_size) if resize_mode in ("LARGEST_EDGE", "MAX_MP") else (width, height)
            return self._ui(empty(ph, ph_h), 0, 0)

        def resize_one(frame):
            anchor = None
            if resize_mode == "CROP" and crop_on:
                anchor = scs.resolve_anchor(frame, anchor_mode, anchor_grid, anchor_xy, bbox_override, advanced)
            return scs.apply_resize(frame, resize_mode, interp, direction, width, height,
                                     target_size=target_size, target_mp=max_mp_val,
                                     fill=fill, crop_on=crop_on, ratio_w=ratio_w, ratio_h=ratio_h,
                                     anchor=anchor)

        # OFF always streams one image at a time: batching native-resolution images
        # means padding every frame to the largest and stacking them, which OOMs on
        # big sources. uniform_batch only governs the resize modes (uniform output).
        if not uniform_batch or resize_mode == "OFF":
            # Single-image mode: load only the image at image_index.
            # Natural per-image size preserved, no padding, no torch.cat of mixed sizes.
            fname = all_files[idx]
            try:
                with Image.open(os.path.join(folder_path, fname)) as img:
                    img   = ImageOps.exif_transpose(img)
                    frame = next(iter(ImageSequence.Iterator(img))).convert("RGB")
                    proc  = resize_one(frame)
                    return self._ui((self._to_tensor(proc), fname, folder_path, total, total - 1, idx,
                                     meta_line(fname)), total, idx)
            except Exception as exc:
                print(f"[LoadImagesUniformBatch] Failed {fname}: {exc}")
                return self._ui(empty(target_size, target_size), total, idx)

        # Batch mode: load all images from idx onward
        batch, names = [], []

        if dynamic:
            resized = []
            for fname in all_files[idx:]:
                try:
                    with Image.open(os.path.join(folder_path, fname)) as img:
                        img = ImageOps.exif_transpose(img)
                        for frame in ImageSequence.Iterator(img):
                            resized.append((resize_one(frame.convert("RGB")), fname))
                except Exception as exc:
                    print(f"[LoadImagesUniformBatch] Skipping {fname}: {exc}")

            if not resized:
                return self._ui(empty(target_size, target_size), total, idx)

            max_w = max(im.width  for im, _ in resized)
            max_h = max(im.height for im, _ in resized)
            for proc, fname in resized:
                batch.append(self._to_tensor(scs.pad_to(proc, max_w, max_h)))
                names.append(fname)

        else:
            for fname in all_files[idx:]:
                try:
                    with Image.open(os.path.join(folder_path, fname)) as img:
                        img = ImageOps.exif_transpose(img)
                        for frame in ImageSequence.Iterator(img):
                            proc = resize_one(frame.convert("RGB"))
                            batch.append(self._to_tensor(proc))
                            names.append(fname)
                except Exception as exc:
                    print(f"[LoadImagesUniformBatch] Skipping {fname}: {exc}")

        if not batch:
            ph, ph_h = (target_size, target_size) if resize_mode in ("LARGEST_EDGE", "MAX_MP") else (width, height)
            return self._ui(empty(ph, ph_h), total, idx)

        meta_cache = {}
        metas = [meta_cache.setdefault(n, meta_line(n)) for n in names]
        return self._ui((torch.cat(batch, dim=0), "\n".join(names), folder_path, total, total - 1, idx,
                         "\n".join(metas)), total, idx)


NODE_CLASS_MAPPINGS        = {"LoadImagesUniformBatch": LoadImagesUniformBatch}
NODE_DISPLAY_NAME_MAPPINGS = {"LoadImagesUniformBatch": "Load Images Batch [umbrae]"}

# ── Server routes ─────────────────────────────────────────────────────────────

if PromptServer and web:

    @PromptServer.instance.routes.get("/unp/batch_folders")
    async def _unp_batch_folders(request):
        output_dir = LoadImagesUniformBatch._default_browse_dir()
        folders = []
        root_count = 0
        if os.path.isdir(output_dir):
            for root, dirs, files in os.walk(output_dir):
                rel = os.path.relpath(root, output_dir)
                count = sum(1 for f in os.listdir(root)
                            if f.lower().endswith(LoadImagesUniformBatch.IMAGE_EXTS))
                if rel == ".":
                    root_count = count
                elif count > 0:
                    folders.append({"label": f"{rel} ({count} images)", "rel": rel, "count": count})
        folders.sort(key=lambda x: x["label"].lower())
        # The input folder itself always comes first (even with 0 images) so a new
        # node has a predictable default instead of whichever subfolder sorts first.
        root_label = LoadImagesUniformBatch.ROOT_LABEL
        folders.insert(0, {"label": f"{root_label} ({root_count} images)", "rel": ".", "count": root_count})
        return web.json_response({"folders": folders})

    @PromptServer.instance.routes.get("/unp/batch_images")
    async def _unp_batch_images(request):
        folder_path = LoadImagesUniformBatch._resolve_folder(
            request.query.get("folder_label", ""),
            request.query.get("custom_path",  "").strip(),
        )
        files = LoadImagesUniformBatch._sorted_images(folder_path)
        return web.json_response({"folder_path": folder_path, "files": files, "count": len(files)})

    @PromptServer.instance.routes.get("/unp/batch_image_view")
    async def _unp_batch_image_view(request):
        folder_path = request.query.get("folder_path", "").strip()
        filename    = request.query.get("filename",    "").strip()
        if not folder_path or not filename:
            return web.Response(status=400, text="Missing params")
        safe_folder = os.path.abspath(folder_path)
        safe_file   = os.path.abspath(os.path.join(safe_folder, filename))
        if os.path.relpath(safe_file, safe_folder).startswith(".."):
            return web.Response(status=403, text="Forbidden")
        if not os.path.isfile(safe_file):
            return web.Response(status=404, text="Not found")
        mime, _ = mimetypes.guess_type(safe_file)
        with open(safe_file, "rb") as fh:
            data = fh.read()
        return web.Response(body=data, content_type=mime or "image/jpeg")

    @PromptServer.instance.routes.get("/unp/browse_dir")
    async def _unp_browse_dir(request):
        """Real filesystem drill-down: list subdirectories of `path`, with
        image counts, an `Up` target, and a drive list when path is empty."""
        path = request.query.get("path", "").strip()

        if not path:
            roots = []
            if os.name == "nt":
                for letter in string.ascii_uppercase:
                    drive = f"{letter}:\\"
                    if os.path.exists(drive):
                        roots.append({"name": drive, "path": drive, "image_count": 0})
            else:
                roots.append({"name": "/", "path": "/", "image_count": 0})
                home = os.path.expanduser("~")
                if os.path.isdir(home) and home != "/":
                    roots.append({"name": f"~  ({home})", "path": home, "image_count": 0})
            return web.json_response({
                "current_path": "", "parent_path": None, "dirs": roots, "image_count": 0,
            })

        path = os.path.abspath(path)
        if not os.path.isdir(path):
            return web.json_response({"error": "Not a directory"}, status=400)

        try:
            entries = os.listdir(path)
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=403)

        dirs = []
        image_count = 0
        for entry in sorted(entries, key=str.lower):
            full = os.path.join(path, entry)
            if os.path.isdir(full):
                try:
                    sub = os.listdir(full)
                    count = sum(1 for f in sub if f.lower().endswith(LoadImagesUniformBatch.IMAGE_EXTS))
                except Exception:
                    count = 0
                dirs.append({"name": entry, "path": full, "image_count": count})
            elif entry.lower().endswith(LoadImagesUniformBatch.IMAGE_EXTS):
                image_count += 1

        stripped = path.rstrip("\\/") or path
        parent = os.path.dirname(stripped)
        if parent == stripped or not parent:
            # At a real filesystem root (e.g. "/" or "C:\\") — Up goes back
            # to the drive list on Windows, or nowhere further on POSIX.
            parent_path = "" if os.name == "nt" else None
        else:
            parent_path = parent

        return web.json_response({
            "current_path": path,
            "parent_path":  parent_path,
            "dirs":         dirs,
            "image_count":  image_count,
        })

    @PromptServer.instance.routes.get("/unp/batch_image_info")
    async def _unp_batch_image_info(request):
        folder_path = request.query.get("folder_path", "").strip()
        filename    = request.query.get("filename",    "").strip()
        if not folder_path or not filename:
            return web.Response(status=400, text="Missing params")
        safe_folder = os.path.abspath(folder_path)
        safe_file   = os.path.abspath(os.path.join(safe_folder, filename))
        if os.path.relpath(safe_file, safe_folder).startswith("..") or not os.path.isfile(safe_file):
            return web.Response(status=404, text="Not found")

        try:
            file_size = os.path.getsize(safe_file)
            with Image.open(safe_file) as img:
                width, height = img.size
                fmt  = (img.format or "").upper()
                mode = img.mode
                try:
                    frame_count = getattr(img, "n_frames", 1)
                except Exception:
                    frame_count = 1
                dpi = img.info.get("dpi")
                exif_orientation = None
                try:
                    exif = img.getexif()
                    if exif:
                        exif_orientation = exif.get(0x0112)  # Orientation tag
                except Exception:
                    pass

            def human_size(n):
                for unit in ("B", "KB", "MB", "GB"):
                    if n < 1024 or unit == "GB":
                        return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
                    n /= 1024

            g = scs.gcd(width, height)
            return web.json_response({
                "width": width, "height": height,
                "megapixels": round(width * height / 1_048_576, 2),
                "aspect_ratio": f"{width // g}:{height // g}",
                "format": fmt or "?",
                "mode": mode,
                "frame_count": frame_count,
                "file_size_bytes": file_size,
                "file_size_human": human_size(file_size),
                "dpi": list(dpi) if dpi else None,
                "exif_orientation": exif_orientation,
            })
        except Exception as exc:
            return web.json_response({"error": str(exc)}, status=500)

    @PromptServer.instance.routes.get("/bjornulf/get_uniform_image_folders")
    async def _bjornulf_folders(request):
        output_dir = LoadImagesUniformBatch._default_browse_dir()
        folders = []
        if os.path.isdir(output_dir):
            for root, dirs, files in os.walk(output_dir):
                rel = os.path.relpath(root, output_dir)
                if rel == ".":
                    continue
                count = sum(1 for f in os.listdir(root)
                            if f.lower().endswith(LoadImagesUniformBatch.IMAGE_EXTS))
                if count > 0:
                    folders.append(f"{rel} ({count} images)")
        folders.sort(key=str.lower)
        return web.json_response({"success": True, "folders": folders})
