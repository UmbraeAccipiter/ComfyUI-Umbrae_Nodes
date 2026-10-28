import json
import numpy as np
import torch
from PIL import Image

from . import scale_crop_shared as scs
from . import crop_core as core

anytype = scs.ANYTYPE


class UmbraeSimpleCrop:
    """Crop / resize an image (and any paired mask) using a Region (bbox or SEGS)
    and/or a Region alternate (mask or SEGS). Pure image manipulation — no saving,
    no iteration. Both fields are optional; with neither wired the whole image is
    processed through the scale settings.

    List in, list out: every frame of every incoming image is cropped, and each
    crop leaves on its own list item at its native size (no black padding to a
    common size). A downstream node runs once per crop; training prep [umbrae]
    takes the whole list and pairs it with a caption list by index."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
            },
            "optional": {
                "region": (anytype, {
                    "tooltip": "Bounding boxes, a SEGS, or any detector output. Defines the crop "
                               "geometry; a SEGS also carries a per-detection mask. A list with one "
                               "entry per image is paired by index; one entry applies to all.",
                }),
                "region_alternate": (anytype, {
                    "tooltip": "A mask (or a second region source). Rides along with the crop and "
                               "is cut by the same geometry. Its own bounding box can contribute "
                               "geometry if Extract is set to include bbox.",
                }),
                "upscale_model": ("UPSCALE_MODEL", {
                    "tooltip": "Optional. When the resize stage enlarges a crop (direction Up / Both), "
                               "the model does the enlarging instead of Lanczos; the final size is "
                               "unchanged. Ignored for downscaling.",
                }),
            },
            "hidden": {
                "ui_state": ("STRING", {"default": "{}"}),
            },
        }

    RETURN_TYPES   = ("IMAGE", "MASK")
    RETURN_NAMES   = ("image", "mask")
    OUTPUT_TOOLTIPS = ("One item per crop, native size. Downstream nodes run once per crop.",
                       "One mask per crop, same geometry as its image.")
    INPUT_IS_LIST  = True
    OUTPUT_IS_LIST = (True, True)
    FUNCTION       = "run"
    CATEGORY       = "umbrae/image"

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    def run(self, image, region=None, region_alternate=None, ui_state=None, upscale_model=None):
        try:
            state = json.loads(core.as_list(ui_state)[0] or "{}") if core.as_list(ui_state) else {}
        except Exception:
            state = {}

        ups = core.as_list(upscale_model)
        upscaler = scs.model_upscaler(ups[0]) if ups else None
        crops = []
        for e in core.expand_inputs(image, region, region_alternate):
            crops.extend(core.process_frame(e["frame"], e["region"], e["alt"], state,
                                            upscaler=upscaler)["crops"])
        if not crops:
            return ([torch.zeros((1, 1, 1, 3), dtype=torch.float32)], [core.blank_mask(1, 1)])
        return ([c["image"] for c in crops], [c["mask"] for c in crops])


NODE_CLASS_MAPPINGS        = {"UmbraeSimpleCrop": UmbraeSimpleCrop}
NODE_DISPLAY_NAME_MAPPINGS = {"UmbraeSimpleCrop": "Crop Image [umbrae]"}
