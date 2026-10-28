# umbrae_nodes/modules/expander — umbrae_nodes v0.9.0
# "wildcard expander [umbrae]": batch expansion with per-draw pins on the
# umbrae wildcard engine. See README.md in this folder.

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS
from .server import register as _register_routes

_register_routes()

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
