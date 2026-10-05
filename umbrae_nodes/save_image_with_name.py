import os
import re
import numpy as np
from PIL import Image

class SaveImageWithName:
    """
    Save a single IMAGE tensor (1,H,W,3) to disk with a specific filename and directory.

    Inputs:
      - image: single image tensor (1,H,W,3) float32 in [0,1]
      - image_filename: the original image filename (e.g., "foo.jpg") or a stem ("foo")
      - output_dir: where to save; if blank, defaults to ComfyUI/output/resized
      - format: "png", "jpg", or "webp"
      - quality: used for jpg/webp (ignored for png)
      - overwrite: if False, auto-increments suffix (_001, _002, ...)
      - keep_original_extension: if True and image_filename has an extension, we keep it and ignore 'format'
        (useful if you want mirror names exactly). If False, we enforce the 'format' extension.

    Returns:
      - saved_path: full path of the written file
      - saved_filename: final filename used (basename.ext)
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "image_filename": ("STRING", {"multiline": False, "default": ""}),
                "output_dir": ("STRING", {"multiline": False, "default": ""}),
                "format": (["png", "jpg", "webp"],),
                "quality": ("INT", {"default": 95, "min": 1, "max": 100, "step": 1}),
                "overwrite": ("BOOLEAN", {"default": False}),
                "keep_original_extension": ("BOOLEAN", {"default": False}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("saved_path", "saved_filename")
    FUNCTION = "save"
    CATEGORY = "umbrae/files"

    # --- helpers ---
    def _sanitize(self, s: str) -> str:
        # remove control chars, replace win-invalid, trim
        s = re.sub(r"[\x00-\x1f\x7f]", "", s)
        s = re.sub(r'[\\/:*?"<>|]', "_", s)
        return s.strip(" .")

    def _default_output_dir(self) -> str:
        # ComfyUI/custom_nodes/umbrae_nodes/.. -> ComfyUI
        here = os.path.dirname(os.path.abspath(__file__))
        comfy_root = os.path.abspath(os.path.join(here, "..", ".."))
        return os.path.join(comfy_root, "output", "resized")

    def _ensure_dir(self, path: str):
        os.makedirs(path, exist_ok=True)

    def _pick_ext(self, image_filename: str, fmt: str, keep_original_extension: bool) -> str:
        base = os.path.basename(image_filename or "")
        stem, ext = os.path.splitext(base)
        stem = self._sanitize(stem or "image")
        ext = (ext or "").lower()

        if keep_original_extension and ext in [".png", ".jpg", ".jpeg", ".webp"]:
            # normalize .jpeg -> .jpg
            if ext == ".jpeg":
                ext = ".jpg"
            return stem, ext

        # enforce format
        ext_map = {"png": ".png", "jpg": ".jpg", "webp": ".webp"}
        return stem, ext_map.get(fmt, ".png")

    def _unique_path(self, dirpath: str, basename: str, ext: str) -> (str, str):
        candidate = f"{basename}{ext}"
        full = os.path.join(dirpath, candidate)
        if not os.path.exists(full):
            return full, candidate
        # auto-increment
        idx = 1
        while True:
            candidate = f"{basename}_{idx:03d}{ext}"
            full = os.path.join(dirpath, candidate)
            if not os.path.exists(full):
                return full, candidate
            idx += 1

    def _tensor_to_pil(self, image):
        # image: (1,H,W,3) float32 [0,1]
        if image is None:
            raise ValueError("image is None")
        if hasattr(image, "shape") and len(image.shape) == 4 and image.shape[0] == 1:
            arr = image[0].detach().cpu().numpy() if hasattr(image, "detach") else image[0]
        else:
            raise ValueError("Expected IMAGE tensor with shape (1,H,W,3)")
        arr = np.clip(arr, 0.0, 1.0)
        arr = (arr * 255.0).round().astype(np.uint8)  # H,W,3
        return Image.fromarray(arr, mode="RGB")

    # --- main ---
    def save(self, image, image_filename, output_dir, format, quality, overwrite, keep_original_extension):
        # Resolve dir
        out_dir = output_dir.strip() or self._default_output_dir()
        out_dir = os.path.abspath(out_dir)
        self._ensure_dir(out_dir)

        # Sanitize and decide extension
        stem, ext = self._pick_ext(image_filename, format, keep_original_extension)
        stem = self._sanitize(stem) or "image"

        # Build path
        if overwrite:
            final_name = f"{stem}{ext}"
            full_path = os.path.join(out_dir, final_name)
        else:
            full_path, final_name = self._unique_path(out_dir, stem, ext)

        # Convert to PIL and write
        im = self._tensor_to_pil(image)
        save_kwargs = {}
        if ext == ".png":
            save_kwargs.update({"optimize": True, "compress_level": 6})
        elif ext == ".jpg":
            save_kwargs.update({"quality": int(quality), "subsampling": 0, "progressive": True})
        elif ext == ".webp":
            save_kwargs.update({"quality": int(quality)})

        im.save(full_path, **save_kwargs)

        return (full_path, final_name)
