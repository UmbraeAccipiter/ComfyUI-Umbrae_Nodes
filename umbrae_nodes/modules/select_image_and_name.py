import torch

class SelectImageAndName:
    """
    Given:
      - images: batch tensor (N,H,W,3)
      - filenames: STRING with newline-separated names (len == N)
      - index: int
    Returns:
      - image: single image (1,H,W,3)
      - image_filename: STRING (exact filename at index)
    Notes:
      - Index is clamped to [0, N-1]
      - If N==0, returns a black 1x1 image and empty filename
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "filenames": ("STRING", {"multiline": True}),
                "index": ("INT", {"default": 0, "min": 0, "max": 10_000_000}),
            }
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "image_filename")
    FUNCTION = "select"
    CATEGORY = "umbrae/files"

    def select(self, images, filenames, index):
        if not isinstance(images, torch.Tensor) or images.ndim != 4:
            # Return safe placeholder
            img = torch.zeros((1, 1, 1, 3), dtype=torch.float32)
            return (img, "")

        n = images.shape[0]
        if n == 0:
            img = torch.zeros((1, 1, 1, 3), dtype=torch.float32)
            return (img, "")

        # Parse filenames into a list of exactly n entries (pad/truncate)
        name_list = [ln.strip() for ln in filenames.splitlines()]
        if len(name_list) < n:
            # pad with empty names to match N
            name_list += [""] * (n - len(name_list))
        elif len(name_list) > n:
            name_list = name_list[:n]

        # clamp index
        idx = max(0, min(index, n - 1))

        # slice out one image, keep leading batch dimension (1, H, W, 3)
        out_img = images[idx:idx+1, ...]
        out_name = name_list[idx] if idx < len(name_list) else ""
        return (out_img, out_name)
