import torch

class ConstantImage1x1:
    """
    Emits a tiny dummy image (1x1 RGB). Use when a node requires an IMAGE input
    but you're actually processing via source_file elsewhere.
    """
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "optional": {
                "r": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "g": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01}),
                "b": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 1.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "emit"
    CATEGORY = "umbrae/image"

    def emit(self, r=0.0, g=0.0, b=0.0):
        img = torch.tensor([[[[r,g,b]]]], dtype=torch.float32)  # (1,1,1,3)
        return (img,)
