# umbrae_nodes/modules/vlm — umbrae_nodes v0.9.1
# Hugging Face VLM / LLM loader + generator that lets ComfyUI's model management
# own the model's VRAM, plus a JoyCaption-style caption prompt builder.
# See README.md in this folder.

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
