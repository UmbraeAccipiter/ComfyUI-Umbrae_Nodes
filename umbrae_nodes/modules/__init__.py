# umbrae_nodes/modules — all node / engine code lives here (v0.8.8 layout).
# The pack root keeps only __init__.py (registration), web/, wildcards/,
# wildcard_examples/, dev/ and the syntax cheat sheets, so users can find the
# folders they are meant to touch. Modules import each other relatively
# (from . import x); clause/ reaches the engine with `from .. import umbrae_wildcards`.
