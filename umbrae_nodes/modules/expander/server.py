# umbrae_nodes/modules/expander/server.py — umbrae_nodes v0.9.0
#
# Routes for the wildcard expander panel. The handle_* functions are plain
# (dict in, dict out) so dev/expander_dev_server.py can serve the same panel
# without ComfyUI.
#
#   GET  /umbrae/expander/tree                    the whole collection as a folder tree
#   GET  /umbrae/expander/entries?tag=&offset=&limit=&q=   lines of one tag, with indexes
#   POST /umbrae/expander/expand {text, seed, count, switches, edits, settings, node_id}
#        -> {prompts: [{seed, text, notes, draws}], seeds, notes}   (never advances cycles)
#   (reload files: GET /umbrae/wildcards/refresh from the wildcard processor)
# Event: "umbrae-expander-feedback" {node_id, prompts, seeds, notes} after a run.

import logging

from .. import umbrae_wildcards as wildcards
from .catalog import collection_tree, entries
from .expand import MAX_COUNT, expand_batch, parse_edits, parse_settings

logger = logging.getLogger(__name__)


def handle_tree() -> dict:
    return collection_tree()


def handle_entries(query: dict) -> dict:
    return entries(query.get("tag") or query.get("key") or "", query.get("offset") or 0,
                   query.get("limit") or 60, query.get("q") or "")


def handle_expand(data: dict) -> dict:
    text = data.get("text") or ""
    try:
        seed = int(data.get("seed") or 0)
    except (TypeError, ValueError):
        seed = 0
    try:
        count = max(1, min(MAX_COUNT, int(data.get("count") or 1)))
    except (TypeError, ValueError):
        count = 1
    scope_id = f"expander-preview-{data.get('node_id', '')}"
    scope = ("UmbraeWildcardExpanderPreview", scope_id)
    aspect = {}
    try:
        w, h = int(data.get("width") or 0), int(data.get("height") or 0)
        if w > 0 and h > 0:
            aspect = wildcards.aspect_config(w, h)
    except (TypeError, ValueError):
        pass
    wildcards.reset_cycles(scope_id)               # a preview never advances real cycles
    try:
        res = expand_batch(text, seed, count, switches=data.get("switches") or "",
                           edits=parse_edits(data.get("edits")), settings=parse_settings(data.get("settings")),
                           cycle_scope=scope, aspect=aspect, aspect_final=bool(aspect),
                           want_trees=bool(data.get("trees", True)))
    finally:
        wildcards.reset_cycles(scope_id)
    res.pop("edits", None)
    res["status"] = "ok"
    return res


def register():
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception as e:
        logger.info(f"[umbrae expander] PromptServer unavailable ({e}); routes disabled.")
        return False

    routes = PromptServer.instance.routes

    @routes.get("/umbrae/expander/tree")
    async def _tree(request):
        try:
            return web.json_response(handle_tree())
        except Exception as e:
            logger.exception("[umbrae expander] tree failed")
            return web.json_response({"status": "error", "error": str(e)}, status=500)

    @routes.get("/umbrae/expander/entries")
    async def _entries(request):
        try:
            return web.json_response(handle_entries(dict(request.query)))
        except Exception as e:
            logger.exception("[umbrae expander] entries failed")
            return web.json_response({"status": "error", "error": str(e)}, status=500)

    @routes.post("/umbrae/expander/expand")
    async def _expand(request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        try:
            return web.json_response(handle_expand(data if isinstance(data, dict) else {}))
        except Exception as e:
            logger.exception("[umbrae expander] expand failed")
            return web.json_response({"status": "error", "error": str(e)}, status=200)

    return True
