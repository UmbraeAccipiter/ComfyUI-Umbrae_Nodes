# rgba_inpaint_nodes.py — umbrae_nodes v0.8.1
#
# "inpaint crop rgba [umbrae]" / "inpaint stitch rgba [umbrae]"
# RGBA-native versions of Pixaroma's Inpaint Crop / Inpaint Stitch (MIT,
# see rgba_inpaint_core.py for the notice). Python only - no mask editor:
# the inpaint mask is a required MASK input (SAM, segmentation, any MASK).
#
# Unlike the Pixaroma nodes, errors are NOT swallowed into a silent
# pass-through: a failed crop/stitch raises, so a broken run is visible
# instead of saving a wrong image.

from .rgba_inpaint_core import (
    apply_rgba_crop, stitch_back_rgba, resolve_seam, merge_params,
    DEFAULTS, MATTES, UMBRAE_RGBA_CROP_INFO,
)

_SIZE_MODE = {
    "keep shape (long side)": "keep",
    "force size (square)": "force",
    "free (multiple only)": "free",
}

_BLEND_MODE = {
    "mask": "mask",
    "whole crop": "whole_crop",
}

_MATTE_LIST = list(MATTES.keys())  # black, white, gray


class UmbraeInpaintCropRGBA:
    DESCRIPTION = (
        "Inpaint Crop RGBA - crops the masked area (plus context) out of an RGB or "
        "RGBA image at a model-friendly size, keeping transparency.\n\n"
        "image: RGB crop flattened over the matte colour, for RGB-only models.\n"
        "image_rgba: the same crop with its transparency.\n"
        "crop_info carries the full RGBA original to Inpaint Stitch RGBA, which "
        "pastes the result back. An RGB input is treated as fully opaque."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {
                    "tooltip": "RGB or RGBA image to inpaint (e.g. image_rgba from load image rgba).",
                }),
                "mask": ("MASK", {
                    "tooltip": "Area to inpaint (1 = inpaint). SAM / segmentation / any MASK.",
                }),
                "size_mode": (list(_SIZE_MODE.keys()), {
                    "default": "keep shape (long side)",
                    "tooltip": (
                        "Keep shape: scale the masked area so its long side hits the "
                        "target, no stretching. Force size: always a target x target "
                        "square. Free: natural size, rounded to the multiple."
                    ),
                }),
                "target": ("INT", {
                    "default": 1024, "min": 64, "max": 8192, "step": 8,
                    "tooltip": "Target long side (keep) or square size (force), in px.",
                }),
                "multiple": ([8, 16, 32, 64], {
                    "default": 8,
                    "tooltip": "Round the crop size to this multiple for model compatibility.",
                }),
                "context_px": ("INT", {
                    "default": 24, "min": 0, "max": 1024, "step": 1,
                    "tooltip": "Extra pixels of surrounding context on each side.",
                }),
                "mask_grow": ("INT", {
                    "default": 4, "min": 0, "max": 256, "step": 1,
                    "tooltip": "Expand the mask by this many pixels before cropping.",
                }),
                "mask_blur": ("INT", {
                    "default": 4, "min": 0, "max": 256, "step": 1,
                    "tooltip": "Soften the OUTPUT mask edge by this many pixels.",
                }),
                "softness": ("INT", {
                    "default": 16, "min": 0, "max": 150, "step": 1,
                    "tooltip": "Seam feather used by Inpaint Stitch RGBA (also grows the crop context to fit).",
                }),
                "blend_mode": (list(_BLEND_MODE.keys()), {
                    "default": "mask",
                    "tooltip": (
                        "How the stitch pastes back. 'mask': only the masked area is "
                        "replaced. 'whole crop': the entire cropped box is replaced."
                    ),
                }),
                "invert_mask": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Flip the mask so the OPPOSITE area is inpainted.",
                }),
                "matte": (_MATTE_LIST, {
                    "default": "black",
                    "tooltip": "Colour behind transparent areas in the RGB 'image' output.",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "MASK", UMBRAE_RGBA_CROP_INFO, "INT", "INT")
    RETURN_NAMES = ("image", "image_rgba", "mask", "crop_info", "width", "height")
    OUTPUT_TOOLTIPS = (
        "Cropped region, RGB, flattened over the matte colour (for RGB-only models).",
        "Cropped region, RGBA (transparency kept).",
        "Cropped inpaint mask at the same size (grown + blurred).",
        "Crop info for Inpaint Stitch RGBA (full RGBA original + region).",
        "Crop width in pixels.",
        "Crop height in pixels.",
    )
    FUNCTION = "run"
    CATEGORY = "umbrae/image"

    def run(self, image, mask, size_mode="keep shape (long side)", target=1024,
            multiple=8, context_px=24, mask_grow=4, mask_blur=4, softness=16,
            blend_mode="mask", invert_mask=False, matte="black"):
        p = dict(DEFAULTS)
        p.update({
            "size_mode": _SIZE_MODE.get(size_mode, "keep"),
            "target": int(target), "target_w": int(target), "target_h": int(target),
            "multiple": int(multiple), "context_px": int(context_px),
            "mask_grow": int(mask_grow), "mask_blur": int(mask_blur),
            "blend": max(0, min(150, int(softness))),
            "invert_mask": bool(invert_mask),
        })
        p = merge_params(p)
        crop_rgb, crop_rgba, out_mask, crop_info, ow, oh = apply_rgba_crop(image, mask, p, matte)
        crop_info["blend"] = p["blend"]
        crop_info["blend_mode"] = _BLEND_MODE.get(blend_mode, "mask")
        return (crop_rgb, crop_rgba, out_mask, crop_info, ow, oh)


class UmbraeInpaintStitchRGBA:
    DESCRIPTION = (
        "Inpaint Stitch RGBA - pastes the inpainted crop back onto the RGBA "
        "original from Inpaint Crop RGBA. Inside the mask the result REPLACES the "
        "original, transparency included, with a feathered seam. Wire VAE Decode "
        "straight in (an RGBA decode keeps its alpha; an RGB one counts as opaque). "
        "Both outputs are always RGBA."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE", {
                    "tooltip": "The inpainted crop (RGB or RGBA). Resized back to the region automatically.",
                }),
                "crop_info": (UMBRAE_RGBA_CROP_INFO, {
                    "tooltip": "crop_info from Inpaint Crop RGBA.",
                }),
            },
            "optional": {
                "mask": ("MASK", {
                    "tooltip": "Optional. Limits the paste to this area. If omitted, the mask carried in crop_info is used.",
                }),
                "softness": ("INT", {
                    "default": -1, "min": -1, "max": 150, "step": 1,
                    "tooltip": "Seam feather override. -1 = use the crop node's softness.",
                }),
                "blend_mode": (["from crop", "mask", "whole crop"], {
                    "default": "from crop",
                    "tooltip": "Override the crop node's blend mode.",
                }),
                "color_match": (["off", "subtle", "strong"], {
                    "default": "off",
                    "tooltip": "Correct a colour/tone shift the model introduced, matched to the unmasked surroundings.",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE")
    RETURN_NAMES = ("image", "original")
    OUTPUT_TOOLTIPS = (
        "The RGBA original with the inpainted crop blended back in place.",
        "The RGBA original, uncropped (for a before / after compare).",
    )
    FUNCTION = "run"
    CATEGORY = "umbrae/image"

    def run(self, image, crop_info, mask=None, softness=-1, blend_mode="from crop",
            color_match="off"):
        if not isinstance(crop_info, dict) or "image" not in crop_info \
                or any(k not in crop_info for k in ("x", "y", "w", "h")):
            raise ValueError("inpaint stitch rgba: crop_info is missing or malformed - "
                             "wire it from inpaint crop rgba [umbrae].")
        blend, bm = resolve_seam(crop_info, softness, blend_mode)
        cm = str(color_match)
        cm = cm if cm in ("off", "subtle", "strong") else "off"
        result, original = stitch_back_rgba(crop_info, image, mask, blend, bm, cm)
        return (result, original)


NODE_CLASS_MAPPINGS = {
    "UmbraeInpaintCropRGBA": UmbraeInpaintCropRGBA,
    "UmbraeInpaintStitchRGBA": UmbraeInpaintStitchRGBA,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "UmbraeInpaintCropRGBA": "inpaint crop rgba [umbrae]",
    "UmbraeInpaintStitchRGBA": "inpaint stitch rgba [umbrae]",
}
