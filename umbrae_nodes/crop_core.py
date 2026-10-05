# crop_core.py — Umbrae
#
# Single source of truth for the crop pipeline, shared by UmbraeSimpleCrop and
# UmbraeTrainingPrep so the two nodes manipulate images identically. The nodes
# are thin: they parse ui_state, call process(), and (for Training Prep) save.
#
# Pipeline per detection:  bbox -> shape to aspect -> grow to minimum size ->
# padding % -> crop rect -> resize (shared scale module).
#
# A "detection" is {bbox:(x1,y1,x2,y2)|None, mask:'L' PIL|None, label:str|None}.
# Region (boxes/SEGS) and Region-alternate (mask/SEGS) both parse to detections;
# the flatten/extract/merge controls decide how they collapse into crops.

import os, re
import numpy as np
import torch
from PIL import Image

from . import scale_crop_shared as scs


# ── mask tensor <-> PIL ───────────────────────────────────────────────────────
def mask_to_pil(m):
    """MASK tensor ([H,W] / [B,H,W] / [B,1,H,W], 0..1) -> first plane as 'L'."""
    if m is None:
        return None
    t = m
    if hasattr(t, "dim"):
        while t.dim() > 2:
            t = t[0]
    a = (t.cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
    return Image.fromarray(a, mode="L")


def pil_to_mask(pil):
    """'L' PIL -> MASK tensor [1,H,W] float 0..1."""
    a = np.array(pil.convert("L")).astype(np.float32) / 255.0
    return torch.from_numpy(a).unsqueeze(0)


def blank_mask(h, w):
    return torch.zeros((1, max(1, int(h)), max(1, int(w))), dtype=torch.float32)


def or_combine(masks):
    """Pixel-max (logical OR) of same-size 'L' PILs. None entries ignored."""
    masks = [m for m in masks if m is not None]
    if not masks:
        return None
    if len(masks) == 1:
        return masks[0].convert("L")
    base = np.array(masks[0].convert("L")).astype(np.uint8)
    for m in masks[1:]:
        mm = np.array(m.convert("L")).astype(np.uint8)
        if mm.shape != base.shape:
            mm = np.array(m.convert("L").resize((base.shape[1], base.shape[0]),
                                                 Image.NEAREST)).astype(np.uint8)
        base = np.maximum(base, mm)
    return Image.fromarray(base, mode="L")


def mask_bbox(pil):
    """Bounding box of non-zero pixels in an 'L' mask, or None if empty."""
    a = np.array(pil.convert("L"))
    ys, xs = np.where(a > 0)
    if xs.size == 0:
        return None
    return (float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1))


# ── SEGS helpers ──────────────────────────────────────────────────────────────
def _segs_dims(region):
    """Impact-Pack SEGS header is (h, w). Return (h, w) or None."""
    try:
        hdr = region[0]
        if isinstance(hdr, (tuple, list)) and len(hdr) >= 2:
            return int(hdr[0]), int(hdr[1])
    except Exception:
        pass
    return None


def _seg_mask_full(seg, H, W):
    """Composite a SEG's cropped_mask onto a full HxW canvas at its crop_region,
    so it aligns with the full image and can flow through the same crop+resize."""
    cm = getattr(seg, "cropped_mask", None)
    if cm is None:
        return None
    a = np.asarray(cm)
    while a.ndim > 2:
        a = a[0]
    a = a.astype(np.float32)
    if a.size and a.max() <= 1.0 + 1e-6:
        a = a * 255.0
    a = a.clip(0, 255).astype(np.uint8)

    cr = getattr(seg, "crop_region", None) or getattr(seg, "bbox", None)
    if not cr or len(cr) < 4:
        return None
    x1, y1, x2, y2 = [int(round(float(v))) for v in cr[:4]]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(W, x2), min(H, y2)
    rw, rh = max(0, x2 - x1), max(0, y2 - y1)
    if rw == 0 or rh == 0:
        return None
    if (a.shape[1], a.shape[0]) != (rw, rh):
        a = np.array(Image.fromarray(a, mode="L").resize((rw, rh), Image.NEAREST))
    canvas = np.zeros((H, W), dtype=np.uint8)
    canvas[y1:y2, x1:x2] = a
    return Image.fromarray(canvas, mode="L")


def _is_segs(region):
    return (isinstance(region, (tuple, list)) and len(region) == 2
            and isinstance(region[1], (list, tuple))
            and all(hasattr(s, "bbox") for s in region[1]))


# ── detection parsing ─────────────────────────────────────────────────────────
def parse_detections(region, extract="both"):
    """Decompose any region source into a list of detections. `extract` is one of
    'both' / 'bbox' / 'mask' and prunes what each detection carries.
    Sources handled: SEGS (box+mask+label per seg), bbox tensors/lists/dicts
    (box only), MASK tensor (mask only; box derived from coverage on demand)."""
    want_bbox = extract in ("both", "bbox")
    want_mask = extract in ("both", "mask")
    dets = []

    if region is None:
        return dets

    # MASK tensor (Region alternate fed a plain mask): one full-image detection.
    if isinstance(region, torch.Tensor) and region.dim() >= 2 and region.shape[-1] != 4:
        # Heuristic: a 4-wide last dim is bbox(es); otherwise treat as mask.
        if region.dim() == 2 or (region.dim() >= 3 and region.shape[-1] not in (4,)):
            # iterate batch of masks
            t = region
            planes = [t] if t.dim() == 2 else [t[i] for i in range(t.shape[0])]
            for p in planes:
                mp = mask_to_pil(p) if want_mask else None
                bb = mask_bbox(mask_to_pil(p)) if want_bbox else None
                if mp is not None or bb is not None:
                    dets.append({"bbox": bb, "mask": mp, "label": None})
            return dets

    # SEGS
    if _is_segs(region):
        dims = _segs_dims(region) or (None, None)
        H, W = dims
        for seg in region[1]:
            b = getattr(seg, "bbox", None)
            bbox = tuple(float(v) for v in b[:4]) if (want_bbox and b and len(b) >= 4) else None
            mp = None
            if want_mask and H and W:
                mp = _seg_mask_full(seg, H, W)
            label = getattr(seg, "label", None)
            if isinstance(label, (list, tuple)):
                label = label[0] if label else None
            dets.append({"bbox": bbox, "mask": mp,
                         "label": str(label) if label is not None else None})
        return dets

    # Everything else: boxes only (reuse the proven box parser).
    if want_bbox:
        for b in _parse_boxes(region):
            dets.append({"bbox": b, "mask": None, "label": None})
    return dets


def _parse_boxes(bb):
    """Return list of (x1,y1,x2,y2) floats from whatever a detector gives us.
    Handles raw tensor (N,4), list of dicts (native SAM3), dict with boxes key,
    KJ {x,y,w,h}, flat list, and SEGS bbox."""
    if bb is None:
        return []
    if isinstance(bb, torch.Tensor):
        t = bb.cpu().float()
        if t.dim() == 1:
            return [tuple(t.tolist()[:4])] if t.shape[0] >= 4 else []
        while t.dim() > 2:
            t = t[0]
        if t.shape[-1] < 4:
            return []
        return [tuple(t[i].tolist()[:4]) for i in range(t.shape[0])]
    if isinstance(bb, dict):
        for key in ("boxes", "bboxes", "input_boxes", "bbox", "bounding_boxes"):
            if key in bb:
                return _parse_boxes(bb[key])
        if "x" in bb and "y" in bb:
            x, y = float(bb["x"]), float(bb["y"])
            if "w" in bb and "h" in bb:
                return [(x, y, x + float(bb["w"]), y + float(bb["h"]))]
            if "width" in bb and "height" in bb:
                return [(x, y, x + float(bb["width"]), y + float(bb["height"]))]
            if "x2" in bb and "y2" in bb:
                return [(x, y, float(bb["x2"]), float(bb["y2"]))]
        return []
    if isinstance(bb, (list, tuple)):
        if len(bb) == 0:
            return []
        first = bb[0]
        if isinstance(first, (int, float)):
            return [tuple(float(v) for v in bb[:4])] if len(bb) >= 4 else []
        if isinstance(first, dict):
            out = []
            for it in bb:
                out.extend(_parse_boxes(it))
            return out
        if isinstance(first, torch.Tensor):
            out = []
            for t in bb:
                out.extend(_parse_boxes(t))
            return out
        if isinstance(first, (list, tuple)):
            out = []
            for it in bb:
                out.extend(_parse_boxes(it))
            return out
        if hasattr(first, "bbox"):
            out = []
            for seg in bb:
                b = seg.bbox
                if isinstance(b, (list, tuple)) and len(b) >= 4:
                    out.append(tuple(float(v) for v in b[:4]))
            return out
    if isinstance(bb, tuple) and len(bb) == 2 and isinstance(bb[1], list):
        out = []
        for seg in bb[1]:
            if hasattr(seg, "bbox"):
                b = seg.bbox
                if isinstance(b, (list, tuple)) and len(b) >= 4:
                    out.append(tuple(float(v) for v in b[:4]))
        return out
    return []


# ── box merge ─────────────────────────────────────────────────────────────────
def merge_boxes(boxes, method="union"):
    """Collapse boxes to one. union = cover all; largest = biggest-area box."""
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    if len(boxes) == 1:
        return boxes[0]
    if method == "largest":
        return max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


# ── rect shaping: bbox -> aspect -> minimum size -> padding ───────────────────
def _aspect_target(box, source, state, iw, ih):
    """Target aspect ratio (w/h) for shape-to-aspect, by source."""
    if source == "image":
        return (iw / ih) if ih else 1.0
    if source == "user":
        rw = max(0.01, float(state.get("shape_ratio_w", 1.0)))
        rh = max(0.01, float(state.get("shape_ratio_h", 1.0)))
        return rw / rh
    # bbox's own
    bw, bh = (box[2] - box[0]), (box[3] - box[1])
    return (bw / bh) if bh else 1.0


def _grow_to_aspect(box, target_ar, iw, ih):
    """Expand the deficient axis (pull in surrounding source) to hit target_ar,
    centered on the box. Clamped to source; any shortfall is left for the crop to
    pad black. Never shrinks the box (we only ever add context)."""
    x1, y1, x2, y2 = box
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    bw, bh = max(1.0, x2 - x1), max(1.0, y2 - y1)
    cur_ar = bw / bh
    if cur_ar < target_ar:          # too tall -> widen
        bw = bh * target_ar
    else:                           # too wide -> heighten
        bh = bw / target_ar
    nx1, ny1 = cx - bw / 2.0, cy - bh / 2.0
    nx2, ny2 = cx + bw / 2.0, cy + bh / 2.0
    return _clamp_keep_size(nx1, ny1, nx2, ny2, iw, ih)


def _grow_to_min(box, min_edge, iw, ih):
    """Grow the rect from its center, keeping aspect, until its short edge reaches
    min_edge in native pixels (or as far as the source allows). Centered + clamped."""
    if min_edge <= 0:
        return box
    x1, y1, x2, y2 = box
    bw, bh = max(1.0, x2 - x1), max(1.0, y2 - y1)
    short = min(bw, bh)
    if short >= min_edge:
        return box
    s = min_edge / short
    cx, cy = (x1 + x2) / 2.0, (y1 + y2) / 2.0
    # Cap to source: never exceed the image, so the crop stays native (no black
    # pad). When the source can't supply min_edge, the resize stage upscales the
    # largest native window per direction (up = upscale, down = leave smaller).
    nw, nh = min(bw * s, float(iw)), min(bh * s, float(ih))
    return _clamp_keep_size(cx - nw / 2.0, cy - nh / 2.0,
                            cx + nw / 2.0, cy + nh / 2.0, iw, ih)


def _clamp_keep_size(x1, y1, x2, y2, iw, ih):
    """Shift the rect to sit inside the source where possible without shrinking;
    only clip (allowing later black-pad) when the rect is larger than the source."""
    w, h = x2 - x1, y2 - y1
    if w <= iw:
        if x1 < 0:   x1, x2 = 0.0, w
        if x2 > iw:  x1, x2 = iw - w, float(iw)
    if h <= ih:
        if y1 < 0:   y1, y2 = 0.0, h
        if y2 > ih:  y1, y2 = ih - h, float(ih)
    return (x1, y1, x2, y2)


def _add_padding(box, state, iw, ih):
    """Apply the padding control (percentage of box size, or pixels)."""
    pad = float(state.get("padding", 10.0))
    if pad == 0:
        return box
    x1, y1, x2, y2 = box
    if state.get("padding_unit", "percentage") == "percentage":
        px = (x2 - x1) * (pad / 100.0)
        py = (y2 - y1) * (pad / 100.0)
    else:
        px = py = pad
    return (max(0.0, x1 - px), max(0.0, y1 - py),
            min(float(iw), x2 + px), min(float(ih), y2 + py))


def build_rect(box, state, iw, ih):
    """bbox -> shape to aspect -> grow to minimum size -> padding -> final rect.
    `box` is the raw detector box; iw,ih are the source dimensions."""
    shape = state.get("shape_mode", "exact")      # exact | aspect
    if shape == "aspect":
        ar = _aspect_target(box, state.get("aspect_source", "bbox"), state, iw, ih)
        box = _grow_to_aspect(box, ar, iw, ih)

    # Minimum crop size: SMALLEST_EDGE feeds its target in here when enabled.
    if bool(state.get("min_crop_on", False)):
        min_edge = int(state.get("min_crop_size",
                                 state.get("target_size", 1024)))
        # Trigger measures the RAW bbox short edge (per locked design).
        raw_short = min(box[2] - box[0], box[3] - box[1])
        if raw_short < min_edge:
            box = _grow_to_min(box, min_edge, iw, ih)

    box = _add_padding(box, state, iw, ih)
    return box


# ── resize / anchor (shared scale module) ─────────────────────────────────────
def resize_params(state):
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


def compute_anchor(pil, state, bbox_override=None):
    """Anchor derived from IMAGE content (face/entropy/etc); computed once and
    reused for the paired mask so geometry matches exactly."""
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


def apply_resize(pil, state, anchor, interp=Image.LANCZOS):
    p = resize_params(state)
    return scs.apply_resize(pil, p["mode"], interp, p["direction"], p["width"], p["height"],
                             target_size=p["target_size"], target_mp=p["target_mp"],
                             fill=p["fill"], crop_on=p["crop_on"],
                             ratio_w=p["ratio_w"], ratio_h=p["ratio_h"], anchor=anchor)


def _mask_interp(state):
    return Image.NEAREST if state.get("mask_interpolation", "nearest") == "nearest" else Image.BILINEAR


# ── one crop (image + optional mask), shared geometry ─────────────────────────
def crop_one(pil_full, rect, mask_full, state, bbox_override=None):
    """Crop pil_full (and mask_full, if given) to `rect`, then resize both with
    one shared anchor. Returns (image_tensor[1,H,W,3], mask_tensor[1,H,W])."""
    iw, ih = pil_full.size
    rx1, ry1, rx2, ry2 = [int(round(v)) for v in rect]
    crop_box = (rx1, ry1, max(rx1 + 1, rx2), max(ry1 + 1, ry2))

    sub = pil_full.crop(crop_box)               # PIL pads OOB with black
    anchor = compute_anchor(sub, state, bbox_override)
    img = apply_resize(sub, state, anchor, Image.LANCZOS)
    out = torch.from_numpy(np.array(img.convert("RGB")).astype(np.float32) / 255.0).unsqueeze(0)

    if mask_full is not None:
        msub = mask_full.convert("L").crop(crop_box).convert("RGB")
        mres = apply_resize(msub, state, anchor, _mask_interp(state)).convert("L")
        mout = pil_to_mask(mres)
    else:
        mout = blank_mask(out.shape[1], out.shape[2])
    return out, mout


# ── top-level: parse, flatten/extract/merge, crop ─────────────────────────────
def process(image, region, alt, state, log=print):
    """Returns dict with:
      images : IMAGE tensor [N,H,W,3]   (N crops; padded to uniform if separate)
      masks  : MASK  tensor [N,H,W]     (socket form; OR-combined when 1 img/many)
      crops  : list of per-crop {image:[1..], mask:[1..], label:str|None}
    The crops list preserves per-detection masks+labels for per-file saving."""
    img_t = image[0]
    img_np = (img_t.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
    pil = Image.fromarray(img_np).convert("RGB")
    iw, ih = pil.size

    ex_r = state.get("extract_region", "both")
    ex_a = state.get("extract_alt", "both")
    fl_r = bool(state.get("flatten_region", True))
    fl_a = bool(state.get("flatten_alt", True))
    method = state.get("merge_method", "union")

    det_r = parse_detections(region, ex_r)
    det_a = parse_detections(alt, ex_a)

    def split(dets):
        return ([d["bbox"] for d in dets if d["bbox"]],
                [(d["mask"], d["label"]) for d in dets if d["mask"] is not None])

    bx_r, mk_r = split(det_r)
    bx_a, mk_a = split(det_a)

    # Per-input flatten of boxes.
    if fl_r and bx_r:
        bx_r = [merge_boxes(bx_r, method)]
    if fl_a and bx_a:
        bx_a = [merge_boxes(bx_a, method)]
    boxes = bx_r + bx_a

    # Per-input flatten of masks (OR-combine within each input when flattening).
    masks = list(mk_r) + list(mk_a)
    if fl_r and mk_r:
        masks = [(or_combine([m for m, _ in mk_r]), None)] + list(mk_a)
        if fl_a and mk_a:
            masks = [(or_combine([m for m, _ in mk_r]), None),
                     (or_combine([m for m, _ in mk_a]), None)]
    elif fl_a and mk_a:
        masks = list(mk_r) + [(or_combine([m for m, _ in mk_a]), None)]

    if not boxes:
        # No geometry anywhere -> crop the whole image; masks (if any) ride along.
        boxes = [(0.0, 0.0, float(iw), float(ih))]

    nB, nM = len(boxes), len(masks)

    # Pairing rules.
    crops = []
    if nB == 1:
        # One crop. All masks ride it; socket gets OR of them, files stay separate.
        rect = build_rect(boxes[0], state, iw, ih)
        if masks:
            for mp, label in masks:
                im, mo = crop_one(pil, rect, mp, state)
                crops.append({"image": im, "mask": mo, "label": label})
            # ensure at least the image exists even if a mask was None
            if not crops:
                im, mo = crop_one(pil, rect, None, state)
                crops.append({"image": im, "mask": mo, "label": None})
        else:
            im, mo = crop_one(pil, rect, None, state)
            crops.append({"image": im, "mask": mo, "label": None})
    else:
        # Multiple boxes. Pair masks by index when counts match; one shared mask
        # cuts per box; mismatch (both >1, unequal) -> error + flatten masks.
        if nM <= 1:
            shared = masks[0][0] if nM == 1 else None
            for b in boxes:
                rect = build_rect(b, state, iw, ih)
                im, mo = crop_one(pil, rect, shared, state)
                crops.append({"image": im, "mask": mo, "label": None})
        elif nM == nB:
            for b, (mp, label) in zip(boxes, masks):
                rect = build_rect(b, state, iw, ih)
                im, mo = crop_one(pil, rect, mp, state)
                crops.append({"image": im, "mask": mo, "label": label})
        else:
            log(f"[crop_core] ERROR: {nB} boxes vs {nM} masks can't be paired; "
                f"OR-combining masks to one and cutting it per box. Flatten one "
                f"input to control this.")
            shared = or_combine([m for m, _ in masks])
            for b in boxes:
                rect = build_rect(b, state, iw, ih)
                im, mo = crop_one(pil, rect, shared, state)
                crops.append({"image": im, "mask": mo, "label": None})

    images_t = _stack_uniform([c["image"] for c in crops])
    masks_t  = _socket_masks(crops)
    return {"images": images_t, "masks": masks_t, "crops": crops}


def _stack_uniform(img_list):
    """Stack [1,H,W,3] tensors into [N,H,W,3]; pad to the max H,W if they differ
    (separate crops are naturally different sizes)."""
    if not img_list:
        return torch.zeros((1, 1, 1, 3), dtype=torch.float32)
    if len(img_list) == 1:
        return img_list[0]
    H = max(t.shape[1] for t in img_list)
    W = max(t.shape[2] for t in img_list)
    out = []
    for t in img_list:
        h, w = t.shape[1], t.shape[2]
        if (h, w) != (H, W):
            canvas = torch.zeros((1, H, W, 3), dtype=t.dtype)
            canvas[:, :h, :w, :] = t
            t = canvas
        out.append(t)
    return torch.cat(out, dim=0)


def _socket_masks(crops):
    """Mask socket form. One image + many masks -> OR to one. Otherwise stack to
    match the image batch (padded)."""
    masks = [c["mask"] for c in crops]
    if not masks:
        return blank_mask(1, 1)
    if len(masks) == 1:
        return masks[0]
    H = max(m.shape[1] for m in masks)
    W = max(m.shape[2] for m in masks)
    padded = []
    for m in masks:
        h, w = m.shape[1], m.shape[2]
        if (h, w) != (H, W):
            canvas = torch.zeros((1, H, W), dtype=m.dtype)
            canvas[:, :h, :w] = m
            m = canvas
        padded.append(m)
    return torch.cat(padded, dim=0)
