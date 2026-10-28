# load_image_rgba.py — umbrae_nodes v0.8.1
#
# "load image rgba [umbrae]" - image loader that keeps transparency.
# Python only: native image_upload combo (upload / drag-drop / preview come
# from the stock frontend), resize via scale_crop_shared.apply_resize so the
# math matches the rest of umbrae_nodes.
#
# Outputs both an RGB image (flattened over a matte) and an RGBA image, so
# RGB-only consumers (SAM, VAE Encode, ...) and RGBA consumers can be wired
# from the same loader. Colour and alpha are resized TOGETHER (Pillow resizes
# RGBA through premultiplied alpha), so edges stay smooth and the colour hidden
# under transparent pixels never bleeds into the visible subject.
#
# Frame / bit-depth handling follows ComfyUI's LoadImage and Pixaroma's
# Load Image (MIT, copyright (c) 2026 pixaroma - see rgba_inpaint_core.py).

import hashlib
import os

import numpy as np
import torch
from PIL import Image, ImageOps, ImageSequence

import folder_paths
import node_helpers

from . import scale_crop_shared as scs

_I16_MODES = ("I;16", "I;16B", "I;16L", "I;16N")

_RESIZE_MODES = ["OFF", "LARGEST_EDGE", "SMALLEST_EDGE", "MAX_MP", "FIT_AND_PAD", "FORCE_EXACT"]

_INTERP = {
    "lanczos": Image.LANCZOS,
    "bicubic": Image.BICUBIC,
    "bilinear": Image.BILINEAR,
    "nearest": Image.NEAREST,
}

_MATTES = {
    "black": (0.0, 0.0, 0.0),
    "white": (1.0, 1.0, 1.0),
    "gray": (0.5, 0.5, 0.5),
}


class UmbraeLoadImageRGBA:
    DESCRIPTION = (
        "Load Image RGBA - loads an image keeping its transparency, with an "
        "optional resize.\n\n"
        "image: RGB, flattened over the matte colour (for RGB-only nodes).\n"
        "image_rgba: RGBA with transparency (opaque alpha if the file has none).\n"
        "mask: 1 - alpha (ComfyUI convention), matching image_rgba after resize."
    )

    @classmethod
    def INPUT_TYPES(cls):
        input_dir = folder_paths.get_input_directory()
        files = []
        if os.path.isdir(input_dir):
            for root, _dirs, fnames in os.walk(input_dir):
                rel_root = os.path.relpath(root, input_dir)
                for fname in fnames:
                    rel = fname if rel_root == "." else os.path.join(rel_root, fname)
                    files.append(rel.replace("\\", "/"))
        files = folder_paths.filter_files_content_types(files, ["image"])
        return {
            "required": {
                "image": (sorted(files), {"image_upload": True,
                                          "tooltip": "Image from ComfyUI's input folder (upload, drag-drop or pick)."}),
                "resize_mode": (_RESIZE_MODES, {
                    "default": "OFF",
                    "tooltip": (
                        "OFF: no resize. LARGEST_EDGE / SMALLEST_EDGE: that edge = target_size. "
                        "MAX_MP: total pixels = target_mp (binary MP, as the rest of umbrae_nodes). "
                        "FIT_AND_PAD: fit inside width x height, transparent padding. "
                        "FORCE_EXACT: stretch to width x height."
                    ),
                }),
                "target_size": ("INT", {"default": 1024, "min": 8, "max": 16384, "step": 8,
                                        "tooltip": "Edge length for LARGEST_EDGE / SMALLEST_EDGE."}),
                "target_mp": ("FLOAT", {"default": 1.0, "min": 0.01, "max": 64.0, "step": 0.01,
                                        "tooltip": "Megapixels for MAX_MP."}),
                "width": ("INT", {"default": 1024, "min": 8, "max": 16384, "step": 8,
                                  "tooltip": "Box width for FIT_AND_PAD / FORCE_EXACT."}),
                "height": ("INT", {"default": 1024, "min": 8, "max": 16384, "step": 8,
                                   "tooltip": "Box height for FIT_AND_PAD / FORCE_EXACT."}),
                "interpolation": (list(_INTERP.keys()), {"default": "lanczos"}),
                "direction": (["down", "up", "both"], {
                    "default": "down",
                    "tooltip": "down = never enlarge, up = never shrink, both = always hit the target.",
                }),
                "matte": (list(_MATTES.keys()), {
                    "default": "black",
                    "tooltip": "Colour behind transparent areas in the RGB 'image' output.",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "MASK", "INT", "INT", "STRING")
    RETURN_NAMES = ("image", "image_rgba", "mask", "width", "height", "filename")
    OUTPUT_TOOLTIPS = (
        "RGB image flattened over the matte colour, after any resize.",
        "RGBA image with transparency, after any resize.",
        "1 - alpha (1 = transparent), after any resize.",
        "Output width in pixels.",
        "Output height in pixels.",
        "Filename without extension.",
    )
    FUNCTION = "load_image"
    CATEGORY = "umbrae/image"

    def load_image(self, image, resize_mode="OFF", target_size=1024, target_mp=1.0,
                   width=1024, height=1024, interpolation="lanczos", direction="down",
                   matte="black"):
        image_path = folder_paths.get_annotated_filepath(image)
        img = node_helpers.pillow(Image.open, image_path)
        basename = os.path.splitext(os.path.basename(image_path))[0]

        try:
            import comfy.model_management as _mm
            tensor_dtype = _mm.intermediate_dtype()
        except Exception:
            tensor_dtype = torch.float32

        interp = _INTERP.get(str(interpolation).lower(), Image.LANCZOS)
        matte_rgb = np.asarray(_MATTES.get(str(matte).lower(), _MATTES["black"]), dtype=np.float32)

        rgba_frames = []
        first_size = None
        for frame in ImageSequence.Iterator(img):
            frame = node_helpers.pillow(ImageOps.exif_transpose, frame)
            if frame.mode == "I":
                frame = frame.point(lambda px: px * (1 / 255))
            elif frame.mode in _I16_MODES:
                frame = frame.convert("I").point(lambda px: px * (1 / 257))
            if frame.mode == "I":
                frame = frame.convert("L")   # I -> RGBA is not a direct PIL path
            rgba = frame.convert("RGBA")     # also resolves P + transparency

            if first_size is None:
                first_size = rgba.size
            if rgba.size != first_size:
                continue                    # native LoadImage: skip off-size frames

            rgba = scs.apply_resize(
                rgba, resize_mode, interp, direction, int(width), int(height),
                target_size=int(target_size), target_mp=float(target_mp),
                keep_alpha=True,
            )
            if rgba.mode != "RGBA":          # defensive: never silently lose alpha
                rgba = rgba.convert("RGBA")
            rgba_frames.append(np.asarray(rgba, dtype=np.float32) / 255.0)

            if img.format == "MPO":
                break

        if not rgba_frames:
            raise ValueError(f"load image rgba: no readable frames in {image}")

        # all kept frames share one size (same source size + same settings)
        arr = np.stack(rgba_frames, 0)                       # [B,H,W,4]
        alpha = arr[..., 3:4]
        rgb = arr[..., :3] * alpha + matte_rgb * (1.0 - alpha)

        out_rgba = torch.from_numpy(arr).to(dtype=tensor_dtype)
        out_rgb = torch.from_numpy(np.ascontiguousarray(rgb)).to(dtype=tensor_dtype)
        out_mask = torch.from_numpy(np.ascontiguousarray(1.0 - arr[..., 3])).to(dtype=tensor_dtype)
        h, w = int(arr.shape[1]), int(arr.shape[2])
        return (out_rgb, out_rgba, out_mask, w, h, basename)

    @classmethod
    def IS_CHANGED(cls, image, **kwargs):
        image_path = folder_paths.get_annotated_filepath(image)
        m = hashlib.sha256()
        with open(image_path, "rb") as f:
            m.update(f.read())
        return m.hexdigest()

    @classmethod
    def VALIDATE_INPUTS(cls, image, **kwargs):
        if not folder_paths.exists_annotated_filepath(image):
            return f"Invalid image file: {image}"
        return True


NODE_CLASS_MAPPINGS = {"UmbraeLoadImageRGBA": UmbraeLoadImageRGBA}
NODE_DISPLAY_NAME_MAPPINGS = {"UmbraeLoadImageRGBA": "load image rgba [umbrae]"}
