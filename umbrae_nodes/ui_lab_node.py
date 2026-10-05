# ui_lab_node.py -- DEV ONLY: UI design lab.
#
# Three do-nothing nodes whose panels show the same controls in different styles
# (see web/ui_lab_panels.js). They have no inputs or outputs and are never executed.
# To remove the lab: delete this file, web/ui_lab.js, web/ui_lab_panels.js, the dev/
# folder, and the "UI lab" lines in __init__.py.


class _UILabBase:
    CATEGORY = "umbrae/_dev"
    FUNCTION = "run"
    RETURN_TYPES = ()

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    def run(self):
        return ()


class UmbraeUILabCurrent(_UILabBase):
    pass


class UmbraeUILabUnified(_UILabBase):
    pass


class UmbraeUILabSkinned(_UILabBase):
    pass


NODE_CLASS_MAPPINGS = {
    "UmbraeUILabCurrent": UmbraeUILabCurrent,
    "UmbraeUILabUnified": UmbraeUILabUnified,
    "UmbraeUILabSkinned": UmbraeUILabSkinned,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "UmbraeUILabCurrent": "ui lab A - current [umbrae]",
    "UmbraeUILabUnified": "ui lab B - unified [umbrae]",
    "UmbraeUILabSkinned": "ui lab C - skinned [umbrae]",
}
