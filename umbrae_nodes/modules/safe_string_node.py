"""
safe_string_node.py — umbrae_nodes
A string change detector that also guards against non-string inputs.

On each execution:
  - If input is not a string (e.g. CLIP from a disabled node), outputs fallback
  - If input is a string but identical to the last stored value, outputs fallback
  - If input is a string and has changed, passes it through and stores it

State is keyed by ComfyUI's unique_id so multiple instances of this node
in the same workflow are automatically independent with no manual
configuration required.
"""


class SafeString:

    _last_values: dict = {}

    CATEGORY = "umbrae/text"
    FUNCTION = "safe_string"
    RETURN_TYPES = ("STRING", "BOOLEAN")
    RETURN_NAMES = ("text", "changed")

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "optional": {
                "input": ("*", {
                    "tooltip": (
                        "Any input. Non-strings, missing, and unchanged inputs "
                        "all output the fallback value. Only a changed string "
                        "passes through."
                    ),
                }),
                "fallback": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": (
                        "Output when input is absent, not a string, or unchanged. "
                        "Defaults to empty string."
                    ),
                }),
            },
            "hidden": {
                "unique_id": "UNIQUE_ID",
            },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, input_types):
        return True

    def safe_string(self, unique_id, input=None, fallback: str = ""):
        node_id = unique_id

        if not isinstance(input, str):
            print(
                f"[SafeString:{node_id}] non-string input "
                f"({type(input).__name__}) — outputting fallback"
            )
            return (fallback, False)

        last = SafeString._last_values.get(node_id)

        if input == last:
            print(f"[SafeString:{node_id}] value unchanged — outputting fallback")
            return (fallback, False)

        SafeString._last_values[node_id] = input
        print(f"[SafeString:{node_id}] value changed ({len(input)} chars) — passing through")
        return (input, True)


NODE_CLASS_MAPPINGS = {
    "SafeString": SafeString,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SafeString": "safe string [umbrae]",
}
