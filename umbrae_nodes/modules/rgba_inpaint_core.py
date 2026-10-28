# rgba_inpaint_core.py — umbrae_nodes v0.8.1
#
# RGBA-native inpaint crop / stitch core for "inpaint crop rgba [umbrae]" and
# "inpaint stitch rgba [umbrae]" (rgba_inpaint_nodes.py).
#
# Derived from ComfyUI-Pixaroma's nodes/_inpaint_helpers.py (crop region math,
# mask preprocessing, seam feathering, color match). The crop/stitch paths are
# rewritten here so the image stays RGBA end to end:
#   * crop_info carries the full RGBA original (an RGB input gets alpha = 1)
#   * the crop is resized through premultiplied alpha (no hidden-color bleed)
#   * the model-facing crop is offered both flattened over a matte (RGB) and as
#     RGBA
#   * the stitch REPLACES the original inside the coverage area, alpha
#     included (premultiplied lerp), so generated transparency is honoured.
#     With both alphas = 1 this is exactly Pixaroma's RGB lerp.
#
# ---------------------------------------------------------------------------
# Portions copyright (c) 2026 pixaroma, used under the MIT License:
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
# ---------------------------------------------------------------------------

import numpy as np
import torch
from PIL import Image, ImageFilter

try:
    from scipy import ndimage as _ndimage  # optional, for true hole fill / distance
    _HAS_SCIPY = True
except Exception:
    _ndimage = None
    _HAS_SCIPY = False

# A scipy built against numpy 1.x can import fine and then fail inside a call
# under numpy 2. Every scipy call is guarded at call time and falls back to the
# PIL/numpy path; the failure latches for the session (one warning, not one
# per mask).
_SCIPY_DEAD = False

# Own connection type, deliberately NOT Pixaroma's "PIXAROMA_CROP_INFO": the
# two pairs must not be cross-wired (Pixaroma's stitch flattens alpha).
UMBRAE_RGBA_CROP_INFO = "UMBRAE_RGBA_CROP_INFO"

MATTES = {
    "black": (0.0, 0.0, 0.0),
    "white": (1.0, 1.0, 1.0),
    "gray": (0.5, 0.5, 0.5),
}

_RESAMPLE = {
    "lanczos": Image.LANCZOS,
    "bicubic": Image.BICUBIC,
    "bilinear": Image.BILINEAR,
    "nearest": Image.NEAREST,
}

DEFAULTS = {
    "size_mode": "keep",        # keep | force | free
    "target": 1024,
    "target_w": 1024,
    "target_h": 1024,
    "multiple": 8,
    "context_px": 24,
    "context_pct": 10.0,
    "mask_grow": 4,
    "mask_blur": 4,
    "blend": 16,
    "invert_mask": False,
    "fill_holes": True,
    "min_size": 256,
    "max_size": 2048,
    "resample": "lanczos",
    "allow_upscale": True,
}


# ─────────────────────────────────────────────────────────────────────────────
# scipy guards

def _scipy_ok():
    return _HAS_SCIPY and _ndimage is not None and not _SCIPY_DEAD


def _scipy_failed(where, err):
    global _SCIPY_DEAD
    if not _SCIPY_DEAD:
        _SCIPY_DEAD = True
        print(
            f"[umbrae rgba inpaint] scipy is installed but unusable here - "
            f"{type(err).__name__}: {err} (raised from {where}). Using the built-in "
            f"mask code for the rest of this session; results are near-identical."
        )


def _scipy_call(name, *args, **kwargs):
    """Run ONE scipy call -> (True, result) or (False, None) after latching."""
    if not _scipy_ok():
        return False, None
    try:
        return True, getattr(_ndimage, name)(*args, **kwargs)
    except Exception as e:
        _scipy_failed("ndimage." + name, e)
        return False, None


# ─────────────────────────────────────────────────────────────────────────────
# small utils

def _round_mult(v, m):
    m = max(1, int(m))
    return int(max(m, round(float(v) / m) * m))


def _clampi(v, lo, hi):
    return int(max(lo, min(hi, int(round(v)))))


def merge_params(p):
    """Fill any missing keys from DEFAULTS and coerce types."""
    out = dict(DEFAULTS)
    if isinstance(p, dict):
        out.update({k: p[k] for k in p if k in DEFAULTS})
    out["size_mode"] = str(out["size_mode"]).lower()
    if out["size_mode"] not in ("keep", "force", "free"):
        out["size_mode"] = "keep"
    out["resample"] = str(out["resample"]).lower()
    if out["resample"] not in _RESAMPLE:
        out["resample"] = "lanczos"
    for k in ("target", "target_w", "target_h", "multiple", "context_px",
              "mask_grow", "mask_blur", "blend", "min_size", "max_size"):
        out[k] = int(round(float(out[k])))
    out["context_pct"] = float(out["context_pct"])
    out["fill_holes"] = bool(out["fill_holes"])
    out["allow_upscale"] = bool(out["allow_upscale"])
    out["invert_mask"] = bool(out["invert_mask"])
    out["multiple"] = max(1, out["multiple"])
    out["min_size"] = max(8, out["min_size"])
    out["max_size"] = max(out["min_size"], out["max_size"])
    return out


def matte_rgb(name):
    return MATTES.get(str(name).lower(), MATTES["black"])


# ─────────────────────────────────────────────────────────────────────────────
# channel helpers (BHWC float tensors)

def to_rgba(t):
    """Any BHWC image -> RGBA. 3 ch gets alpha = 1, 1 ch is greyscale, 2 ch is
    grey + alpha, 5+ ch keeps the first four. Fresh tensor, input untouched."""
    c = int(t.shape[-1])
    if c == 4:
        return t.clone()
    if c == 3:
        return torch.cat([t, torch.ones_like(t[..., :1])], dim=-1)
    if c == 1:
        return torch.cat([t.repeat(1, 1, 1, 3), torch.ones_like(t)], dim=-1)
    if c == 2:
        return torch.cat([t[..., :1].repeat(1, 1, 1, 3), t[..., 1:2]], dim=-1)
    return t[..., :4].clone()


def flatten_rgba(t, matte):
    """RGBA -> RGB composited over a solid matte colour (straight alpha)."""
    a = t[..., 3:4].clamp(0, 1)
    m = torch.tensor(matte, dtype=t.dtype, device=t.device).view(1, 1, 1, 3)
    return (t[..., :3] * a + m * (1.0 - a)).clamp(0, 1)


# ─────────────────────────────────────────────────────────────────────────────
# mask helpers (numpy float HxW, 1 = the area to inpaint)

def mask_to_np(mask, h, w):
    """ComfyUI MASK ([1,H,W] / [H,W]) -> float HxW numpy 0..1, resized to (h, w)
    with NEAREST if needed. None -> zeros."""
    if mask is None:
        return np.zeros((h, w), dtype=np.float32)
    m = mask
    if isinstance(m, torch.Tensor):
        if m.dim() == 4:
            m = m[:, 0] if m.shape[1] == 1 else m[..., 0]
        if m.dim() == 3:
            m = m[0]
        m = m.detach().cpu().float().clamp(0, 1).numpy()
    m = np.asarray(m, dtype=np.float32)
    if m.ndim != 2:
        return np.zeros((h, w), dtype=np.float32)
    if m.shape != (h, w):
        pim = Image.fromarray((np.clip(m, 0, 1) * 255).astype(np.uint8), "L")
        pim = pim.resize((w, h), Image.NEAREST)
        m = np.asarray(pim, dtype=np.float32) / 255.0
    return np.clip(m, 0.0, 1.0)


def _max1d(a, k):
    """1D max filter along axis 1 (odd window k, edge-padded)."""
    r = k // 2
    ap = np.pad(a, ((0, 0), (r, r)), mode="edge")
    win = np.lib.stride_tricks.sliding_window_view(ap, k, axis=1)
    return win.max(axis=2)


def _dilate(m_bool, px):
    if px <= 0:
        return m_bool
    k = 2 * int(px) + 1
    ok, filtered = _scipy_call("maximum_filter", m_bool, size=k)
    if ok:
        return filtered > 0
    a = m_bool.astype(np.uint8)
    a = _max1d(a, k)
    a = _max1d(np.ascontiguousarray(a.T), k).T
    return a > 0


def fill_holes(m_bool):
    """Fill only SMALL enclosed holes (specks / gaps), never a subject-sized
    hole (that would collapse a cut-out mask to solid)."""
    ok, filled = _scipy_call("binary_fill_holes", m_bool)
    if ok:
        try:
            added = filled & ~m_bool
            if not added.any():
                return filled
            H, W = m_bool.shape
            limit = max(256, int(0.005 * H * W))
            ok2, labelled = _scipy_call("label", added)
            if ok2:
                lbl = labelled[0]
                sizes = np.bincount(lbl.ravel())
                small = np.where(sizes <= limit)[0]
                small = small[small != 0]
                return m_bool | np.isin(lbl, small)
        except Exception:
            pass  # our numpy failed, not scipy - fall back for this mask only
    pim = Image.fromarray((m_bool * 255).astype(np.uint8), "L")
    k = 9
    pim = pim.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MinFilter(k))
    return np.asarray(pim, dtype=np.uint8) > 127


def gaussian_blur_np(m, px):
    if px <= 0:
        return m
    pim = Image.fromarray((np.clip(m, 0, 1) * 255).astype(np.uint8), "L")
    pim = pim.filter(ImageFilter.GaussianBlur(radius=float(px)))
    return np.asarray(pim, dtype=np.float32) / 255.0


def preprocess_mask(m, p):
    """fill-holes + grow -> binary float mask (bbox + carried in crop_info)."""
    mb = m > 0.5
    if p["fill_holes"]:
        mb = fill_holes(mb)
    if p["mask_grow"] > 0:
        mb = _dilate(mb, p["mask_grow"])
    return mb.astype(np.float32)


def mask_bbox(m_bool):
    ys, xs = np.where(m_bool)
    if xs.size == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


# ─────────────────────────────────────────────────────────────────────────────
# region geometry (identical to Pixaroma's compute_region)

def compute_region(bbox, W, H, p):
    """bbox (x0,y0,x1,y1) or None (whole image) -> {rx, ry, rw, rh, out_w, out_h}."""
    p = merge_params(p)
    W = int(W); H = int(H)
    if bbox is None:
        x0, y0, x1, y1 = 0, 0, W, H
    else:
        x0, y0, x1, y1 = bbox
    bw = max(1.0, float(x1 - x0))
    bh = max(1.0, float(y1 - y0))
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0

    # context: max(context_px, blend) each side + context_pct of the bbox, so
    # the seam feather always has room to reach 0 inside the crop.
    ctx = max(p["context_px"], p["blend"])
    rw = bw + 2.0 * ctx + bw * p["context_pct"] / 100.0
    rh = bh + 2.0 * ctx + bh * p["context_pct"] / 100.0

    mode = p["size_mode"]
    mult = p["multiple"]

    tw = th = 0
    if mode == "force":
        tw = max(mult, _round_mult(p["target_w"], mult))
        th = max(mult, _round_mult(p["target_h"], mult))
        target_aspect = tw / float(th)
        if rw / rh < target_aspect:
            rw = rh * target_aspect
        else:
            rh = rw / target_aspect

    rw_i = max(1, min(int(round(rw)), W))
    rh_i = max(1, min(int(round(rh)), H))
    if mode == "force":
        aspect = tw / float(th)
        if rw_i > rh_i * aspect:
            rw_i = max(1, int(round(rh_i * aspect)))
        else:
            rh_i = max(1, int(round(rw_i / aspect)))
    rx = _clampi(cx - rw_i / 2.0, 0, W - rw_i)
    ry = _clampi(cy - rh_i / 2.0, 0, H - rh_i)

    if mode == "force":
        out_w, out_h = tw, th
    elif mode == "free":
        ow, oh = float(rw_i), float(rh_i)
        big = max(ow, oh)
        if big > p["max_size"]:
            k = p["max_size"] / big
            ow *= k; oh *= k
        out_w = _round_mult(ow, mult)
        out_h = _round_mult(oh, mult)
    else:  # keep
        long_side = max(rw_i, rh_i)
        s = p["target"] / long_side if long_side > 0 else 1.0
        if not p["allow_upscale"]:
            s = min(s, 1.0)
        ow = rw_i * s
        oh = rh_i * s
        small = min(ow, oh)
        if small < p["min_size"]:
            k = p["min_size"] / small
            ow *= k; oh *= k
        big = max(ow, oh)
        if big > p["max_size"]:
            k = p["max_size"] / big
            ow *= k; oh *= k
        out_w = _round_mult(ow, mult)
        out_h = _round_mult(oh, mult)

    out_w = max(mult, int(out_w))
    out_h = max(mult, int(out_h))
    return {"rx": rx, "ry": ry, "rw": rw_i, "rh": rh_i,
            "out_w": out_w, "out_h": out_h}


# ─────────────────────────────────────────────────────────────────────────────
# resize

def resize_rgba_tensor(t, w, h, resample="lanczos"):
    """BHWC RGBA float 0..1 resize via PIL per frame. Pillow resizes RGBA
    through premultiplied alpha (all filters except NEAREST), so colour hidden
    under transparent pixels cannot bleed into visible edges. Returns the input
    unchanged when the size already matches (identity stays pixel-exact).
    NOTE: like the original, this round-trips through 8-bit."""
    if int(w) == int(t.shape[2]) and int(h) == int(t.shape[1]):
        return t
    filt = _RESAMPLE.get(resample, Image.LANCZOS)
    frames = []
    for i in range(int(t.shape[0])):
        arr = (t[i].clamp(0, 1).cpu().numpy() * 255.0 + 0.5).astype(np.uint8)
        pim = Image.fromarray(arr, "RGBA").resize((int(w), int(h)), filt)
        frames.append(np.asarray(pim, dtype=np.float32) / 255.0)
    return torch.from_numpy(np.stack(frames, 0))


def resize_mask_np(m, w, h, resample="bilinear"):
    if int(w) == int(m.shape[1]) and int(h) == int(m.shape[0]):
        return np.clip(m, 0, 1).astype(np.float32)
    filt = _RESAMPLE.get(resample, Image.BILINEAR)
    pim = Image.fromarray((np.clip(m, 0, 1) * 255).astype(np.uint8), "L")
    pim = pim.resize((int(w), int(h)), filt)
    return np.asarray(pim, dtype=np.float32) / 255.0


# ─────────────────────────────────────────────────────────────────────────────
# CROP

def apply_rgba_crop(image, mask, p, matte="black"):
    """image [B,H,W,C] (any of 1-4+ channels), mask [1,H,W] | None.

    Returns (crop_rgb [B,oh,ow,3], crop_rgba [B,oh,ow,4], out_mask [1,oh,ow],
    crop_info, out_w, out_h). crop_info carries the full RGBA original and the
    full-frame processed mask for the stitch."""
    p = merge_params(p)
    rgba = to_rgba(image)
    B, H, W = int(rgba.shape[0]), int(rgba.shape[1]), int(rgba.shape[2])

    raw = mask_to_np(mask, H, W)
    if p["invert_mask"] and mask is not None:
        raw = 1.0 - raw
    proc = preprocess_mask(raw, p)            # binary core for the bbox
    bbox = mask_bbox(proc > 0.5)
    softm = np.maximum(raw, proc)             # keep the soft painted rim
    region = compute_region(bbox, W, H, p)
    rx, ry, rw, rh = region["rx"], region["ry"], region["rw"], region["rh"]
    out_w, out_h = region["out_w"], region["out_h"]

    crop = rgba[:, ry:ry + rh, rx:rx + rw, :].contiguous()
    crop_rgba = resize_rgba_tensor(crop, out_w, out_h, p["resample"]).to(image.device, image.dtype)
    crop_rgb = flatten_rgba(crop_rgba, matte_rgb(matte)).contiguous()

    # NEAREST mask resize, then the mask_blur Gaussian is the only softening.
    mreg = softm[ry:ry + rh, rx:rx + rw]
    mout = resize_mask_np(mreg, out_w, out_h, "nearest")
    mout = gaussian_blur_np(mout, p["mask_blur"])
    out_mask = torch.from_numpy(np.clip(mout, 0, 1)[None, ...].astype(np.float32)).to(image.device)

    full_mask = torch.from_numpy(softm[None, ...].astype(np.float32)).to(image.device)
    crop_info = {
        "image": rgba, "mask": full_mask,
        "x": rx, "y": ry, "w": rw, "h": rh,
        "orig_w": W, "orig_h": H,
        "matte": str(matte),
    }
    return crop_rgb, crop_rgba, out_mask, crop_info, out_w, out_h


# ─────────────────────────────────────────────────────────────────────────────
# STITCH helpers

def _feather_alpha(alpha, feather):
    """Ramp a [ch,cw] coverage to 0 at the rectangle edge over `feather` px.
    Capped at ~half the smaller side so the interior stays fully opaque."""
    k = int(feather)
    if k <= 0:
        return alpha
    ch, cw = int(alpha.shape[-2]), int(alpha.shape[-1])
    k = min(k, max(1, (min(ch, cw) - 1) // 2))
    ys = torch.arange(ch, dtype=torch.float32).view(ch, 1)
    xs = torch.arange(cw, dtype=torch.float32).view(1, cw)
    dist = torch.minimum(torch.minimum(ys, (ch - 1) - ys),
                         torch.minimum(xs, (cw - 1) - xs))
    ramp = (dist / float(k)).clamp(0.0, 1.0)
    return (alpha * ramp).clamp(0.0, 1.0)


def _blur_alpha(alpha, blend):
    """OUTWARD-only feather of a mask edge: 1.0 inside and at the edge, ramping
    to 0 over `blend` px outside (smoothstep on a signed distance)."""
    k = int(blend)
    if k <= 0:
        return alpha
    a_np = np.clip(alpha.detach().cpu().numpy(), 0.0, 1.0)
    mb = a_np > 0.5
    if not mb.any() or mb.all():
        return torch.from_numpy(a_np.astype(np.float32))
    soft = None
    ok_in, d_in = _scipy_call("distance_transform_edt", mb)
    ok_out, d_out = _scipy_call("distance_transform_edt", ~mb) if ok_in else (False, None)
    if ok_in and ok_out:
        try:
            signed = d_in - d_out
            t = np.clip(signed / float(k) + 1.0, 0.0, 1.0)
            soft = (t * t * (3.0 - 2.0 * t)).astype(np.float32)
        except Exception:
            soft = None
    if soft is None:
        mbf = mb.astype(np.float32)
        blurred = gaussian_blur_np(mbf, max(1, int(k / 1.7)))
        soft = np.where(mbf > 0.5, 1.0, blurred).astype(np.float32)
    return torch.from_numpy(np.clip(soft, 0.0, 1.0).astype(np.float32))


def _color_match(patch, ref, weights, strength):
    """Shift patch colour stats toward `ref` within `weights`. 'subtle' = mean,
    'strong' = mean + std. patch/ref [ch,cw,3], weights [ch,cw]."""
    if strength == "off":
        return patch
    w = weights.reshape(-1, 1)
    wsum = float(w.sum()) + 1e-6
    pf = patch.reshape(-1, 3)
    rf = ref.reshape(-1, 3)
    pm = (pf * w).sum(0) / wsum
    rm = (rf * w).sum(0) / wsum
    if strength == "strong":
        pv = ((pf - pm) ** 2 * w).sum(0) / wsum
        rv = ((rf - rm) ** 2 * w).sum(0) / wsum
        scale = (rv.clamp_min(1e-6).sqrt()) / (pv.clamp_min(1e-6).sqrt())
        scale = scale.clamp(0.5, 2.0)
        out = (pf - pm) * scale + rm
    else:
        out = pf - pm + rm
    return out.reshape(patch.shape).clamp(0.0, 1.0)


def resolve_seam(crop_info, softness, blend_mode):
    """Stitch-side override of the seam feather + blend mode. softness < 0 keeps
    crop_info['blend']; blend_mode 'from crop' keeps crop_info['blend_mode']."""
    if not isinstance(crop_info, dict):
        crop_info = {}
    try:
        s = int(softness)
    except (TypeError, ValueError):
        s = -1
    if s < 0:
        try:
            s = int(crop_info.get("blend", 16))
        except (TypeError, ValueError):
            s = 16
    blend = max(0, min(150, s))

    bm = str(blend_mode if blend_mode is not None else "from crop").strip().lower()
    if bm in ("", "from crop", "inherit"):
        bm = str(crop_info.get("blend_mode", "mask"))
    bm = bm.replace(" ", "_")
    if bm not in ("mask", "whole_crop"):
        bm = "mask"
    return blend, bm


def composite_replace(region, patch, coverage):
    """RGBA 'replace' composite: inside `coverage` the patch replaces the
    region, alpha included, interpolated in premultiplied space:

        out_a   = pa*c + da*(1-c)
        out_rgb = (prgb*pa*c + drgb*da*(1-c)) / out_a

    region/patch [B,h,w,4] straight alpha, coverage [1,h,w,1]. Where coverage
    is 0 the region is returned bit-exact (hidden RGB under alpha 0 included).
    With pa = da = 1 this reduces to Pixaroma's RGB lerp patch*c + region*(1-c)."""
    c = coverage
    pa = patch[..., 3:4].clamp(0, 1)
    da = region[..., 3:4].clamp(0, 1)
    wp = pa * c
    wd = da * (1.0 - c)
    out_a = wp + wd
    prem = patch[..., :3] * wp + region[..., :3] * wd
    tiny = torch.finfo(region.dtype).tiny
    rgb = torch.where(out_a > 0, prem / out_a.clamp_min(tiny),
                      torch.where(c > 0, patch[..., :3], region[..., :3]))
    result = torch.cat([rgb, out_a], dim=-1).clamp(0, 1)
    return torch.where(c == 0, region, result)


# ─────────────────────────────────────────────────────────────────────────────
# STITCH

def stitch_back_rgba(crop_info, image, mask, blend, blend_mode, color_match):
    """Paste `image` (RGB or RGBA) back onto crop_info['image'] (RGBA) at the
    recorded region. Returns (result [B,H,W,4], original [B,H,W,4])."""
    base = to_rgba(crop_info["image"])
    H, W = int(base.shape[1]), int(base.shape[2])
    x = _clampi(crop_info.get("x", 0), 0, W - 1)
    y = _clampi(crop_info.get("y", 0), 0, H - 1)
    cw = int(max(1, min(int(crop_info.get("w", W)), W - x)))
    ch = int(max(1, min(int(crop_info.get("h", H)), H - y)))

    patch = to_rgba(image)
    if int(patch.shape[1]) != ch or int(patch.shape[2]) != cw:
        patch = resize_rgba_tensor(patch, cw, ch, "lanczos")
    patch = patch.to(base.device, base.dtype)

    # coverage [ch,cw] (1 = take the patch)
    if blend_mode == "whole_crop":
        a = _feather_alpha(torch.ones((ch, cw), dtype=torch.float32), blend)
    else:
        if isinstance(mask, torch.Tensor):
            a = torch.from_numpy(np.ascontiguousarray(mask_to_np(mask, ch, cw), dtype=np.float32))
        elif isinstance(crop_info.get("mask"), torch.Tensor):
            fm = mask_to_np(crop_info["mask"], H, W)[y:y + ch, x:x + cw]
            a = torch.from_numpy(np.ascontiguousarray(fm, dtype=np.float32))
        else:
            a = torch.ones((ch, cw), dtype=torch.float32)
        ac = a.clamp(0, 1)
        ab = ac > 0.5
        if not bool(ab.any()) or bool(ab.all()):
            # no mask edge to soften (empty / full mask): rectangle feather
            a = _feather_alpha(torch.ones((ch, cw), dtype=torch.float32), blend)
        else:
            a = _blur_alpha(ac, blend)

    out = base.clone()
    B = int(out.shape[0])
    if patch.shape[0] != B:
        if patch.shape[0] == 1:
            patch = patch.repeat(B, 1, 1, 1)
        elif B == 1:
            out = out.repeat(patch.shape[0], 1, 1, 1)
            B = int(patch.shape[0])
        else:
            n = min(B, int(patch.shape[0]))
            print(f"[umbrae inpaint stitch rgba] batch mismatch: original {B} vs "
                  f"inpainted {patch.shape[0]} - using {n} frames")
            out, patch = out[:n], patch[:n]
            B = n

    if color_match and color_match != "off":
        patch = patch.clone()
        # reference = the unmasked context around the mask (not the masked
        # area), weighted by both alphas so transparent pixels don't count.
        am = np.clip(a.detach().cpu().numpy(), 0.0, 1.0)
        ctx = (am < 0.5).astype(np.float32)
        if ctx.sum() < 0.02 * ctx.size:
            ctx = np.ones_like(am, dtype=np.float32)
        ctx_t = torch.from_numpy(np.ascontiguousarray(ctx))
        for b in range(B):
            region_b = out[b, y:y + ch, x:x + cw, :3].detach().cpu().float()
            p_b = patch[b, :, :, :3].detach().cpu().float()
            weights = (ctx_t
                       * patch[b, :, :, 3].detach().cpu().float().clamp(0, 1)
                       * out[b, y:y + ch, x:x + cw, 3].detach().cpu().float().clamp(0, 1))
            if not bool((weights > 0).any()):
                continue
            matched = _color_match(p_b, region_b, weights, color_match)
            patch[b, :, :, :3] = matched.to(patch.device, patch.dtype)

    cov = a[None, ..., None].to(out.device, out.dtype)
    region = out[:, y:y + ch, x:x + cw, :]
    out[:, y:y + ch, x:x + cw, :] = composite_replace(region, patch, cov)

    original = base
    if original.shape[0] != out.shape[0]:
        if original.shape[0] == 1:
            original = original.repeat(out.shape[0], 1, 1, 1)
        else:
            original = original[:out.shape[0]]
    return out.clamp(0, 1), original.clamp(0, 1)
