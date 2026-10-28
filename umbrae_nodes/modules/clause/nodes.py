# umbrae_nodes/modules/clause/nodes.py — umbrae_nodes v0.8.8
# "wildcard clause expander [umbrae]": ComfyUI-WildcardClause's node running on
# the umbrae wildcard engine (seeded picks, {a|b}, switches, variables, cycles,
# relative tags, folder calls, recursion guard, [[aspect]] ...).

from .. import umbrae_wildcards as wildcards
from .clause_expand import expand_with_overrides
from .contract import OVERRIDE_FIELDS, OVERRIDE_INPUT_KEYS
from .prompt_hooks import CLASS_NAME


def _override_string(field):
    return (
        "STRING",
        {
            "multiline": True,
            "default": "",
            "tooltip": f"Example: {field.example}",
        },
    )


class UmbraeWildcardClauseExpander:
    DESCRIPTION = (
        "Wildcard expand with scene-leaf / character-atom overrides, on the umbrae "
        "wildcard engine. populate = expand wildcard_text on queue; fixed = use "
        "populated_text as written. Overrides replace the wildcard key whose path "
        "matches the slot (…/leaf/<scene>/wardrobe, …/common/hair/…, see the "
        "WildcardClause README). Precedence: wardrobe beats jewelry."
    )

    @classmethod
    def INPUT_TYPES(cls):
        optional = {field.id: _override_string(field) for field in OVERRIDE_FIELDS}
        return {
            "required": {
                "wildcard_text": ("STRING", {"multiline": True, "dynamicPrompts": False}),
                "populated_text": (
                    "STRING",
                    {
                        "multiline": True,
                        "dynamicPrompts": False,
                        "tooltip": (
                            "Expanded prompt shown after queue in populate mode. "
                            "Edit only in fixed mode."
                        ),
                    },
                ),
                "mode": (["populate", "fixed"], {"default": "populate"}),
                "seed": (
                    "INT",
                    {
                        "default": 0,
                        "min": 0,
                        "max": 0xFFFFFFFFFFFFFFFF,
                        "control_after_generate": True,
                    },
                ),
            },
            "optional": optional,
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("populated_text",)
    FUNCTION = "expand"
    CATEGORY = "umbrae/text"

    def expand(self, wildcard_text, populated_text, mode, seed, unique_id=None, **overrides):
        source = wildcard_text if mode == "populate" else populated_text
        kwargs = {key: overrides.get(key) or "" for key in OVERRIDE_INPUT_KEYS}
        scope = (CLASS_NAME, str(unique_id)) if unique_id is not None else None
        out = expand_with_overrides(source, seed, engine_kwargs={"cycle_scope": scope}, **kwargs)
        out = wildcards.finalize_output(out)        # \n line breaks, \& literal
        out = wildcards.strip_aspect_markers(out)   # typed [W:H] overrides are not prompt text
        return (out,)


NODE_CLASS_MAPPINGS = {
    CLASS_NAME: UmbraeWildcardClauseExpander,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    CLASS_NAME: "wildcard clause expander [umbrae]",
}
