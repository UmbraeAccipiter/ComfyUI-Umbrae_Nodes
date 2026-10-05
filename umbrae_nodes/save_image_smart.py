# save_image_smart.py — UNP
#
# Resize/crop/anchor behavior now comes entirely from scale_crop_shared,
# the same module LoadImagesUniformBatch and CropImageRegion use, configured
# through the DOM panel (ui_state) instead of ~25 native widgets. Only
# genuinely save-specific concerns stay here: folder, format, quality,
# renaming/sequencing, optimize/lossless.

import json, os, re
import numpy as np
import torch
import folder_paths
from PIL import Image, ImageOps
from PIL.PngImagePlugin import PngInfo

from . import scale_crop_shared as scs
from . import metadata_wildcards as mw


class SaveImageSmart:

    DEFAULT_STATE = {
        "resize_mode":     "CROP",
        "target_size":     1024,
        "width":           1024,
        "height":          1024,
        "max_mp":          1.0,
        "scale_direction": "down",
        "fill":            True,
        "crop_on":         True,
        "ratio_w":         1,
        "ratio_h":         1,
        "anchor_mode":     "face",
        "anchor_grid":     "center",
        "anchor_xy":       [0.5, 0.5],
        "torso_bias":            0.0,
        "headroom":              -0.20,
        "face_margin_pct":       0.22,
        "top_guard_pct":         0.16,
        "face_top_guard_pct":    0.25,
        "min_face_frac":         0.06,
        "max_face_frac":         0.55,
        "reject_too_low_faces":  True,
        "too_low_threshold_pct": 0.74,
        "fallback_if_no_face":   "entropy",
        "speed_mode":            "balanced",
        # Save-specific
        "output_folder":   "",
        "format":          "png",
        "quality":         95,
        "rename_mode":     "pattern",   # "source_stem" | "base_stem" | "pattern"
        "base_name":       "image",
        "rename_pattern":  "myset",
        "sequence_index":  0,
        "auto_index":      True,
        "auto_index_pad":  3,
        "optimize":        True,
        "lossless_webp":   False,
        "preserve_metadata": False,   # off: embed current workflow; on: copy source file's embedded metadata
    }

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
            },
            "optional": {
                "source_file": ("STRING", {
                    "default": "", "multiline": True,
                    "tooltip": "Optional. Wire from the batch loader's filenames output, or leave "
                               "blank to save directly from the incoming image tensor. Used for "
                               "SOURCE_STEM naming and as a fallback original-resolution read "
                               "when available on disk.",
                }),
                "bbox_override": (scs.ANYTYPE, {
                    "tooltip": "Optional fixed bounding box used as the crop anchor for every "
                               "image, overriding whichever anchor mode is selected.",
                }),
                "metadata": ("STRING", {
                    "default": "", "multiline": True, "forceInput": True,
                    "tooltip": "Optional. Wire from the batch loader's metadata output. One JSON "
                               "object per line, aligned with filenames: extracted generation "
                               "fields + source_path/created/modified. Feeds metadata wildcards "
                               "and preserve-metadata mode.",
                }),
            },
            "hidden": {
                "ui_state": ("STRING", {"default": "{}"}),
                "prompt": "PROMPT",
                "extra_pnginfo": "EXTRA_PNGINFO",
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "IMAGE")
    RETURN_NAMES = ("saved_paths", "saved_filenames", "saved_folder", "cropped_images")
    OUTPUT_NODE = True   # valid terminal node — executes without downstream consumers
    FUNCTION = "save"
    CATEGORY = "umbrae/files"

    # ── small utils ──────────────────────────────────────────────────────────
    def _sanitize(self, s):
        s = re.sub(r"[\x00-\x1f\x7f]", "", s)
        s = re.sub(r'[\\/:*?"<>|]', "_", s)
        return s.strip(" .")

    def _ensure_folder(self, p):
        if not p:
            p = folder_paths.get_output_directory()
        elif not os.path.isabs(p):
            # Relative patterns land under ComfyUI's output dir
            # (e.g. "images/{model}" → output/images/<model>).
            p = os.path.join(folder_paths.get_output_directory(), p)
        os.makedirs(p, exist_ok=True)
        return os.path.abspath(p)

    def _tensor_to_pil(self, t):
        arr = (t.clamp(0, 1).cpu().numpy() * 255.0).round().astype(np.uint8)
        return Image.fromarray(arr, mode="RGB")

    def _pil_to_tensor(self, im):
        arr = np.array(im.convert("RGB"), dtype=np.uint8).astype(np.float32) / 255.0
        return torch.from_numpy(arr)[None, ...]

    def _stem(self, name):
        return os.path.splitext(name)[0] if name else "image"

    def _auto_orient(self, img):
        return ImageOps.exif_transpose(img)

    def _open_original(self, p):
        try:
            im = Image.open(p)
            im = ImageOps.exif_transpose(im)
            return im.convert("RGB")
        except Exception:
            return None

    # ── naming helpers ───────────────────────────────────────────────────────
    def _has_index_tokens(self, pattern):
        return bool(pattern) and bool(re.search(r"\{(i|z\d+|seq|zseq\d+)\}", pattern))

    def _next_index_in_folder(self, folder, stem, ext):
        try:
            files = os.listdir(folder)
        except Exception:
            return 1
        rx = re.compile(rf"^{re.escape(stem)}_(\d+)\.{re.escape(ext)}$", re.IGNORECASE)
        m = 0
        for f in files:
            mm = rx.match(f)
            if mm:
                try:
                    m = max(m, int(mm.group(1)))
                except Exception:
                    pass
        return m + 1

    def _apply_pattern(self, pattern, stem, base, i, total, seq):
        s = pattern or ""
        s = s.replace("{i}", str(i + 1))
        s = re.sub(r"\{z(\d+)\}", lambda m: str(i + 1).zfill(int(m.group(1))), s)
        s = s.replace("{seq}", str(seq))
        s = re.sub(r"\{zseq(\d+)\}", lambda m: str(seq).zfill(int(m.group(1))), s)
        s = s.replace("{stem}", stem).replace("{base}", base)
        return self._sanitize(s)

    # ── main ─────────────────────────────────────────────────────────────────
    def save(self, image, source_file="", bbox_override=None, metadata="",
             ui_state="{}", prompt=None, extra_pnginfo=None):
        state = dict(self.DEFAULT_STATE)
        try:
            state.update(json.loads(ui_state or "{}"))
        except Exception:
            pass

        if not isinstance(image, torch.Tensor) or image.ndim != 4 or image.shape[-1] != 3:
            raise ValueError("[SaveImageSmart] Expected IMAGE tensor (N,H,W,3)")

        # Folder may contain metadata wildcards → resolved per image, below.
        folder_pattern = (state.get("output_folder") or "").strip()
        preserve_meta = bool(state.get("preserve_metadata", False))
        fmt = (state.get("format") or "png").lower().strip()
        if fmt not in ("png", "jpg", "webp"):
            fmt = "png"
        quality = int(state.get("quality", 95))
        optimize = bool(state.get("optimize", True))
        lossless_webp = bool(state.get("lossless_webp", False))

        rename_mode = state.get("rename_mode", "pattern")
        rename_pattern = state.get("rename_pattern", "myset")
        auto_index = bool(state.get("auto_index", True))
        auto_index_pad = int(state.get("auto_index_pad", 3))

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

        resize_mode = state.get("resize_mode", "CROP").upper()
        direction   = state.get("scale_direction", "down")
        interp      = Image.LANCZOS
        target_size = int(state.get("target_size", 1024))
        target_mp   = float(state.get("max_mp", 1.0))
        width       = int(state.get("width", 1024))
        height      = int(state.get("height", 1024))
        fill        = bool(state.get("fill", True))
        crop_on     = bool(state.get("crop_on", True))
        ratio_w     = float(state.get("ratio_w", 1))
        ratio_h     = float(state.get("ratio_h", 1))
        anchor_mode = state.get("anchor_mode", "face")
        anchor_grid = state.get("anchor_grid", "center")
        anchor_xy   = state.get("anchor_xy", [0.5, 0.5])

        raw_src = (source_file or "").splitlines()
        src_list = [ln.strip() for ln in raw_src if ln.strip()]
        N = int(image.shape[0])

        # Wired metadata: one JSON object per line, aligned with filenames.
        meta_list = []
        for ln in (metadata or "").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                meta_list.append(json.loads(ln))
            except Exception:
                meta_list.append({})

        # Live generation fields from this run's flattened prompt — the base
        # layer; overlaid by source-file metadata, then by the wired metadata
        # input (highest priority) so converted images keep their own history.
        live_fields = mw.extract_fields(prompt) if isinstance(prompt, dict) else {}

        seq_num = int(state.get("sequence_index", 0))
        if seq_num <= 0:
            seq_num = int(state.get("sequence_index", 0)) + 1

        saved_full, saved_names, cropped_batches, folders_used = [], [], [], []

        for i in range(N):
            src_i = src_list[i] if i < len(src_list) else ""
            # Pixels come from source_file only when it's an actual readable
            # path; the stem falls back to the bare filename (the batch
            # loader's filenames output has no folder) and then to the wired
            # metadata's source_path — so Source Stem naming works even when
            # the pixels arrive via the IMAGE tensor.
            pil_img, src_stem = None, ""
            if src_i and os.path.isfile(src_i):
                pil_img = self._open_original(src_i)
            if src_i:
                src_stem = self._stem(os.path.basename(src_i.replace("\\", "/")))
            if pil_img is None:
                pil_img = self._auto_orient(self._tensor_to_pil(image[i]))

            # ---- metadata merge: live prompt ← source file ← wired input ----
            meta = dict(live_fields)
            wired = meta_list[i] if i < len(meta_list) else None
            if wired is None and src_i and os.path.isfile(src_i):
                try:
                    wired = mw.metadata_for_file(src_i)
                except Exception:
                    wired = None
            if wired:
                meta.update({k: v for k, v in wired.items() if v not in (None, "")})
            if not src_stem and meta.get("source_path"):
                src_stem = self._stem(os.path.basename(str(meta["source_path"]).replace("\\", "/")))

            anchor = None
            if resize_mode == "CROP" and crop_on:
                anchor = scs.resolve_anchor(pil_img, anchor_mode, anchor_grid, anchor_xy,
                                             bbox_override, advanced)
            cropped = scs.apply_resize(pil_img, resize_mode, interp, direction, width, height,
                                        target_size=target_size, target_mp=target_mp,
                                        fill=fill, crop_on=crop_on, ratio_w=ratio_w, ratio_h=ratio_h,
                                        anchor=anchor)

            # ---- dimensions of the image actually being saved ----
            meta["width"], meta["height"] = cropped.width, cropped.height
            meta["size"] = f"{cropped.width}x{cropped.height}"

            # ---- folder (metadata wildcards allowed; / creates subfolders;
            #      relative patterns are rooted at ComfyUI's output dir) ----
            folder = self._ensure_folder(mw.resolve_folder(folder_pattern, meta))
            if folder not in folders_used:
                folders_used.append(folder)

            # ---- naming (metadata/date/time tokens first, index tokens after) ----
            pattern_i = mw.resolve(rename_pattern, meta)
            base_i = self._sanitize(os.path.basename(mw.resolve(state.get("base_name") or "image", meta))) or "image"
            base_stem_i = self._stem(base_i)
            if rename_mode == "source_stem" and src_stem:
                stem = src_stem
            elif rename_mode == "base_stem":
                stem = base_stem_i
            else:
                pattern_has_index = self._has_index_tokens(pattern_i)
                stem = (self._apply_pattern(pattern_i, src_stem or base_stem_i, base_stem_i, i, N, seq_num)
                        if pattern_has_index else
                        self._sanitize(self._apply_pattern(pattern_i, src_stem or base_stem_i,
                                                            base_stem_i, 0, 1, seq_num)))
            if auto_index and not (rename_mode == "pattern" and self._has_index_tokens(pattern_i)):
                next_idx = self._next_index_in_folder(folder, stem, fmt)
                stem = f"{stem}_{str(next_idx).zfill(max(1, auto_index_pad))}"

            out_name = f"{stem}.{fmt}"
            out_path = os.path.join(folder, out_name)
            if os.path.exists(out_path):
                k = 1
                while True:
                    cand = f"{stem}_{str(k).zfill(4)}.{fmt}"
                    cand_path = os.path.join(folder, cand)
                    if not os.path.exists(cand_path):
                        out_name, out_path = cand, cand_path
                        break
                    k += 1

            # ---- metadata to embed ----
            # Default: this run's workflow (standard ComfyUI behavior, keeps the
            # output drag-and-droppable). Preserve mode: copy the source file's
            # embedded prompt/workflow verbatim instead; if the source has none,
            # nothing is embedded.
            if preserve_meta:
                pr_raw = wf_raw = None
                src_for_meta = meta.get("source_path") or src_i
                if src_for_meta and os.path.isfile(src_for_meta):
                    emb = mw.read_embedded(src_for_meta)
                    pr_raw, wf_raw = emb.get("prompt_raw"), emb.get("workflow_raw")
                extra = {}
            else:
                pr_raw = json.dumps(prompt) if isinstance(prompt, dict) else None
                extra = extra_pnginfo if isinstance(extra_pnginfo, dict) else {}
                wf = extra.get("workflow")
                wf_raw = json.dumps(wf) if wf else None

            pnginfo = exif_bytes = None
            if fmt == "png":
                if pr_raw or wf_raw or extra:
                    pnginfo = PngInfo()
                    if pr_raw:
                        pnginfo.add_text("prompt", pr_raw)
                    if preserve_meta:
                        if wf_raw:
                            pnginfo.add_text("workflow", wf_raw)
                    else:
                        for k, v in extra.items():
                            pnginfo.add_text(k, json.dumps(v))
            elif pr_raw or wf_raw:
                exif = Image.Exif()
                if wf_raw:
                    exif[0x010F] = "workflow:" + wf_raw   # Make — matches ComfyUI webp convention
                if pr_raw:
                    exif[0x0110] = "prompt:" + pr_raw     # Model
                exif_bytes = exif.tobytes()

            # ---- save ----
            exif_kw = {"exif": exif_bytes} if exif_bytes else {}
            if fmt == "png":
                cropped.save(out_path, format="PNG", optimize=optimize, pnginfo=pnginfo)
            elif fmt == "jpg":
                if cropped.mode != "RGB":
                    cropped = cropped.convert("RGB")
                cropped.save(out_path, format="JPEG", quality=quality, optimize=optimize,
                             subsampling=0, **exif_kw)
            else:
                cropped.save(out_path, format="WEBP", quality=quality,
                             method=6 if optimize else 4, lossless=lossless_webp,
                             **exif_kw)

            saved_full.append(os.path.abspath(out_path))
            saved_names.append(os.path.basename(out_path))
            cropped_batches.append(self._pil_to_tensor(cropped))

        if cropped_batches:
            max_w = max(t.shape[2] for t in cropped_batches)
            max_h = max(t.shape[1] for t in cropped_batches)
            if any(t.shape[1] != max_h or t.shape[2] != max_w for t in cropped_batches):
                padded = []
                for t in cropped_batches:
                    im = Image.fromarray((t[0].numpy() * 255).astype(np.uint8))
                    padded.append(self._pil_to_tensor(scs.pad_to(im, max_w, max_h)))
                cropped_batches = padded
            cropped_images = torch.cat(cropped_batches, dim=0)
        else:
            cropped_images = torch.zeros((1, height, width, 3), dtype=torch.float32)

        # With folder wildcards a batch can span multiple folders; the
        # saved_folder output lists each unique folder, one per line.
        if not folders_used:
            folders_used.append(self._ensure_folder(mw.resolve_folder(folder_pattern, live_fields)))
        # The ui block drives the panel's status line and the JS auto-advance
        # hook (onExecuted only fires for nodes that return ui data).
        return {
            "ui": {"saved_files": saved_names, "saved_folders": folders_used,
                   "saved_count": [len(saved_names)]},
            "result": ("\n".join(saved_full), "\n".join(saved_names),
                       "\n".join(folders_used), cropped_images),
        }


NODE_CLASS_MAPPINGS        = {"SaveImageSmart": SaveImageSmart}
NODE_DISPLAY_NAME_MAPPINGS = {"SaveImageSmart": "Save Image Smart [umbrae]"}
