# umbrae_nodes/modules/expander/nodes.py — umbrae_nodes v0.9.0
# "wildcard expander [umbrae]": one wildcard prompt -> N prompts over a seed
# plan, every draw pinnable / skippable from the node's panel, prompts out as a
# list (one downstream run per prompt) and as one joined string.

from .. import umbrae_wildcards as wildcards
from ..umbrae_wildcard_nodes import _image_size
from .expand import (
    CLASS_NAME, FEEDBACK_EVENT, MAX_COUNT, expand_batch, parse_edits, parse_settings,
    seed_plan, split_fixed,
)


def _scope(unique_id):
    return (CLASS_NAME, str(unique_id if unique_id is not None else ""))


def _send_feedback(node_id, payload):
    try:
        from server import PromptServer
        PromptServer.instance.send_sync(FEEDBACK_EVENT, {"node_id": str(node_id), **payload})
    except Exception:
        pass


class UmbraeWildcardExpander:
    DESCRIPTION = (
        "Wildcard expander (umbrae): expands one wildcard prompt into `count` prompts, one per "
        "seed of the seed plan (seed, seed+step, ... or seeds derived from the seed).\n\n"
        "The panel shows every draw the engine made for each prompt (which line of which "
        "wildcard) and lets you pin it, pick another line, reroll it, skip it or type your own "
        "text; edits are stored by wildcard key + occurrence, so they apply to every prompt of "
        "the batch and to the run. Browse your whole wildcard collection from the Collection "
        "panel and insert tags or pins from there.\n\n"
        "mode populate: expand `text` when the node runs. fixed: use the prompts in fixed_text "
        "as written (separate prompts with a line that is only ---).\n\n"
        "Outputs: prompts (a LIST - downstream nodes run once per prompt), joined (one string, "
        "separator from the Output panel), count, seeds (list, aligned with prompts). All "
        "wildcard syntax of the wildcard processor works (switches, variables, cycles, pins, "
        "[[aspect]] with the latent / width / height inputs)."
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"multiline": True, "dynamicPrompts": False,
                                    "tooltip": "Prompt using wildcard syntax (__tags__, {a|b}, switches, variables ...)."}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffffffffffff,
                                 "control_after_generate": True,
                                 "tooltip": "First seed of the batch."}),
                "count": ("INT", {"default": 1, "min": 1, "max": MAX_COUNT,
                                  "tooltip": "How many prompts to produce."}),
                "mode": (["populate", "fixed"], {
                    "default": "populate",
                    "tooltip": "populate: expand `text` on every run. fixed: use fixed_text as written (prompts separated by a --- line)."}),
            },
            "optional": {
                "fixed_text": ("STRING", {"multiline": True, "default": "", "dynamicPrompts": False,
                                          "tooltip": "The prompts used in fixed mode, separated by a line that is only ---."}),
                "switches": ("STRING", {"multiline": True, "default": "", "dynamicPrompts": False,
                                        "tooltip": "Switch values, e.g.  gend=2, hair=4  (see the wildcard processor)."}),
                "edits": ("STRING", {"multiline": True, "default": "", "dynamicPrompts": False,
                                     "tooltip": "Pinned / skipped / replaced draws, as JSON (managed by the panel)."}),
                "settings": ("STRING", {"multiline": True, "default": "", "dynamicPrompts": False,
                                        "tooltip": "Seed plan and output options, as JSON (managed by the panel)."}),
                "latent": ("LATENT", {"tooltip": "Image size for [[aspect]] and the [ratio] / [orientation] tokens."}),
                "width": ("INT", {"forceInput": True, "default": 0, "min": 0, "max": 16384,
                                  "tooltip": "Image width, when no latent is connected."}),
                "height": ("INT", {"forceInput": True, "default": 0, "min": 0, "max": 16384,
                                   "tooltip": "Image height, when no latent is connected."}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    RETURN_TYPES = ("STRING", "STRING", "INT", "INT")
    RETURN_NAMES = ("prompts", "joined", "count", "seeds")
    OUTPUT_IS_LIST = (True, False, False, True)
    OUTPUT_TOOLTIPS = (
        "The prompts, as a list: nodes connected here run once per prompt.",
        "All prompts in one string (separator from the Output panel).",
        "Number of prompts.",
        "The seed each prompt was made with (list, aligned with prompts).",
    )
    FUNCTION = "doit"
    CATEGORY = "umbrae/text"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        if wildcards.cycle_is_changed(kwargs.get("text"), _scope(kwargs.get("unique_id"))):
            return float("nan")
        return False

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        return True

    def doit(self, text="", seed=0, count=1, mode="populate", fixed_text="", switches="",
             edits="", settings="", latent=None, width=0, height=0, unique_id=None, **kwargs):
        cfg = parse_settings(settings)
        size = _image_size(latent, width, height)
        aspect = wildcards.aspect_config(*size) if size else {}
        if mode == "fixed":
            prompts = split_fixed(fixed_text)
            plan = seed_plan(seed, cfg)
            seeds = [next(plan) for _ in prompts]
        else:
            res = expand_batch(text, seed, count, switches=switches, edits=parse_edits(edits),
                               settings=cfg, cycle_scope=_scope(unique_id), aspect=aspect,
                               aspect_final=True, want_trees=False)
            prompts = [p["text"] for p in res["prompts"]]
            seeds = res["seeds"]
            if unique_id is not None:
                _send_feedback(unique_id, {"prompts": prompts, "seeds": seeds, "notes": res["notes"]})
        joined = cfg["joiner"].join(prompts)
        return (prompts, joined, len(prompts), seeds)


NODE_CLASS_MAPPINGS = {CLASS_NAME: UmbraeWildcardExpander}
NODE_DISPLAY_NAME_MAPPINGS = {CLASS_NAME: "wildcard expander [umbrae]"}
