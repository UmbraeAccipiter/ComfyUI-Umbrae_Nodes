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
    processed through the scale settings."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
            },
            "optional": {
                "region": (anytype, {
                    "tooltip": "Bounding boxes, a SEGS, or any detector output. Defines the crop "
                               "geometry; a SEGS also carries a per-detection mask.",
                }),
                "region_alternate": (anytype, {
                    "tooltip": "A mask (or a second region source). Rides along with the crop and "
                               "is cut by the same geometry. Its own bounding box can contribute "
                               "geometry if Extract is set to include bbox.",
                }),
            },
            "hidden": {
                "ui_state": ("STRING", {"default": "{}"}),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("image", "mask")
    FUNCTION     = "run"
    CATEGORY     = "umbrae/image"

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    def run(self, image, region=None, region_alternate=None, ui_state="{}"):
        try:
            state = json.loads(ui_state or "{}")
        except Exception:
            state = {}

        res = core.process(image, region, region_alternate, state)
        return (res["images"], res["masks"])


NODE_CLASS_MAPPINGS        = {"UmbraeSimpleCrop": UmbraeSimpleCrop}
NODE_DISPLAY_NAME_MAPPINGS = {"UmbraeSimpleCrop": "Crop Image [umbrae]"}
