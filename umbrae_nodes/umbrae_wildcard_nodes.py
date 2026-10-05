# umbrae_wildcard_nodes.py — umbrae_nodes v0.8.6
#
# "wildcard processor [umbrae]" - port of Impact Pack's ImpactWildcardProcessor
# (GPL-3.0, see umbrae_wildcards.py) with a `runs` countdown.
#
# Countdown: the first execution of a series loads it with `runs`; every
# execution counts down one. The frontend (web/umbrae_wildcards.js) queues the
# next run only after the current one FINISHES successfully, and ends the
# series on cancel / interrupt / error. Series and cycle state live in memory
# and clear on a ComfyUI restart or with the node's Reset button.

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
        "{!find=replace} replaces whole words last (case follows the text); {!!find=replace} is exact-case. "
        "\\n in text becomes a line break.\n\n"
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
             switches="", unique_id=None, **kwargs):
        scope = _scope(unique_id)
        text = wildcards.process(text=populated_text or "", seed=seed, cycle_scope=scope,
                                 switches=switches if isinstance(switches, str) else "")
        if mode == "populate" and (populated_text or "") == (wildcard_text or ""):
            # the queue-time populate handed over the raw prompt (seed from a
            # computing node): show the resolved prompt in populated_text
            _send_feedback(unique_id, "populated_text", text)
        text = wildcards.finalize_output(text)      # \n line breaks, \& literal

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
