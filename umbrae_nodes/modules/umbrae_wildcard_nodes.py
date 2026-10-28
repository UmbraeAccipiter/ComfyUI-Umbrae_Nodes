# umbrae_wildcard_nodes.py — umbrae_nodes v0.8.7
#
# "wildcard processor [umbrae]" - port of Impact Pack's ImpactWildcardProcessor
# (GPL-3.0, see umbrae_wildcards.py) with a `runs` countdown.
#
# Countdown: the first execution of a series loads it with `runs`; every
# execution counts down one. The frontend (web/umbrae_wildcards.js) queues the
# next run only after the current one FINISHES successfully, and ends the
# series on cancel / interrupt / error. Series and cycle state live in memory
# and clear on a ComfyUI restart or with the node's Reset button.
#
# Aspect (v0.8.7): the node reads the image size from its optional latent /
# width / height inputs and adapts the text to it: [[aspect]] inserts a line
# from __aspect/[orientation]__ (defaults ship in wildcard_examples/aspect/; a
# same-named file in wildcards/ overrides); [orientation] [ratio] [width]
# [height] tokens are filled anywhere. See umbrae_wildcards.py.

import threading

from . import umbrae_wildcards as wildcards

CLASS_NAME = "UmbraeWildcardProcessor"
WILDCARD_LABEL = "Select the Wildcard to add to the text"

_series_lock = threading.Lock()
_series = {}   # scope -> {"total": int, "remaining": int}


def _scope(unique_id):
    return (CLASS_NAME, str(unique_id if unique_id is not None else ""))


def end_series(node_id=None):
    """End the runs countdown for one node (or all when node_id is None)."""
    with _series_lock:
        keys = [k for k in _series if wildcards._scope_matches(k, node_id)]
        for k in keys:
            del _series[k]
    return len(keys)


def _send_feedback(node_id, widget_name, value):
    try:
        from server import PromptServer
        PromptServer.instance.send_sync("umbrae-wildcard-feedback",
                                        {"node_id": str(node_id), "widget_name": widget_name, "value": value})
    except Exception:
        pass


def _image_size(latent, width, height):
    """(width, height) in pixels from a connected latent (shape [..., H/8, W/8]),
    else from the width / height inputs; None when nothing usable is connected."""
    try:
        if latent is not None:
            shape = latent["samples"].shape
            w, h = int(shape[-1]) * 8, int(shape[-2]) * 8
            if w > 0 and h > 0:
                return w, h
    except Exception:
        pass
    try:
        w, h = int(width), int(height)
        if w > 0 and h > 0:
            return w, h
    except (TypeError, ValueError):
        pass
    return None


def _series_active(scope):
    with _series_lock:
        st = _series.get(scope)
        return bool(st and st["remaining"] > 0)


class UmbraeWildcardProcessor:
    DESCRIPTION = (
        "Wildcard Processor (umbrae) - processes wildcard syntax into a prompt.\n\n"
        "Modes: populate (fill populated_text from wildcard_text at queue time), "
        "fixed (use populated_text as written), reproduce (fixed once, then populate).\n\n"
        "Persistent groups: {a^b^c} shuffled bag, {-::a^b^c} written order, "
        "{N+::a|b|c} no repeat of the last N items. '-::' with '|' = written order "
        "within the run (use with a count). {-::__file__} steps through a wildcard "
        "file in order.\n\n"
        "runs: queue this workflow X times; the next run is queued only after the "
        "previous one finishes, and cancel / interrupt / error stops the series. "
        "Reset clears this node's cycles, histories and countdown.\n\n"
        "Switches: {&name=2} defines, {&name:a|b|c} picks option 2; the switches box "
        "overrides; an undefined switch picks one random option, shared by all its groups. "
        "Overrides: {@!name=...} / {&!name=...} beat any other definition (also inside wildcard files). "
        "{!find=replace} replaces whole words last (case follows the text); {!!find=replace} is exact-case, written as typed; {!!!find=replace} matches any case but writes as typed. "
        "\\n in text becomes a line break.\n\n"
        "Aspect: connect the latent (or width + height) the image is made from; [[aspect]] in the "
        "text then inserts a description for that orientation on its own line, from "
        "__aspect/[orientation]__ (aspect/horizontal, vertical or square; defaults ship in "
        "wildcard_examples/, copy one into wildcards/ to edit it). Tokens [orientation] [ratio] "
        "[width] [height] are filled anywhere in the text.\n\n"
        "Wildcards are read from umbrae_nodes/wildcards and Impact Pack's custom "
        "wildcards folder (umbrae wins on duplicate names)."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "wildcard_text": ("STRING", {"multiline": True, "dynamicPrompts": False,
                                             "tooltip": "Prompt using wildcard syntax."}),
                "populated_text": ("STRING", {"multiline": True, "dynamicPrompts": False,
                                              "tooltip": "The text actually used for the run. Filled automatically in populate mode."}),
                "mode": (["populate", "fixed", "reproduce"], {
                    "default": "populate",
                    "tooltip": (
                        "populate: overwrite populated_text from wildcard_text before each run (read-only, copyable).\n"
                        "fixed: ignore wildcard_text and use populated_text as written.\n"
                        "reproduce: use populated_text once as-is, then switch to populate (manual choice only; loading an image does not set it - use fixed to re-create an image's exact prompt)."
                    ),
                }),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff,
                                 "tooltip": "Random seed for wildcard processing."}),
                "runs": ("INT", {"default": 1, "min": 1, "max": 100000,
                                 "tooltip": (
                                     "Number of runs for this series. 1 = normal single run. "
                                     "The next run is queued after the previous one finishes; "
                                     "cancel / interrupt / error stops the series."
                                 )}),
                "Select to add Wildcard": ([WILDCARD_LABEL],),
            },
            "optional": {
                "switches": ("STRING", {
                    "multiline": True, "default": "", "dynamicPrompts": False,
                    "tooltip": (
                        "Switch values, e.g.  gend=2, hair=4  or  {&gend=2}{&hair=4}  (any mix, "
                        "commas or new lines). Overrides same-named {&name=...} definitions in the "
                        "prompt. Typed here or from a Primitive / plain text node: resolved when you "
                        "press Run. From a node that computes text: switch groups are resolved when "
                        "this node executes (populated_text then still shows them)."
                    ),
                }),
                "latent": ("LATENT", {
                    "tooltip": "The latent the image is generated from: its size drives [[aspect]] and the [ratio] / [orientation] tokens.",
                }),
                "width": ("INT", {
                    "forceInput": True, "default": 0, "min": 0, "max": 16384,
                    "tooltip": "Image width, when no latent is connected.",
                }),
                "height": ("INT", {
                    "forceInput": True, "default": 0, "min": 0, "max": 16384,
                    "tooltip": "Image height, when no latent is connected.",
                }),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("STRING", "INT", "INT")
    RETURN_NAMES = ("processed text", "run_index", "runs_remaining")
    OUTPUT_TOOLTIPS = (
        "The processed prompt.",
        "Which run of the series this is (1..runs).",
        "Runs left after this one (0 = last run).",
    )
    FUNCTION = "doit"
    CATEGORY = "umbrae/text"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        scope = _scope(kwargs.get("unique_id"))
        if wildcards.cycle_is_changed(kwargs.get("populated_text"), scope):
            return float("nan")
        try:
            runs = int(kwargs.get("runs", 1))
        except (TypeError, ValueError):
            runs = 2          # unresolved / linked value: assume a series
        if runs > 1 or _series_active(scope):
            return float("nan")
        return False

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        # the wildcard picker combo always serializes its label, but be lenient
        return True

    def doit(self, wildcard_text="", populated_text="", mode="populate", seed=0, runs=1,
             switches="", latent=None, width=0, height=0, unique_id=None, **kwargs):
        scope = _scope(unique_id)
        size = _image_size(latent, width, height)
        aspect = wildcards.aspect_config(*size) if size else {}
        text = wildcards.process(text=populated_text or "", seed=seed, cycle_scope=scope,
                                 switches=switches if isinstance(switches, str) else "",
                                 aspect=aspect, aspect_final=True)
        if mode == "populate" and text != (populated_text or ""):
            # the queue-time populate handed over the raw prompt (seed from a
            # computing node), or left [[aspect]] / tokens for the real size:
            # show the resolved prompt in populated_text
            _send_feedback(unique_id, "populated_text", text)
        text = wildcards.finalize_output(text)      # \n line breaks, \& literal
        text = wildcards.strip_aspect_markers(text)  # typed [W:H] overrides are not prompt text

        try:
            runs = max(1, int(runs))
        except (TypeError, ValueError):
            runs = 1
        with _series_lock:
            st = _series.get(scope)
            if st is None or st["remaining"] <= 0:
                st = {"total": runs, "remaining": runs}
            run_index = st["total"] - st["remaining"] + 1
            st["remaining"] -= 1
            remaining = st["remaining"]
            if remaining > 0:
                _series[scope] = st
            else:
                _series.pop(scope, None)

        return {
            "ui": {"umbrae_runs": [int(remaining), int(run_index), int(st["total"])]},
            "result": (text, int(run_index), int(remaining)),
        }


NODE_CLASS_MAPPINGS = {CLASS_NAME: UmbraeWildcardProcessor}
NODE_DISPLAY_NAME_MAPPINGS = {CLASS_NAME: "wildcard processor [umbrae]"}
