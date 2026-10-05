# scale_crop_shared.py — UNP
#
# Single source of truth for resize/crop/anchor math, shared by
# LoadImagesUniformBatch, CropImageRegion, and SaveImageSmart so the three
# nodes behave identically given identical settings.
#
# Modes: OFF (pass-through), LARGEST_EDGE, SMALLEST_EDGE, MAX_MP, FIT_AND_PAD, CROP, FORCE_EXACT.
# CROP carries independent fill/crop booleans:
#   fill=True,  crop=True  -> cover-scale then crop overflow (fixed W,H output)
#   fill=True,  crop=False -> cover-scale only, no crop (output overflows target on one axis)
#   fill=False, crop=True  -> direct native-resolution crop at the target RATIO, no scaling
#   fill=False, crop=False -> scale to fit inside W,H, no bars, no crop (dynamic output size)
#
# Anchor (used whenever CROP actually crops): grid (9-point), face, entropy,
# xy (manual normalized offset), or an externally wired bbox override (always
# takes priority over whichever anchor_mode is selected).

import numpy as np
from PIL import Image


class AnyType(str):
    def __ne__(self, v): return False


ANYTYPE = AnyType("*")

RESIZE_MODES = ("OFF", "LARGEST_EDGE", "SMALLEST_EDGE", "MAX_MP", "FIT_AND_PAD", "CROP", "FORCE_EXACT")

GRID_POINTS = {
    "top-left": (0.0, 0.0), "top": (0.5, 0.0), "top-right": (1.0, 0.0),
    "left":     (0.0, 0.5), "center": (0.5, 0.5), "right":    (1.0, 0.5),
    "bottom-left": (0.0, 1.0), "bottom": (0.5, 1.0), "bottom-right": (1.0, 1.0),
}


# ── scale direction ──────────────────────────────────────────────────────────

def apply_direction(scale, direction):
    """down = never enlarge, up = never shrink, both = no cap."""
    if direction == "down":
        return min(scale, 1.0)
    if direction == "up":
        return max(scale, 1.0)
    return scale


def gcd(a, b):
    a, b = abs(int(a)), abs(int(b))
    while b:
        a, b = b, a % b
    return a or 1


# ── face / entropy detection (built-in, no extra model download) ───────────────

_face_cascade_front = None
_face_cascade_profile = None


def _get_face_cascade(profile=False):
    global _face_cascade_front, _face_cascade_profile
    try:
        import cv2
        if profile:
            if _face_cascade_profile is None:
                c = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_profileface.xml")
                _face_cascade_profile = c if not c.empty() else False
            return _face_cascade_profile
        if _face_cascade_front is None:
            c = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            _face_cascade_front = c if not c.empty() else False
        return _face_cascade_front
    except Exception as exc:
        print(f"[scale_crop_shared] Face detection unavailable ({exc}); falling back to center anchor.")
        return False


def detect_face_box(pil_im, use_profile=True, scale=0.6):
    """Largest detected face as (x, y, w, h) in ORIGINAL image pixel space, or None."""
    try:
        import cv2
        arr = cv2.cvtColor(np.array(pil_im.convert("RGB")), cv2.COLOR_RGB2BGR)
        ds_w = max(1, int(arr.shape[1] * scale))
        ds_h = max(1, int(arr.shape[0] * scale))
        arr_ds = cv2.resize(arr, (ds_w, ds_h), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(arr_ds, cv2.COLOR_BGR2GRAY)

        def scan(cascade):
            if not cascade:
                return []
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(36, 36))
            return [(x / scale, y / scale, w / scale, h / scale) for (x, y, w, h) in faces]

        faces = scan(_get_face_cascade(False))
        if use_profile and not faces:
            faces = scan(_get_face_cascade(True))
        if not faces:
            return None
        return max(faces, key=lambda f: f[2] * f[3])
    except Exception as exc:
        print(f"[scale_crop_shared] Face detection failed: {exc}")
        return None


def detect_entropy_center(pil_im, win_w, win_h, scale=0.5, stride_div=4):
    """(cx, cy) in ORIGINAL image pixel space — the window position with the
    highest edge-energy (Laplacian) content. CPU fallback when cv2 is unavailable."""
    arr = np.array(pil_im.convert("L"), dtype=np.float32)
    try:
        import cv2
        arr_ds = cv2.resize(arr, (max(1, int(arr.shape[1] * scale)), max(1, int(arr.shape[0] * scale))),
                             interpolation=cv2.INTER_AREA) if scale != 1.0 else arr
        energy = np.abs(cv2.Laplacian(arr_ds, ddepth=cv2.CV_32F))
    except Exception:
        im_ds = (Image.fromarray(arr.astype(np.uint8)).resize(
            (max(1, int(arr.shape[1] * scale)), max(1, int(arr.shape[0] * scale))), Image.BILINEAR)
            if scale != 1.0 else Image.fromarray(arr.astype(np.uint8)))
        arr_ds = np.array(im_ds, dtype=np.float32)
        kx = np.array([[1, 0, -1], [2, 0, -2], [1, 0, -1]], np.float32)
        ky = np.array([[1, 2, 1], [0, 0, 0], [-1, -2, -1]], np.float32)
        pad = np.pad(arr_ds, ((1, 1), (1, 1)), mode="edge")
        ex = np.zeros_like(arr_ds)
        ey = np.zeros_like(arr_ds)
        for y in range(arr_ds.shape[0]):
            for x in range(arr_ds.shape[1]):
                patch = pad[y:y + 3, x:x + 3]
                ex[y, x] = np.sum(patch * kx)
                ey[y, x] = np.sum(patch * ky)
        energy = np.abs(ex) + np.abs(ey)

    ih, iw = energy.shape
    w = max(1, int(win_w * scale))
    h = max(1, int(win_h * scale))
    integral = energy.cumsum(0).cumsum(1)
    stride = max(4, min(w, h) // stride_div)
    best, best_xy = -1, (iw // 2, ih // 2)
    for y in range(0, max(1, ih - h + 1), stride):
        y2 = y + h - 1
        for x in range(0, max(1, iw - w + 1), stride):
            x2 = x + w - 1
            s = integral[y2, x2]
            if x > 0: s -= integral[y2, x - 1]
            if y > 0: s -= integral[y - 1, x2]
            if x > 0 and y > 0: s += integral[y - 1, x - 1]
            if s > best:
                best, best_xy = s, (x + w // 2, y + h // 2)
    sc = scale or 1.0
    return (best_xy[0] / sc, best_xy[1] / sc)


# ── bbox override parsing ───────────────────────────────────────────────────

def parse_single_bbox(bb):
    """Center (x, y) from a single externally-supplied bbox, in whatever
    reasonable format it arrives as. Returns None if unparseable."""
    try:
        if bb is None:
            return None
        if hasattr(bb, "tolist"):
            bb = bb.tolist()
        while isinstance(bb, (list, tuple)) and len(bb) and isinstance(bb[0], (list, tuple)):
            bb = bb[0]
        if isinstance(bb, dict):
            x1, y1 = bb.get("x1", bb.get("x", 0)), bb.get("y1", bb.get("y", 0))
            x2, y2 = bb.get("x2", 0), bb.get("y2", 0)
        elif isinstance(bb, (list, tuple)) and len(bb) >= 4:
            x1, y1, x2, y2 = bb[:4]
        else:
            return None
        return (float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0
    except Exception:
        return None


def resolve_anchor(pil_im, anchor_mode, anchor_grid="center", anchor_xy=None,
                    bbox_override=None, advanced=None):
    """(cx, cy) in ORIGINAL image pixel space. Priority: bbox_override always
    wins; otherwise dispatches on anchor_mode (face / entropy / grid / xy),
    applying the same guard/rejection logic SaveImageSmart originally had
    (min/max face fraction, too-low rejection with fallback, headroom, top
    guard) so the Advanced section has real effect on every node, not just
    a stripped-down approximation.

    Note: headroom and the face-relative top guard are approximated against
    face/content height rather than the final crop window height (which
    isn't known yet at this point in the pipeline) — close in practice, not
    pixel-identical to the original SaveImageSmart math.
    """
    w, h = pil_im.size
    override = parse_single_bbox(bbox_override)
    if override is not None:
        return override

    advanced = advanced or {}
    mode = (anchor_mode or "center").lower()

    def apply_guards(cx, cy, ref_h):
        cy = cy + float(advanced.get("headroom", 0.0)) * ref_h
        guard_y = float(advanced.get("top_guard_pct", 0.0)) * h
        cy = max(cy, guard_y)
        return (cx, cy)

    if mode == "face":
        fb = detect_face_box(pil_im, use_profile=advanced.get("use_profile", True),
                              scale=advanced.get("det_scale", 0.6))
        if fb is not None:
            x, y, fw, fh = fb
            frac = max(fw / w, fh / h) if w and h else 0.0
            min_frac = float(advanced.get("min_face_frac", 0.0))
            max_frac = float(advanced.get("max_face_frac", 1.0))
            fy_center = y + fh / 2.0
            too_low = (advanced.get("reject_too_low_faces", True)
                       and fy_center > float(advanced.get("too_low_threshold_pct", 1.0)) * h)
            if min_frac <= frac <= max_frac and not too_low:
                cx = x + fw / 2.0
                cy = fy_center + float(advanced.get("torso_bias", 0.0)) * fh
                face_guard_y = y - fh * float(advanced.get("face_top_guard_pct", 0.0))
                cy = max(cy, face_guard_y)
                return apply_guards(cx, cy, fh)
        if advanced.get("fallback_if_no_face", "entropy") == "entropy":
            cx, cy = detect_entropy_center(pil_im, advanced.get("win_w", w * 0.5), advanced.get("win_h", h * 0.5),
                                            scale=advanced.get("ent_scale", 0.5),
                                            stride_div=advanced.get("ent_stride_div", 4))
            return apply_guards(cx, cy, h * 0.3)
        return apply_guards(w / 2.0, h / 2.0, h * 0.3)

    if mode == "entropy":
        cx, cy = detect_entropy_center(pil_im, advanced.get("win_w", w * 0.5), advanced.get("win_h", h * 0.5),
                                        scale=advanced.get("ent_scale", 0.5),
                                        stride_div=advanced.get("ent_stride_div", 4))
        return apply_guards(cx, cy, h * 0.3)

    if mode == "xy":
        fx, fy = anchor_xy if anchor_xy else (0.5, 0.5)
        return (fx * w, fy * h)

    fx, fy = GRID_POINTS.get(anchor_grid or "center", (0.5, 0.5))
    return (fx * w, fy * h)


# ── core resize / crop functions ───────────────────────────────────────────────

def _pad_canvas(im, W, H, keep_alpha=False):
    """Blank padding canvas. Default (keep_alpha=False) is the original black
    RGB canvas, so every existing caller is unchanged. keep_alpha=True with an
    RGBA image gives a fully transparent RGBA canvas instead, so the paste
    keeps the image's alpha and the padding itself is transparent (v0.8.1)."""
    if keep_alpha and im.mode == "RGBA":
        return Image.new("RGBA", (W, H), (0, 0, 0, 0))
    return Image.new("RGB", (W, H), 0)


def pad_to(im, W, H, keep_alpha=False):
    """Pad (no scaling) onto a W,H black canvas, centered. Used to make a
    batch of already-resized, dynamic-size images torch.cat-compatible.
    keep_alpha: see _pad_canvas."""
    if im.size == (W, H):
        return im
    canvas = _pad_canvas(im, W, H, keep_alpha)
    canvas.paste(im, ((W - im.width) // 2, (H - im.height) // 2))
    return canvas


def largest_edge(im, target, interp, direction):
    w, h = im.size
    if not w or not h:
        return im
    scale = apply_direction(target / max(w, h), direction)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    return im if abs(scale - 1.0) < 1e-9 else im.resize((nw, nh), interp)


def smallest_edge(im, target, interp, direction):
    """Mirror of largest_edge: scale so the SHORTEST edge meets `target`.
    With direction='up' this floors the short edge at target (training's
    'minimum size' preference); 'down' caps it; 'both' makes it exact."""
    w, h = im.size
    if not w or not h:
        return im
    scale = apply_direction(target / min(w, h), direction)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    return im if abs(scale - 1.0) < 1e-9 else im.resize((nw, nh), interp)


def max_mp(im, target_mp, interp, direction):
    w, h = im.size
    if not w or not h:
        return im
    target_px = max(0.01, float(target_mp)) * 1024 * 1024
    current_px = w * h
    scale = apply_direction((target_px / current_px) ** 0.5 if current_px else 1.0, direction)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    return im if abs(scale - 1.0) < 1e-9 else im.resize((nw, nh), interp)


def fit_no_pad(im, W, H, interp, direction):
    """Fill OFF + Crop OFF: scale to fit inside W,H preserving aspect, no
    bars, no crop. Dynamic output size."""
    w, h = im.size
    scale = apply_direction(min(W / w, H / h), direction)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    return im if abs(scale - 1.0) < 1e-9 else im.resize((nw, nh), interp)


def fit_pad(im, W, H, interp, direction, keep_alpha=False):
    """Fit inside W,H preserving aspect, pad to the exact box with black bars.
    keep_alpha: see _pad_canvas (transparent bars for an RGBA image)."""
    w, h = im.size
    scale = apply_direction(min(W / w, H / h), direction)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    canvas = _pad_canvas(im, W, H, keep_alpha)
    canvas.paste(im.resize((nw, nh), interp), ((W - nw) // 2, (H - nh) // 2))
    return canvas


def force_exact(im, W, H, interp, direction, keep_alpha=False):
    if direction == "down" and im.width <= W and im.height <= H:
        return fit_pad(im, W, H, interp, "down", keep_alpha)
    return im.resize((W, H), interp)


def cover_scale_only(im, W, H, interp, direction):
    """Fill ON + Crop OFF: scale to cover W,H, no crop. Output overflows the
    target box on one axis. Dynamic output size."""
    w, h = im.size
    scale = apply_direction(max(W / w, H / h), direction)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    return im if abs(scale - 1.0) < 1e-9 else im.resize((nw, nh), interp)


def crop_to_fill(im, W, H, interp, direction, anchor=None):
    """Fill ON + Crop ON: scale to cover, then crop the overflow centered on
    `anchor` (image-space x,y). Fixed W,H output."""
    w, h = im.size
    scale = apply_direction(max(W / w, H / h), direction)
    nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
    resized = im.resize((nw, nh), interp)
    ax, ay = anchor if anchor else (w / 2.0, h / 2.0)
    rax, ray = ax * scale, ay * scale
    x1 = max(0.0, min(rax - W / 2.0, max(0, nw - W)))
    y1 = max(0.0, min(ray - H / 2.0, max(0, nh - H)))
    x1, y1 = int(round(x1)), int(round(y1))
    return resized.crop((x1, y1, x1 + W, y1 + H))


def ratio_crop(im, ratio_w, ratio_h, direction, anchor=None):
    """Fill OFF + Crop ON: direct native-resolution crop at a target aspect
    ratio, no scaling at all. Output size is whatever that crop naturally is.
    `direction` is accepted for interface symmetry but has no effect here —
    there's no scale factor to cap, only a crop."""
    w, h = im.size
    ratio_w, ratio_h = max(0.01, float(ratio_w)), max(0.01, float(ratio_h))
    target_ar = ratio_w / ratio_h
    src_ar = w / h if h else 1.0

    if src_ar > target_ar:
        cw, ch = h * target_ar, h
    else:
        cw, ch = w, w / target_ar
    cw, ch = min(cw, w), min(ch, h)

    ax, ay = anchor if anchor else (w / 2.0, h / 2.0)
    x1 = max(0.0, min(ax - cw / 2.0, w - cw))
    y1 = max(0.0, min(ay - ch / 2.0, h - ch))
    x1, y1, cw, ch = int(round(x1)), int(round(y1)), int(round(cw)), int(round(ch))
    cw, ch = max(1, cw), max(1, ch)
    return im.crop((x1, y1, x1 + cw, y1 + ch))


# ── unified dispatch ──────────────────────────────────────────────────────────

def crop_is_fixed_size(fill, crop):
    """True when the CROP mode's fill/crop combination always produces the
    exact configured W,H (only fill=True,crop=True does)."""
    return bool(fill) and bool(crop)


def mode_is_dynamic_size(mode, fill=True, crop=True):
    """True when this mode/combination produces per-image-varying output
    dimensions (so callers can't naively torch.cat without padding first)."""
    mode = (mode or "LARGEST_EDGE").upper()
    if mode in ("OFF", "LARGEST_EDGE", "SMALLEST_EDGE", "MAX_MP"):
        return True
    if mode == "CROP":
        return not crop_is_fixed_size(fill, crop)
    return False  # FIT_AND_PAD, FORCE_EXACT


def apply_resize(im, mode, interp, direction, W, H, target_size=None, target_mp=None,
                  fill=True, crop_on=True, ratio_w=1, ratio_h=1, anchor=None,
                  keep_alpha=False):
    """Single entry point covering every mode. W,H are the configured target
    box for box-based modes; target_size/target_mp are used by the
    aspect-preserving modes. Returns the processed PIL image.

    keep_alpha (default False = unchanged behaviour): when True and `im` is
    RGBA, the padding modes keep alpha and pad with transparency. The resize
    itself is mode-agnostic - Pillow resizes RGBA through premultiplied alpha."""
    mode = (mode or "LARGEST_EDGE").upper()
    if mode == "OFF":
        return im
    if mode == "LARGEST_EDGE":
        return largest_edge(im, target_size or 1024, interp, direction)
    if mode == "SMALLEST_EDGE":
        return smallest_edge(im, target_size or 1024, interp, direction)
    if mode == "MAX_MP":
        return max_mp(im, target_mp or 1.0, interp, direction)
    if mode == "FIT_AND_PAD":
        return fit_pad(im, W, H, interp, direction, keep_alpha)
    if mode == "FORCE_EXACT":
        return force_exact(im, W, H, interp, direction, keep_alpha)
    if mode == "CROP":
        if fill and crop_on:
            return crop_to_fill(im, W, H, interp, direction, anchor)
        if fill and not crop_on:
            return cover_scale_only(im, W, H, interp, direction)
        if not fill and crop_on:
            return ratio_crop(im, ratio_w, ratio_h, direction, anchor)
        return fit_no_pad(im, W, H, interp, direction)
    return im
