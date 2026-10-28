# umbrae_nodes/modules/clause — umbrae_nodes v0.8.8
# Port of ComfyUI-WildcardClause (Wildcard Clause Expander) onto the umbrae
# wildcard engine. Import this AFTER umbrae_wildcard_server (wildcards loaded).
# Web UI: umbrae_nodes/web/clause/ (pack root, two levels up).

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from .prompt_hooks import register_prompt_hooks
from .preview_server import register_preview_routes

register_prompt_hooks()
register_preview_routes()

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
