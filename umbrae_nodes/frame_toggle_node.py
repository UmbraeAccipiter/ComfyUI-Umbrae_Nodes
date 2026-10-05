# frame_toggle_node.py — umbrae_nodes
#
# Two nodes that work together to let you toggle groups of nodes on/off
# by frame (group), without listing the entire workflow.
#
# UmbraeFrameMarker  — drop one inside a frame and rename it.
# UmbraeFrameToggleController — place anywhere; shows a toggle row for
#                               every marker found in the workflow.
#
# All interaction logic lives in web/frame_toggle_node.js.
# These Python classes exist only to register the node types with ComfyUI.


class UmbraeFrameMarker:
    """
    A named marker node. Drop it inside a ComfyUI group/frame and rename
    it to whatever you want that frame's toggle to be labelled.
    The Frame Toggle Controller finds it by type and reads its title.
    """
    CATEGORY = "umbrae/workflow"
    FUNCTION = "run"
    OUTPUT_NODE = True
    RETURN_TYPES = ()

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    def run(self):
        return ()


class UmbraeFrameToggleController:
    """
    Place anywhere in the workflow (outside the frames you want to control).
    Renders a live list of every UmbraeFrameMarker in the workflow with:
      - a toggle switch to mute/unmute all nodes in that frame
      - an arrow button to pan + zoom the canvas to that frame
    Toggle states are saved with the workflow.
    """
    CATEGORY = "umbrae/workflow"
    FUNCTION = "run"
    OUTPUT_NODE = True
    RETURN_TYPES = ()

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    def run(self):
        return ()


NODE_CLASS_MAPPINGS = {
    "UmbraeFrameMarker": UmbraeFrameMarker,
    "UmbraeFrameToggleController": UmbraeFrameToggleController,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "UmbraeFrameMarker": "frame marker [umbrae]",
    "UmbraeFrameToggleController": "frame toggle controller [umbrae]",
}
