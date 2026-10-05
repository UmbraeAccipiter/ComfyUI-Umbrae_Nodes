"""
comfyui-mask-batch-editor
--------------------------
Nodes for editing SAM3 (or any) mask batches in an external editor.

  SaveMaskBatch    – writes masks to disk, with toggle to skip if edits exist
  LoadMaskBatch    – reads edited masks back, with optional cleanup
  MaskBatchOverlay – previews a mask batch as hue-shifted colour overlays

Wiring:
  SAM3 → [Save Mask Batch] → save_folder (STRING)
                                   │
                               [Pause node]
                                   │
                            load_folder (STRING)
                                   │
                          [Load Mask Batch] → masks → detailing nodes
"""

import json
import os
import re
import glob
import shutil

import numpy as np
import torch
from PIL import Image

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _comfyui_root() -> str:
    try:
        import folder_paths
        return folder_paths.base_path
    except Exception:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_save_dir(prefix: str) -> str:
    return os.path.join(_comfyui_root(), "input", "mask_edit", prefix)


def _mask_edit_root() -> str:
    return os.path.join(_comfyui_root(), "input", "mask_edit")


# Path to the small JSON file that persists the last used folder path
def _state_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "mask_batch_state.json")


def _save_last_folder(folder: str):
    try:
        with open(_state_path(), "w") as f:
            json.dump({"last_folder": folder}, f)
    except Exception as e:
        print(f"[MaskBatch] Could not save state: {e}")


def _load_last_folder() -> str:
    try:
        with open(_state_path(), "r") as f:
            return json.load(f).get("last_folder", "")
    except Exception:
        return ""


def _folder_has_edits(folder: str) -> bool:
    """Returns True if the folder contains at least one mask and ref.png."""
    has_mask = len(glob.glob(os.path.join(folder, "mask_*.png"))) > 0
    has_ref  = os.path.exists(os.path.join(folder, "ref.png"))
    return has_mask and has_ref


def _mask_tensor_to_pil(mask_slice: torch.Tensor) -> Image.Image:
    arr = mask_slice.cpu().numpy()
    arr = (arr * 255).clip(0, 255).astype(np.uint8)
    return Image.fromarray(arr, mode="L")


def _pil_to_mask_tensor(img: Image.Image) -> torch.Tensor:
    img = img.convert("L")
    arr = np.array(img).astype(np.float32) / 255.0
    return torch.from_numpy(arr)


def _image_tensor_to_pil(img_slice: torch.Tensor) -> Image.Image:
    arr = img_slice.cpu().numpy()
    arr = (arr * 255).clip(0, 255).astype(np.uint8)
    return Image.fromarray(arr, mode="RGB")


# ---------------------------------------------------------------------------
# API routes (called by the JS buttons)
# ---------------------------------------------------------------------------

def _register_api_routes():
    try:
        from aiohttp import web
        from server import PromptServer

        routes = PromptServer.instance.routes

        @routes.get("/umbrae/mask_batch/last_folder")
        async def get_last_folder(request):
            folder = _load_last_folder()
            return web.json_response({"last_folder": folder})

        @routes.post("/umbrae/mask_batch/clear_folder")
        async def clear_folder(request):
            data = await request.json()
            folder = data.get("folder", "").strip()

            # Safety: folder must be inside the mask_edit root
            edit_root = os.path.abspath(_mask_edit_root())
            target    = os.path.abspath(folder) if folder else edit_root

            if not target.startswith(edit_root):
                return web.json_response(
                    {"error": "Folder is outside the mask_edit directory."},
                    status=400,
                )

            if not os.path.isdir(target):
                return web.json_response(
                    {"error": f"Folder not found: {target}"},
                    status=404,
                )

            shutil.rmtree(target, ignore_errors=True)
            print(f"[LoadMaskBatch] API cleared folder: {target}")
            return web.json_response({"cleared": target})

    except Exception as e:
        print(f"[MaskBatch] Could not register API routes: {e}")


_register_api_routes()


# ---------------------------------------------------------------------------
# Node 1 — SaveMaskBatch
# ---------------------------------------------------------------------------

class SaveMaskBatch:
    """
    Saves every mask in a batch to disk as numbered PNGs for external editing.
    Also saves the source image as ref.png — for your editor only, never
    imported back into the workflow.

    if_edits_exist controls what happens when mask_*.png + ref.png are already
    present in the target folder:
      "overwrite"  — clear the folder and save fresh masks (default)
      "skip"       — leave existing files untouched and pass the folder through
                     so the load node can pick up your edits without re-saving
    """

    CATEGORY = "umbrae/mask"
    FUNCTION = "save"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("save_folder",)

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "masks": ("MASK",),
                "if_edits_exist": (["overwrite", "skip"], {
                    "default": "overwrite",
                    "tooltip": (
                        "overwrite: clear the folder and write fresh masks each run. "
                        "skip: if mask files + ref.png already exist, do nothing and "
                        "pass the folder path through so LoadMaskBatch can load your edits."
                    ),
                }),
            },
            "optional": {
                "source_image": ("IMAGE", {
                    "tooltip": (
                        "Source image used to make the masks. Saved as ref.png "
                        "for reference in your external editor — never loaded back."
                    ),
                }),
                "images": ("IMAGE", {
                    "tooltip": (
                        "Alias for source_image — accepted for backwards compatibility "
                        "with workflows wired before the rename."
                    ),
                }),
                "save_folder_in": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": (
                        "Override the save folder with a full path. "
                        "Leave empty to use: <ComfyUI>/input/mask_edit/<prefix>/"
                    ),
                }),
                "prefix": ("STRING", {
                    "default": "edit",
                    "multiline": False,
                    "tooltip": (
                        "Sub-folder name when save_folder_in is not set. "
                        "Use a unique name per workflow (e.g. the seed) to avoid collisions."
                    ),
                }),
            },
        }

    def save(
        self,
        masks: torch.Tensor,
        if_edits_exist: str = "overwrite",
        source_image: torch.Tensor | None = None,
        images: torch.Tensor | None = None,
        save_folder_in: str = "",
        prefix: str = "edit",
    ):
        # Accept either source_image or images (backwards compat)
        if source_image is None and images is not None:
            source_image = images

        # masks shape: (N, H, W)
        if masks.ndim == 2:
            masks = masks.unsqueeze(0)
        n = masks.shape[0]

        # Resolve folder
        save_dir = save_folder_in.strip() if save_folder_in.strip() else _default_save_dir(prefix)
        os.makedirs(save_dir, exist_ok=True)

        # Persist so the JS buttons can recall it
        _save_last_folder(save_dir)

        # Check for existing edits
        if if_edits_exist == "skip" and _folder_has_edits(save_dir):
            print(
                f"[SaveMaskBatch] edits found in {save_dir} — skipping save "
                f"(if_edits_exist=skip). LoadMaskBatch will load existing files."
            )
            return (save_dir,)

        # Overwrite path — clear stale files first
        for old in glob.glob(os.path.join(save_dir, "mask_*.png")):
            os.remove(old)
        ref_old = os.path.join(save_dir, "ref.png")
        if os.path.exists(ref_old):
            os.remove(ref_old)

        # Write masks
        written = []
        for i in range(n):
            pil_mask = _mask_tensor_to_pil(masks[i])
            mask_path = os.path.join(save_dir, f"mask_{i:02d}.png")
            pil_mask.save(mask_path)
            written.append(mask_path)

        # Write single reference image
        if source_image is not None:
            pil_ref = _image_tensor_to_pil(source_image[0])
            pil_ref.save(os.path.join(save_dir, "ref.png"))

        print(
            f"[SaveMaskBatch] wrote {n} mask(s) "
            f"({'+ ref.png' if source_image is not None else 'no reference image'}) "
            f"to: {save_dir}\n"
            + "\n".join(f"  {p}" for p in written)
        )

        return (save_dir,)


# ---------------------------------------------------------------------------
# Node 2 — LoadMaskBatch
# ---------------------------------------------------------------------------

class LoadMaskBatch:
    """
    Reads edited mask PNGs from the folder supplied by SaveMaskBatch (via Pause)
    and reassembles them into a mask batch tensor.

    Only mask_NN.png files are loaded — ref.png is intentionally ignored.
    Output mask count may differ from input count if you merged or deleted masks.

    Cleanup options (applied after loading):
      delete_files  — removes mask_*.png and ref.png, keeps the folder
      delete_folder — removes the entire folder (implies delete_files)

    Frontend buttons (on the node in the graph):
      Load Last Folder — populates load_folder with the last path SaveMaskBatch wrote
      Clear Folder     — immediately deletes the folder at the current load_folder path
                         (or the full mask_edit root if load_folder is empty)
    """

    CATEGORY = "umbrae/mask"
    FUNCTION = "load"
    RETURN_TYPES = ("MASK", "INT")
    RETURN_NAMES = ("masks", "count")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "load_folder": ("STRING", {
                    "default": "",
                    "multiline": False,
                    "tooltip": (
                        "Folder path from Save Mask Batch (via Pause node). "
                        "Drives execution order as well as supplying the path. "
                        "Use the 'Load Last Folder' button to populate automatically."
                    ),
                }),
                "delete_files": ("BOOLEAN", {
                    "default": False,
                    "tooltip": (
                        "After loading, delete mask_*.png and ref.png but keep "
                        "the folder. Good for fixed prefixes."
                    ),
                }),
                "delete_folder": ("BOOLEAN", {
                    "default": False,
                    "tooltip": (
                        "After loading, delete the entire folder. Good for unique "
                        "per-run prefixes (e.g. seed-based) to prevent accumulation."
                    ),
                }),
            },
        }

    def load(self, load_folder: str, delete_files: bool, delete_folder: bool):
        save_dir = load_folder.strip()

        if not save_dir:
            raise ValueError(
                "[LoadMaskBatch] load_folder is empty. "
                "Wire Save Mask Batch → Pause → Load Mask Batch, "
                "or use the 'Load Last Folder' button."
            )

        if not os.path.isdir(save_dir):
            raise FileNotFoundError(
                f"[LoadMaskBatch] folder not found: {save_dir}\n"
                "Run Save Mask Batch first and edit the masks before resuming."
            )

        # Load only mask_NN.png — ref.png intentionally ignored
        files = sorted(
            glob.glob(os.path.join(save_dir, "mask_*.png")),
            key=lambda p: int(re.search(r"mask_(\d+)\.png", p).group(1)),
        )

        if not files:
            raise FileNotFoundError(
                f"[LoadMaskBatch] no mask_*.png files found in: {save_dir}"
            )

        tensors = [_pil_to_mask_tensor(Image.open(p)) for p in files]
        batch = torch.stack(tensors, dim=0)

        print(
            f"[LoadMaskBatch] loaded {len(files)} mask(s) from: {save_dir}\n"
            + "\n".join(f"  {p}" for p in files)
        )

        # Cleanup
        if delete_folder:
            shutil.rmtree(save_dir, ignore_errors=True)
            print(f"[LoadMaskBatch] deleted folder: {save_dir}")
        elif delete_files:
            for f in glob.glob(os.path.join(save_dir, "mask_*.png")):
                os.remove(f)
            ref = os.path.join(save_dir, "ref.png")
            if os.path.exists(ref):
                os.remove(ref)
            print(f"[LoadMaskBatch] deleted files from: {save_dir}")

        return (batch, len(files))


# ---------------------------------------------------------------------------
# Node 3 — MaskBatchOverlay
# ---------------------------------------------------------------------------

class MaskBatchOverlay:
    """
    Overlays every mask in a batch onto a source image, each in a different hue,
    so you can visually distinguish which mask covers which region.
    """

    CATEGORY = "umbrae/mask"
    FUNCTION = "overlay"
    RETURN_TYPES = ("IMAGE", "IMAGE")
    RETURN_NAMES = ("rgb_overlay", "bw_mask")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "masks": ("MASK", {
                    "tooltip": "Mask batch to overlay (N, H, W).",
                }),
                "image": ("IMAGE", {
                    "tooltip": "Source image the masks were generated from.",
                }),
                "opacity": ("FLOAT", {
                    "default": 0.5, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "Opacity of the coloured overlays. 0=invisible, 1=opaque.",
                }),
                "hue_offset": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 360.0, "step": 1.0,
                    "tooltip": "Rotate the starting hue in degrees.",
                }),
                "saturation": ("FLOAT", {
                    "default": 0.9, "min": 0.1, "max": 1.0, "step": 0.05,
                    "tooltip": "Saturation of the overlay colours.",
                }),
                "brightness": ("FLOAT", {
                    "default": 1.0, "min": 0.1, "max": 1.0, "step": 0.05,
                    "tooltip": "Brightness of the overlay colours.",
                }),
                "resize_output": ("BOOLEAN", {
                    "default": True,
                    "tooltip": (
                        "Resize the output preview to limit resolution. "
                        "Useful for large images to keep the browser responsive."
                    ),
                }),
                "megapixels": ("FLOAT", {
                    "default": 1.0, "min": 0.1, "max": 16.0, "step": 0.1,
                    "tooltip": (
                        "Target resolution in megapixels when resize_output is enabled. "
                        "Scales by longest edge — e.g. 1.0 MP makes the longest edge 1024px."
                    ),
                }),
                "resize_method": (["lanczos", "bicubic", "bilinear", "nearest"], {
                    "default": "lanczos",
                    "tooltip": "Resampling method used when resizing.",
                }),
            },
        }

    def overlay(
        self,
        masks: torch.Tensor,
        image: torch.Tensor,
        opacity: float = 0.5,
        hue_offset: float = 0.0,
        saturation: float = 0.9,
        brightness: float = 1.0,
        resize_output: bool = True,
        megapixels: float = 1.0,
        resize_method: str = "lanczos",
    ):
        import colorsys

        img_np = image[0].cpu().numpy()
        img_np = (img_np * 255).clip(0, 255).astype(np.uint8)

        if masks.ndim == 2:
            masks = masks.unsqueeze(0)
        n = masks.shape[0]

        result = img_np.astype(np.float32)

        for i in range(n):
            hue = ((hue_offset / 360.0) + (i / n)) % 1.0
            r, g, b = colorsys.hsv_to_rgb(hue, saturation, brightness)
            colour = np.array([r * 255, g * 255, b * 255], dtype=np.float32)
            mask_alpha = masks[i].cpu().numpy()[..., np.newaxis] * opacity
            result = result * (1.0 - mask_alpha) + colour * mask_alpha

        result = result.clip(0, 255).astype(np.uint8)

        # Resize if requested — scale by longest edge to hit target megapixels
        if resize_output:
            mp_target = megapixels
            h, w = result.shape[:2]
            current_mp = (h * w) / 1_000_000
            if current_mp > mp_target:
                # Longest edge at target MP: longest_edge = sqrt(MP * 1e6 * aspect)
                if w >= h:
                    new_w = int((mp_target * 1_000_000 * w / h) ** 0.5)
                    new_h = int(new_w * h / w)
                else:
                    new_h = int((mp_target * 1_000_000 * h / w) ** 0.5)
                    new_w = int(new_h * w / h)

                method_map = {
                    "lanczos":  Image.LANCZOS,
                    "bicubic":  Image.BICUBIC,
                    "bilinear": Image.BILINEAR,
                    "nearest":  Image.NEAREST,
                }
                resample = method_map.get(resize_method, Image.LANCZOS)
                # keep method_map in scope for BW resize below
                pil_out = Image.fromarray(result).resize((new_w, new_h), resample)
                result = np.array(pil_out)
                print(
                    f"[MaskBatchOverlay] resized {w}x{h} → {new_w}x{new_h} "
                    f"({current_mp:.2f}MP → {mp_target:.2f}MP, method={resize_method})"
                )

        rgb_out = torch.from_numpy(result).float() / 255.0
        rgb_out = rgb_out.unsqueeze(0)

        # BW mask — combine all masks via max (union), then resize to match
        combined = torch.max(masks, dim=0).values          # (H, W)
        bw_np = (combined.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        # Convert to RGB so it can go directly to a preview image node
        bw_rgb = np.stack([bw_np, bw_np, bw_np], axis=-1)

        if resize_output:
            h_bw, w_bw = bw_rgb.shape[:2]
            current_mp_bw = (h_bw * w_bw) / 1_000_000
            if current_mp_bw > megapixels:
                if w_bw >= h_bw:
                    new_w_bw = int((megapixels * 1_000_000 * w_bw / h_bw) ** 0.5)
                    new_h_bw = int(new_w_bw * h_bw / w_bw)
                else:
                    new_h_bw = int((megapixels * 1_000_000 * h_bw / w_bw) ** 0.5)
                    new_w_bw = int(new_h_bw * w_bw / h_bw)
                resample = method_map.get(resize_method, Image.LANCZOS)
                bw_pil = Image.fromarray(bw_rgb).resize((new_w_bw, new_h_bw), resample)
                bw_rgb = np.array(bw_pil)

        bw_out = torch.from_numpy(bw_rgb).float() / 255.0
        bw_out = bw_out.unsqueeze(0)

        print(f"[MaskBatchOverlay] overlaid {n} mask(s) onto image.")
        return (rgb_out, bw_out)


# ---------------------------------------------------------------------------
# Node 4 — CombineMaskBatch
# ---------------------------------------------------------------------------

class CombineMaskBatch:
    """
    Flattens a mask batch down to a single BW mask image and a single MASK,
    using a selectable combine method.

      max     — union of all masks; any pixel masked in any mask stays masked
      add     — accumulated values, clamped to 1.0; shows overlap density
      average — mean across all masks; shows coverage intensity

    Both outputs are scaled by the same resize options as MaskBatchOverlay.
    """

    CATEGORY = "umbrae/mask"
    FUNCTION = "combine"
    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("bw_mask", "mask")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "masks": ("MASK",),
                "combine_method": (["max", "add", "average"], {
                    "default": "max",
                    "tooltip": (
                        "max: union of all masks. "
                        "add: accumulated (clamped to 1.0), shows overlap. "
                        "average: mean intensity across all masks."
                    ),
                }),
                "resize_output": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Resize the output to limit resolution for preview.",
                }),
                "megapixels": ("FLOAT", {
                    "default": 1.0, "min": 0.1, "max": 16.0, "step": 0.1,
                    "tooltip": "Target MP when resize_output is enabled. Scales by longest edge.",
                }),
                "resize_method": (["lanczos", "bicubic", "bilinear", "nearest"], {
                    "default": "lanczos",
                }),
            },
        }

    def combine(
        self,
        masks: torch.Tensor,
        combine_method: str = "max",
        resize_output: bool = True,
        megapixels: float = 1.0,
        resize_method: str = "lanczos",
    ):
        if masks.ndim == 2:
            masks = masks.unsqueeze(0)

        if combine_method == "max":
            combined = torch.max(masks, dim=0).values
        elif combine_method == "add":
            combined = masks.sum(dim=0).clamp(0.0, 1.0)
        else:  # average
            combined = masks.mean(dim=0)

        # MASK output — (H, W) float tensor
        mask_out = combined

        # BW image output — (H, W) → RGB so preview nodes accept it
        bw_np = (combined.cpu().numpy() * 255).clip(0, 255).astype(np.uint8)
        bw_rgb = np.stack([bw_np, bw_np, bw_np], axis=-1)

        if resize_output:
            h, w = bw_rgb.shape[:2]
            current_mp = (h * w) / 1_000_000
            if current_mp > megapixels:
                if w >= h:
                    new_w = int((megapixels * 1_000_000 * w / h) ** 0.5)
                    new_h = int(new_w * h / w)
                else:
                    new_h = int((megapixels * 1_000_000 * h / w) ** 0.5)
                    new_w = int(new_h * w / h)

                method_map = {
                    "lanczos":  Image.LANCZOS,
                    "bicubic":  Image.BICUBIC,
                    "bilinear": Image.BILINEAR,
                    "nearest":  Image.NEAREST,
                }
                resample = method_map.get(resize_method, Image.LANCZOS)
                bw_pil = Image.fromarray(bw_rgb).resize((new_w, new_h), resample)
                bw_rgb = np.array(bw_pil)
                # Resize mask_out to match
                mask_pil = Image.fromarray(bw_np).resize((new_w, new_h), resample)
                mask_out = torch.from_numpy(
                    np.array(mask_pil).astype(np.float32) / 255.0
                )

                print(
                    f"[CombineMaskBatch] resized {w}x{h} → {new_w}x{new_h} "
                    f"({current_mp:.2f}MP → {megapixels:.2f}MP)"
                )

        bw_out = torch.from_numpy(bw_rgb).float() / 255.0
        bw_out = bw_out.unsqueeze(0)

        print(
            f"[CombineMaskBatch] combined {masks.shape[0]} mask(s) "
            f"using method={combine_method}."
        )
        return (bw_out, mask_out)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

NODE_CLASS_MAPPINGS = {
    "SaveMaskBatch":    SaveMaskBatch,
    "LoadMaskBatch":    LoadMaskBatch,
    "MaskBatchOverlay": MaskBatchOverlay,
    "CombineMaskBatch":  CombineMaskBatch,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SaveMaskBatch":    "Save Mask Batch",
    "LoadMaskBatch":    "Load Mask Batch",
    "MaskBatchOverlay": "Mask Batch Overlay",
    "CombineMaskBatch":  "Combine Mask Batch",
}
