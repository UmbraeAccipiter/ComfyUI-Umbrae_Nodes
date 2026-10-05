"""
latent_auto_encode_node.py — umbrae_nodes

A latent *source* that adapts to whatever it's given each run (t2i / i2i without
rewiring), and emits the matching Flux2 sigma schedule:

  - image wired       -> (optionally resized) VAE-encoded  -> denoise = inpaint_denoise
  - non-empty latent  -> passed through (cropped, not scaled, when resize is ON)
                                                            -> denoise = inpaint_denoise
  - empty / no latent -> empty (t2i) or seeded noise latent -> denoise = 1.0

Outputs: latent, denoise, width, height (INTs), and split sigmas.

Sigmas use the Flux2 closed-form schedule (reproduced from comfy_extras
nodes_flux.Flux2Scheduler) computed from the OUTPUT W/H + steps, so they always
match the latent. The schedule is split on denoise whenever a real source (image
or non-empty latent) is present:
    k = round(steps * (1 - denoise))
    sigmas_low  = sigmas[k:]    (low-noise tail; full schedule when denoise=1)
    sigmas_high = sigmas[:k+1]  (high-noise front)
"""

import json
import math
import numpy as np
import torch
from PIL import Image

from . import scale_crop_shared as scs
from . import crop_core as core

anytype = scs.ANYTYPE


def _to_int(v, default=None):
    if v is None:
        return default
    try:
        if isinstance(v, torch.Tensor):
            v = v.flatten()[0].item()
        if isinstance(v, (list, tuple)):
            if not v:
                return default
            v = v[0]
        return int(round(float(v)))
    except Exception:
        return default


# ── Flux2 sigma schedule (verbatim math from comfy_extras nodes_flux.py) ───────
def _generalized_time_snr_shift(t, mu, sigma):
    return math.exp(mu) / (math.exp(mu) + (1 / t - 1) ** sigma)


def _compute_empirical_mu(image_seq_len, num_steps):
    a1, b1 = 8.73809524e-05, 1.89833333
    a2, b2 = 0.00016927, 0.45666666
    if image_seq_len > 4300:
        return float(a2 * image_seq_len + b2)
    m_200 = a2 * image_seq_len + b2
    m_10 = a1 * image_seq_len + b1
    a = (m_200 - m_10) / 190.0
    b = m_200 - 200.0 * a
    return float(a * num_steps + b)


def flux2_sigmas(steps, width, height):
    seq_len = round(width * height / (16 * 16))
    mu = _compute_empirical_mu(seq_len, steps)
    timesteps = torch.linspace(1, 0, steps + 1)
    return _generalized_time_snr_shift(timesteps, mu, 1.0)


class LatentAutoEncode:

    CATEGORY = "umbrae/latent"
    FUNCTION = "run"
    RETURN_TYPES = ("LATENT", "FLOAT", "INT", "INT", "SIGMAS")
    RETURN_NAMES = ("latent", "denoise", "width", "height", "sigmas")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "optional": {
                "vae": ("VAE", {
                    "tooltip": "Encodes a wired image, and supplies the latent channel count when "
                               "generating."}),
                "image": ("IMAGE", {
                    "tooltip": "i2i. Optionally resized via the panel, then encoded. Priority over latent."}),
                "latent": ("LATENT", {
                    "tooltip": "Pass-through latent, used when no image is wired. With master resize "
                               "ON, a real latent is cropped (never scaled) to the target W/H. Crop "
                               "position follows the Anchor only in CROP mode, Grid or XY only — other "
                               "modes and Face/Entropy default to center. Fill ON pads the short axis "
                               "to the target; Fill OFF leaves it short. A VAE is required for accurate "
                               "latent sizing. An all-zero latent is treated as no source."}),
                "width": (anytype, {"tooltip": "Target width (any number). Overrides the panel field."}),
                "height": (anytype, {"tooltip": "Target height (any number). Overrides the panel field."}),
                "steps": (anytype, {"tooltip": "Sampler steps for the Flux2 sigma schedule. Overrides the field."}),
                "seed": (anytype, {"tooltip": "Seed for random-noise generation."}),
                "inpaint_denoise": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.01,
                    "tooltip": "Denoise output (and sigma split point) when an image is encoded."}),
            },
            "hidden": {"ui_state": ("STRING", {"default": "{}"})},
        }

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    def _probe_vae(self, vae):
        key = id(vae)
        if getattr(self, "_probe_key", None) == key:
            return self._probe
        enc = vae.encode(torch.zeros((1, 64, 64, 3)))
        if isinstance(enc, dict):
            enc = enc["samples"]
        C = int(enc.shape[1])
        r = max(1, 64 // int(enc.shape[2]))
        self._probe_key = key
        self._probe = (C, r)
        return self._probe

    def _resize_image(self, image, state):
        out = []
        for i in range(image.shape[0]):
            a = (image[i].cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
            pil = Image.fromarray(a).convert("RGB")
            anchor = core.compute_anchor(pil, state, None)
            res = core.apply_resize(pil, state, anchor, Image.LANCZOS)
            out.append(torch.from_numpy(np.array(res.convert("RGB")).astype(np.float32) / 255.0).unsqueeze(0))
        return core._stack_uniform(out)

    # 9-box grid cell -> normalized (nx, ny) crop/pad anchor.
    _GRID_NORM = {
        "top-left": (0.0, 0.0), "top": (0.5, 0.0), "top-right": (1.0, 0.0),
        "left": (0.0, 0.5),     "center": (0.5, 0.5), "right": (1.0, 0.5),
        "bottom-left": (0.0, 1.0), "bottom": (0.5, 1.0), "bottom-right": (1.0, 1.0),
    }

    def _latent_anchor(self, state):
        # Anchor only honored in CROP mode (where the controls are settable), and
        # only for Grid / XY. Every other mode, and Face/Entropy (no pixels in a
        # latent), default to center.
        mode = str(state.get("resize_mode", "LARGEST_EDGE")).upper()
        crop_on = state.get("crop_on", True) is not False
        if mode != "CROP" or not crop_on:
            return (0.5, 0.5)
        amode = state.get("anchor_mode", "grid")
        if amode == "xy":
            xy = state.get("anchor_xy", [0.5, 0.5])
            try:
                return (min(1.0, max(0.0, float(xy[0]))), min(1.0, max(0.0, float(xy[1]))))
            except Exception:
                return (0.5, 0.5)
        if amode == "grid":
            return self._GRID_NORM.get(state.get("anchor_grid", "center"), (0.5, 0.5))
        return (0.5, 0.5)

    @staticmethod
    def _is_empty_latent(samples):
        try:
            return not bool(torch.any(samples))
        except Exception:
            return False

    def _crop_pad_latent(self, samples, tw, th, r, state):
        # Crop (and, with Fill on, pad) a real latent to the target cell grid.
        # Never scales. Anchor positions both the crop window and the pad.
        cw = max(1, int(tw) // int(r))
        ch = max(1, int(th) // int(r))
        nx, ny = self._latent_anchor(state)
        fill = state.get("fill", True) is not False
        out = samples

        # width axis
        lw = out.shape[3]
        if lw > cw:
            free = lw - cw
            x0 = max(0, min(free, int(round(nx * free))))
            out = out[:, :, :, x0:x0 + cw]
        elif lw < cw and fill:
            total = cw - lw
            before = max(0, min(total, int(round(nx * total))))
            out = torch.nn.functional.pad(out, (before, total - before, 0, 0))

        # height axis
        lh = out.shape[2]
        if lh > ch:
            free = lh - ch
            y0 = max(0, min(free, int(round(ny * free))))
            out = out[:, :, y0:y0 + ch, :]
        elif lh < ch and fill:
            total = ch - lh
            before = max(0, min(total, int(round(ny * total))))
            out = torch.nn.functional.pad(out, (0, 0, before, total - before))

        return out

    def _latent_and_size(self, vae, image, latent, state, seed, inpaint_denoise):
        tw = _to_int(state.get("__w_override"), None) or _to_int(state.get("width"), 1024)
        th = _to_int(state.get("__h_override"), None) or _to_int(state.get("height"), 1024)
        tw, th = max(8, tw), max(8, th)

        if image is not None and vae is not None:
            img = image
            if bool(state.get("resize_on", False)):
                img = self._resize_image(img, state)
            enc = vae.encode(img[:, :, :, :3])
            return ({"samples": enc}, float(inpaint_denoise), int(img.shape[2]), int(img.shape[1]), True)

        if image is not None and vae is None:
            print("[LatentAutoEncode] image wired but no VAE - cannot encode; falling through")

        if latent is not None:
            s = latent["samples"]
            if not self._is_empty_latent(s):
                r = self._probe_vae(vae)[1] if vae is not None else 8
                if bool(state.get("resize_on", False)):
                    s = self._crop_pad_latent(s, tw, th, r, state)
                    out_lat = {"samples": s}   # drop stale extras (e.g. noise_mask) after reshape
                else:
                    out_lat = latent
                return (out_lat, float(inpaint_denoise), int(s.shape[3] * r), int(s.shape[2] * r), True)
            print("[LatentAutoEncode] empty (all-zero) latent treated as no source; generating")

        if vae is not None:
            C, r = self._probe_vae(vae)
        else:
            C, r = 4, 8
            print("[LatentAutoEncode] no VAE - defaulting to 4-channel /8 latent geometry")
        lh, lw = max(1, th // r), max(1, tw // r)
        if state.get("gen_mode", "empty") == "noise":
            sd = _to_int(state.get("__seed_override"), None)
            if sd is None:
                sd = _to_int(state.get("seed"), 0)
            g = torch.Generator(device="cpu")
            g.manual_seed(int(sd) & 0xFFFFFFFFFFFFFFFF)
            samples = torch.randn((1, C, lh, lw), generator=g)
            print(f"[LatentAutoEncode] noise latent {tuple(samples.shape)} seed={sd}")
        else:
            samples = torch.zeros((1, C, lh, lw))
            print(f"[LatentAutoEncode] empty latent {tuple(samples.shape)}")
        return ({"samples": samples}, 1.0, int(tw), int(th), False)

    def run(self, vae=None, image=None, latent=None, width=None, height=None,
            steps=None, seed=None, inpaint_denoise=1.0, ui_state="{}"):
        try:
            state = json.loads(ui_state or "{}")
        except Exception:
            state = {}
        # let wired inputs override panel fields
        state["__w_override"] = width
        state["__h_override"] = height
        state["__seed_override"] = seed

        lat, denoise, ow, oh, real_source = self._latent_and_size(vae, image, latent, state, seed, inpaint_denoise)

        n_steps = _to_int(steps, None) or _to_int(state.get("steps"), 20)
        n_steps = max(1, n_steps)
        sigmas = flux2_sigmas(n_steps, ow, oh)

        d = max(0.0, min(1.0, float(denoise)))
        # Split only when a real source (encoded image OR non-empty passed latent)
        # is present AND denoise < 1. Otherwise the whole schedule is emitted
        # (t2i / full-denoise) — no toggle needed for that case.
        do_split = real_source and (d < 1.0)
        if do_split:
            k = max(0, min(n_steps, int(round(n_steps * (1.0 - d)))))
            half = state.get("sigmas_half", "low")
            out_sigmas = sigmas[:k + 1] if half == "high" else sigmas[k:]
            print(f"[LatentAutoEncode] sigmas split@{k} half={half} steps={n_steps} "
                  f"denoise={d} out={tuple(out_sigmas.shape)}")
        else:
            out_sigmas = sigmas
            print(f"[LatentAutoEncode] sigmas full steps={n_steps} denoise={d} "
                  f"out={tuple(out_sigmas.shape)}")

        return (lat, float(denoise), int(ow), int(oh), out_sigmas)


NODE_CLASS_MAPPINGS        = {"LatentAutoEncode": LatentAutoEncode}
NODE_DISPLAY_NAME_MAPPINGS = {"LatentAutoEncode": "latent auto encode [umbrae]"}
