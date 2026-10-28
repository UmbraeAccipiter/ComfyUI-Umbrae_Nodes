# run_timer_node.py — umbrae_nodes
#
# run timer [umbrae]: a frontend-only stopwatch for the whole workflow with an
# expandable history of the last N finished runs.
#
# The clock resets when a run starts, counts up live, and freezes on the total
# when the run finishes. Under the clock a ▲ / ▼ pair grows or shrinks a list of
# previous run times (newest at the top). Everything lives in
# web/run_timer.js; this class only registers the node type.
#
# State kept on node.properties (so it travels with the workflow):
#   runTimerLastMs   frozen total of the last run
#   runTimerRows     how many history rows are shown (0 = clock only)
#   runTimerHistory  [{ms, at}, ...] newest first, finished runs only


class UmbraeRunTimer:
    """Frontend-only. No inputs, no outputs; never runs in Python."""

    DESCRIPTION = (
        "Times the whole workflow. The clock resets when you press Run, counts up "
        "while the workflow is working, and freezes on the total when it finishes.\n\n"
        "The arrows under the clock expand a history of the last runs, newest at "
        "the top (▲ shows one more run, ▼ one fewer; shift-click for five). The "
        "newest run is highlighted and the fastest one shown is marked. Right-click "
        "the node to copy the times or clear the history. Only finished runs are "
        "kept; a run you stop or that errors out is not added.\n\n"
        "Drop it anywhere on the canvas; it does not need to be wired."
    )

    CATEGORY = "umbrae/workflow"
    FUNCTION = "noop"
    RETURN_TYPES = ()
    # OUTPUT_NODE deliberately NOT set: with no outputs and no OUTPUT_NODE flag,
    # ComfyUI leaves this node out of the prompt entirely, so it never runs and
    # never draws an execution badge. It is a pure frontend control.

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {}}

    def noop(self):
        return ()


NODE_CLASS_MAPPINGS = {
    "UmbraeRunTimer": UmbraeRunTimer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "UmbraeRunTimer": "run timer [umbrae]",
}
