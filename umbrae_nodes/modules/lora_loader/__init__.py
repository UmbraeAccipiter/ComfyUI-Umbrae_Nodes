# umbrae_nodes/modules/lora_loader — umbrae_nodes v0.9.3
# "lora loader [umbrae]": LoRA stack with Civitai / Hugging Face search and
# download, full gallery info panel and a triggers output. See README.md here.

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from .server import register as _register_routes

_register_routes()

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
