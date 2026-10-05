# umbrae_wildcard_server.py — umbrae_nodes v0.8.6
#
# Server side of "wildcard processor [umbrae]": HTTP routes and the queue-time
# populate hook. Ported from Impact Pack's impact_server.py (GPL-3.0, see
# umbrae_wildcards.py); every route / event / class name is umbrae-specific so
# this runs alongside Impact Pack without clashing.
#
# Routes:
#   GET  /umbrae/wildcards/list          wildcard names for the picker
#   GET  /umbrae/wildcards/list/loaded   + on-demand status
#   GET  /umbrae/wildcards/refresh       reload wildcard files from disk
#   POST /umbrae/wildcards/reset         {"node_id": id}  clear cycles + countdown
#   POST /umbrae/wildcards/series_end    {"node_id": id|null}  end countdown(s)
# Event: "umbrae-wildcard-feedback" {node_id, widget_name, value}

import logging

from . import umbrae_wildcards as wildcards
from .umbrae_wildcard_nodes import CLASS_NAME, end_series


def _find_input_value(input_node, prompt, input_type=int, input_keys=('value',)):
    """Follow a linked seed back to a literal value (from Impact's helper)."""
    input_val = None
    try:
        for n in input_keys:
            input_val = input_node['inputs'].get(n, None)
            if isinstance(input_val, input_type):
                break
            elif isinstance(input_val, list) and len(input_val):
                input_val = _find_input_value(prompt[input_val[0]], prompt=prompt,
                                              input_type=input_type, input_keys=input_keys)
                if input_val is not None:
                    break
    except Exception as e:
        logging.warning(f"[umbrae wildcards] Error finding {input_type} value - {e}")
    return input_val


# Nodes whose STRING output is exactly their typed widget value, so a linked
# `switches` box can be read when Run is pressed. Anything else (a node that
# computes text) -> switch groups are deferred to execution time.
_LITERAL_TEXT_CLASSES = {
    "PrimitiveNode", "PrimitiveString", "PrimitiveStringMultiline",
    "String Literal", "Text Multiline", "StringConstant", "StringConstantMultiline",
}


def _resolve_switches_input(value, prompt):
    """-> (switches_text_or_None, defer)."""
    if value is None:
        return "", False
    if isinstance(value, str):
        return value, False
    if isinstance(value, list) and value:
        try:
            src = prompt[value[0]]
            if src.get('class_type') in _LITERAL_TEXT_CLASSES:
                for key in ('value', 'text', 'string'):
                    v = src['inputs'].get(key)
                    if isinstance(v, str):
                        return v, False
        except Exception:
            pass
        return None, True
    return "", False


def populate_prompt(json_data, send=None):
    """Queue-time populate for every umbrae wildcard processor in the prompt.
    `send(event, data)` pushes widget updates to the frontend (None = don't).

    v0.8.5: the mode is no longer flipped to 'reproduce' (in the prompt or in
    the workflow saved with images). Saved images keep the populated text in
    populated_text, so it can be copied or used with mode = fixed, but loading
    an image regenerates from wildcard_text. A seed that cannot be read at
    queue time (linked to a computing node) no longer skips the node: the raw
    wildcard_text is handed to the node, which resolves it when it runs."""
    prompt = json_data['prompt']
    updated_widget_values = {}

    for k, v in prompt.items():
        if v.get('class_type') != CLASS_NAME:
            continue
        inputs = v['inputs']

        if isinstance(inputs.get('mode'), bool):          # legacy adapter
            inputs['mode'] = 'populate' if inputs['mode'] else 'fixed'

        if inputs.get('mode') == 'populate' and isinstance(inputs.get('populated_text'), str):
            seed_in = inputs.get('seed', 0)
            input_seed = None
            if isinstance(seed_in, list):
                try:
                    input_node = prompt[seed_in[0]]
                    if input_node['class_type'] == 'ImpactInt':
                        input_seed = int(input_node['inputs']['value'])
                    elif input_node['class_type'] == 'Seed (rgthree)':
                        input_seed = int(input_node['inputs']['seed'])
                    else:
                        input_seed = _find_input_value(input_node, prompt=prompt, input_type=int,
                                                       input_keys=('int', 'seed', 'value'))
                except Exception:
                    input_seed = None
            else:
                try:
                    input_seed = int(seed_in)
                except (TypeError, ValueError):
                    input_seed = None

            if input_seed is None:
                # Seed only exists at run time: let the node resolve the prompt
                # itself (doit processes populated_text with the real seed).
                logging.warning("[umbrae wildcards] seed comes from a node that computes it - node "
                                f"{k}: the prompt is resolved when the node runs (populated_text is "
                                "updated then).")
                inputs['populated_text'] = inputs.get('wildcard_text', '')
                continue

            box, defer = _resolve_switches_input(inputs.get('switches', ''), prompt)
            inputs['populated_text'] = wildcards.process(inputs['wildcard_text'], input_seed,
                                                         cycle_scope=(CLASS_NAME, str(k)),
                                                         switches=box, defer_switches=defer)
            if send:
                send("umbrae-wildcard-feedback", {"node_id": k, "widget_name": "populated_text",
                                                  "value": inputs['populated_text']})
            updated_widget_values[k] = inputs['populated_text']

        elif inputs.get('mode') == 'reproduce' and send:
            # chosen by hand: use populated_text once, then back to populate
            send("umbrae-wildcard-feedback", {"node_id": k, "widget_name": "mode", "value": 'populate'})

    # Store the populated text in the workflow saved with the images (widgets:
    # 0 wildcard_text, 1 populated_text, 2 mode). The mode is left as it is.
    match json_data:
        case {"extra_data": {"extra_pnginfo": {"workflow": {"nodes": nodes}}}}:
            for node in nodes:
                match node:
                    case {"id": id, "widgets_values": widgets_values}:
                        key = str(id)
                        if key in updated_widget_values and isinstance(widgets_values, list) and len(widgets_values) > 1:
                            widgets_values[1] = updated_widget_values[key]
    return json_data


def _register():
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception as e:
        logging.warning(f"[umbrae wildcards] server not available ({e}); routes and populate disabled.")
        return False

    routes = PromptServer.instance.routes

    def send(event, data):
        PromptServer.instance.send_sync(event, data)

    @routes.get("/umbrae/wildcards/list")
    async def _list(request):
        return web.json_response({'data': wildcards.get_wildcard_list()})

    @routes.get("/umbrae/wildcards/list/loaded")
    async def _list_loaded(request):
        on_demand = wildcards.is_on_demand_mode()
        return web.json_response({
            'data': wildcards.get_loaded_wildcard_list(),
            'on_demand_mode': on_demand,
            'total_available': len(wildcards.available_wildcards) if on_demand else len(wildcards.wildcard_dict),
        })

    @routes.get("/umbrae/wildcards/refresh")
    async def _refresh(request):
        logging.info("[umbrae wildcards] Manual refresh: reloading wildcard files from disk.")
        wildcards.wildcard_load()
        on_demand = wildcards.is_on_demand_mode()
        count = len(wildcards.available_wildcards) if on_demand else len(wildcards.wildcard_dict)
        return web.json_response({'status': 'ok', 'count': count, 'on_demand_mode': on_demand})

    @routes.post("/umbrae/wildcards/reset")
    async def _reset(request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        node_id = data.get('node_id')
        n = wildcards.reset_cycles(node_id)
        s = end_series(node_id)
        logging.info(f"[umbrae wildcards] Reset node {node_id}: {n} cycle state(s), {s} countdown(s) cleared.")
        return web.json_response({'status': 'ok', 'cycles_cleared': n, 'series_cleared': s})

    @routes.post("/umbrae/wildcards/series_end")
    async def _series_end(request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        s = end_series(data.get('node_id'))
        return web.json_response({'status': 'ok', 'series_cleared': s})

    def onprompt(json_data):
        try:
            populate_prompt(json_data, send)
        except Exception:
            logging.exception("[umbrae wildcards] Error in queue-time populate.")
        return json_data

    PromptServer.instance.add_on_prompt_handler(onprompt)
    return True


wildcards.wildcard_load()
_register()
