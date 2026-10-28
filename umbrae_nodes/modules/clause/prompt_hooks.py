# umbrae_nodes/modules/clause/prompt_hooks.py — umbrae_nodes v0.8.8
# Ported from ComfyUI-WildcardClause (prompt_hooks.py) to run on the umbrae wildcard
# engine (umbrae_wildcards.py) instead of Impact Pack's. Routes live under
# /umbrae/clause/, the node is UmbraeWildcardClauseExpander, the feedback event
# is umbrae-clause-feedback, so it runs alongside the original package.
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

from .clause_expand import expand_with_overrides
from .contract import OVERRIDE_INPUT_KEYS

CLASS_NAME = "UmbraeWildcardClauseExpander"
FEEDBACK_EVENT = "umbrae-clause-feedback"


def _find_input_value(input_node, prompt, input_type=int, input_keys=("value",)):
    input_val = None
    try:
        for n in input_keys:
            input_val = input_node["inputs"].get(n, None)
            if isinstance(input_val, input_type):
                break
            if isinstance(input_val, list) and len(input_val):
                input_val = _find_input_value(
                    prompt[input_val[0]],
                    prompt=prompt,
                    input_type=input_type,
                    input_keys=input_keys,
                )
                if input_val is not None:
                    break
    except Exception as e:
        logger.warning("[umbrae clause] Error resolving linked input: %s", e)
        return None
    return input_val


def _resolve_string_input(inputs, key, prompt):
    value = inputs.get(key)
    if isinstance(value, str):
        return value
    if isinstance(value, list) and len(value):
        try:
            upstream = prompt[value[0]]
            resolved = _find_input_value(
                upstream,
                prompt=prompt,
                input_type=str,
                input_keys=("text", "string", "wildcard_text", "value", "populated_text"),
            )
            if isinstance(resolved, str):
                return resolved
            # Some string nodes expose the value under the same key name.
            for candidate in ("text", "string", "wildcard_text", "value", "populated_text"):
                raw = upstream.get("inputs", {}).get(candidate)
                if isinstance(raw, str):
                    return raw
        except Exception as e:
            logger.warning("[umbrae clause] Could not resolve linked %s: %s", key, e)
    return None


def _resolve_seed(inputs, prompt):
    seed_val = inputs.get("seed")
    if isinstance(seed_val, list):
        try:
            input_node = prompt[seed_val[0]]
            class_type = input_node.get("class_type", "")
            if class_type == "ImpactInt":
                return int(input_node["inputs"]["value"])
            if class_type == "Seed (rgthree)":
                return int(input_node["inputs"]["seed"])
            resolved = _find_input_value(
                input_node,
                prompt=prompt,
                input_type=int,
                input_keys=("int", "seed", "value"),
            )
            if resolved is None:
                logger.info(
                    "[umbrae clause] Only ImpactInt, Seed (rgthree), and Primitive "
                    "are supported as linked seed; skipping populate feedback."
                )
                return None
            return int(resolved)
        except Exception:
            return None
    try:
        return int(seed_val)
    except Exception:
        return None


def _override_kwargs(inputs, prompt):
    kwargs = {}
    for key in OVERRIDE_INPUT_KEYS:
        value = inputs.get(key, "")
        if isinstance(value, list):
            resolved = _resolve_string_input(inputs, key, prompt)
            kwargs[key] = resolved if isinstance(resolved, str) else ""
        else:
            kwargs[key] = value or ""
    return kwargs


def onprompt_populate_wildcard_clause(json_data):
    """Queue-time populate for every clause expander in the prompt (populate mode)."""
    try:
        from server import PromptServer
    except Exception:
        return json_data

    prompt = json_data.get("prompt") or {}
    updated_widget_values = {}

    for k, v in prompt.items():
        if v.get("class_type") != CLASS_NAME:
            continue
        inputs = v.get("inputs") or {}
        mode = inputs.get("mode", "populate")
        if isinstance(mode, bool):
            mode = "populate" if mode else "fixed"
            inputs["mode"] = mode

        if mode != "populate":
            continue
        if not isinstance(inputs.get("populated_text"), str):
            continue

        wildcard_text = _resolve_string_input(inputs, "wildcard_text", prompt)
        if wildcard_text is None:
            continue

        input_seed = _resolve_seed(inputs, prompt)
        if input_seed is None:
            continue

        try:
            populated = expand_with_overrides(
                wildcard_text,
                input_seed,
                **_override_kwargs(inputs, prompt),
            )
        except Exception:
            logger.exception("[umbrae clause] onprompt expand failed for node %s", k)
            continue

        inputs["populated_text"] = populated
        updated_widget_values[k] = populated
        try:
            PromptServer.instance.send_sync(
                FEEDBACK_EVENT,
                {
                    "node_id": k,
                    "widget_name": "populated_text",
                    "type": "STRING",
                    "value": populated,
                },
            )
        except Exception:
            logger.exception("[umbrae clause] send_sync feedback failed for node %s", k)

    match json_data:
        case {"extra_data": {"extra_pnginfo": {"workflow": {"nodes": nodes}}}}:
            for node in nodes:
                match node:
                    case {"id": node_id, "widgets_values": widgets_values}:
                        key = str(node_id)
                        if key in updated_widget_values and isinstance(widgets_values, list) and len(widgets_values) > 1:
                            widgets_values[1] = updated_widget_values[key]

    return json_data


def register_prompt_hooks():
    try:
        from server import PromptServer
    except Exception:
        logger.info("[umbrae clause] PromptServer unavailable; skipping onprompt hook")
        return
    PromptServer.instance.add_on_prompt_handler(onprompt_populate_wildcard_clause)
