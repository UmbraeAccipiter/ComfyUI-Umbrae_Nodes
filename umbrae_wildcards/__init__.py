# __init__.py - umbrae_wildcards v0.9.6 (standalone "wildcard processor [umbrae]")
# Generated from the umbrae_nodes pack by dev/build_standalone.py - do not edit here.
#
# Layout: modules/ = engine + node + server routes, web/ = front-end (node UI and
# syntax colours), wildcards/ + wildcard_examples/ = wildcard roots,
# umbrae_wildcard_syntax.* = cheat sheets.
# Do not install this next to the full umbrae_nodes pack: both contain this node.

from .modules.umbrae_wildcard_nodes import UmbraeWildcardProcessor
from .modules import umbrae_wildcard_server  # noqa: F401  (loads wildcards, registers routes + populate hook)

WEB_DIRECTORY = "./web"

NODE_CLASS_MAPPINGS = {
    "UmbraeWildcardProcessor": UmbraeWildcardProcessor,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "UmbraeWildcardProcessor": "wildcard processor [umbrae]",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
