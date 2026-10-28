# umbrae_nodes/modules/clause/preview_server.py — umbrae_nodes v0.8.8
# Ported from ComfyUI-WildcardClause (preview_server.py) to run on the umbrae wildcard
# engine (umbrae_wildcards.py) instead of Impact Pack's. Routes live under
# /umbrae/clause/, the node is UmbraeWildcardClauseExpander, the feedback event
# is umbrae-clause-feedback, so it runs alongside the original package.
from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from .capabilities import build_capabilities, invalidate_capabilities_cache
from .catalog_index import (
    get_catalog_index,
    invalidate_catalog_cache,
    resolve_thumb_file,
)
from .clause_expand import (
    OVERRIDE_PARAM_TO_KIND,
    preview_expand_with_overrides,
    reload_wildcards,
    reroll_override_value,
    resolve_expand_report,
)
from .contract import ENGINE_VERSION, OVERRIDE_INPUT_KEYS, SCHEMA_VERSION, SKIP_OVERRIDE_SENTINEL
from .preset_store import (
    delete_preset,
    list_presets,
    read_preset,
    save_preset,
)


def _custom_wildcards_root() -> Path:
    """Folder holding presets (scene-/character-configurations) and the
    template catalog (user-wildcards/): Impact's custom wildcards folder when
    it exists (that is where the UW pack installs), else umbrae_nodes/wildcards."""
    from .. import umbrae_wildcards as wc

    impact = wc.get_impact_custom_wildcards_path()
    if impact and Path(impact).is_dir():
        return Path(impact).resolve()
    return Path(wc.wildcards_path).resolve()


def _preview_versions(root: Path) -> dict[str, str]:
    caps = build_capabilities(root)
    return {
        "engine": ENGINE_VERSION,
        "schema": SCHEMA_VERSION,
        "wildcard_corpus_sha256": caps["wildcard_corpus"]["sha256"],
        "catalog_revision": caps["catalog_revision"],
    }


def _normalize_override_entry(key: str, raw: object) -> str:
    if isinstance(raw, str):
        text = raw.strip()
        return SKIP_OVERRIDE_SENTINEL if text == "skipped" else raw
    if not isinstance(raw, Mapping):
        raise ValueError(f"override {key} must be a string or {{state, value}} object")
    state = str(raw.get("state") or "default").strip().lower()
    value = str(raw.get("value") or "")
    if state not in ("default", "pinned", "skipped"):
        raise ValueError(f"override {key} has invalid state {state!r}")
    if state == "skipped":
        return SKIP_OVERRIDE_SENTINEL
    if state == "pinned" and not value.strip():
        raise ValueError(f"override {key} pinned state requires non-empty value")
    if state == "default":
        return ""
    return value


def _wire_overrides_from_request(data: Mapping[str, object]) -> dict[str, str]:
    overrides_block = data.get("overrides")
    wire: dict[str, str] = {}
    if isinstance(overrides_block, Mapping):
        for key, raw in overrides_block.items():
            key = str(key)
            if key == "subject_override":
                raise ValueError("subject_override was removed")
            if key not in OVERRIDE_INPUT_KEYS:
                raise ValueError(f"unknown override key {key!r}")
            wire[key] = _normalize_override_entry(key, raw)
    for key in OVERRIDE_INPUT_KEYS:
        if key in data and key not in wire:
            wire[key] = _normalize_override_entry(key, data.get(key) or "")
    unknown = set(wire) - set(OVERRIDE_INPUT_KEYS)
    if unknown:
        raise ValueError(f"unknown override keys: {sorted(unknown)}")
    return {key: wire.get(key, "") for key in OVERRIDE_INPUT_KEYS}


def build_preview_response(data: Mapping[str, object], root: Path) -> dict[str, Any]:
    mode = str(data.get("mode") or "populate")
    if mode not in ("populate", "fixed"):
        raise ValueError(f"invalid mode {mode!r}")
    seed = data.get("seed", None)
    overrides = _wire_overrides_from_request(data)
    if mode == "fixed":
        source = str(data.get("populated_text") or "")
        if not source.strip():
            raise ValueError("fixed mode requires non-empty populated_text")
    else:
        source = str(data.get("text") or "")
    previewed = preview_expand_with_overrides(source, seed, **overrides)
    report = resolve_expand_report(source, seed, **overrides)
    populated = report.get("populated", previewed)
    return {
        "api_version": "1",
        "text": previewed,
        "structural": previewed,
        "populated": populated,
        "leaves": report.get("leaves", {}),
        "matches": report.get("matches", {}),
        "targets": report.get("targets", {}),
        "versions": _preview_versions(root),
    }


def build_reroll_response(data: Mapping[str, object]) -> dict[str, str]:
    param_key = str(data.get("key") or "")
    if param_key not in OVERRIDE_INPUT_KEYS:
        raise ValueError(f"unknown override key {param_key!r}")
    seed = data.get("seed", None)
    overrides = _wire_overrides_from_request(data)
    text = str(data.get("text") or "")
    return reroll_override_value(text, seed, param_key, **overrides)


def register_preview_routes():
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception:
        logger.info("[umbrae clause] PromptServer unavailable; skipping preview route")
        return

    @PromptServer.instance.routes.get("/umbrae/clause/capabilities")
    async def wildcard_capabilities(request):
        try:
            doc = build_capabilities(_custom_wildcards_root())
        except Exception:
            logger.exception("[umbrae clause] capabilities build failed")
            return web.json_response(
                {
                    "error": {
                        "code": "CAPABILITIES_UNAVAILABLE",
                        "message": "Wildcard capabilities are unavailable.",
                    }
                },
                status=503,
            )
        return web.json_response(doc)

    @PromptServer.instance.routes.post("/umbrae/clause/wildcards/reload")
    async def wildcards_reload(request):
        try:
            count = reload_wildcards()
            invalidate_catalog_cache()
            invalidate_capabilities_cache()
        except Exception:
            logger.exception("[umbrae clause] wildcard reload failed")
            return web.json_response({"ok": False, "error": "reload failed"}, status=500)
        return web.json_response({"ok": True, "count": count})

    @PromptServer.instance.routes.post("/umbrae/clause/preview")
    async def preview_wildcards(request):
        data = await request.json()
        try:
            payload = build_preview_response(data, _custom_wildcards_root())
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception:
            logger.exception("[umbrae clause] preview expand failed")
            return web.json_response({"error": "preview failed"}, status=500)
        return web.json_response(payload)

    @PromptServer.instance.routes.post("/umbrae/clause/reroll")
    async def reroll_override(request):
        data = await request.json()
        try:
            payload = build_reroll_response(data)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception:
            logger.exception("[umbrae clause] reroll failed")
            return web.json_response({"error": "reroll failed"}, status=500)
        return web.json_response(payload)

    @PromptServer.instance.routes.get("/umbrae/clause/presets")
    async def presets_list(request):
        domain = request.rel_url.query.get("domain", "")
        if domain not in ("scene", "character"):
            return web.json_response({"error": "invalid domain"}, status=400)
        try:
            items = list_presets(_custom_wildcards_root(), domain)
        except Exception:
            logger.exception("[umbrae clause] preset list failed")
            return web.json_response({"presets": []}, status=500)
        return web.json_response({"presets": items})

    @PromptServer.instance.routes.get("/umbrae/clause/presets/{domain}/{preset_id:.+}")
    async def presets_get(request):
        domain = request.match_info["domain"]
        preset_id = request.match_info["preset_id"]
        if domain not in ("scene", "character"):
            return web.json_response({"error": "invalid domain"}, status=400)
        try:
            doc = read_preset(_custom_wildcards_root(), domain, preset_id)
        except FileNotFoundError:
            return web.json_response({"error": "not found"}, status=404)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        return web.json_response(doc)

    @PromptServer.instance.routes.post("/umbrae/clause/presets/{domain}")
    async def presets_save(request):
        domain = request.match_info["domain"]
        if domain not in ("scene", "character"):
            return web.json_response({"error": "invalid domain"}, status=400)
        data = await request.json()
        name = (data.get("name") or "").strip()
        overrides = data.get("overrides") or {}
        if not name:
            return web.json_response({"error": "name required"}, status=400)
        try:
            saved = save_preset(_custom_wildcards_root(), domain, name, overrides)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception:
            logger.exception("[umbrae clause] preset save failed")
            return web.json_response({"error": "save failed"}, status=500)
        return web.json_response(saved)

    @PromptServer.instance.routes.delete("/umbrae/clause/presets/{domain}/{preset_id:.+}")
    async def presets_delete(request):
        domain = request.match_info["domain"]
        preset_id = request.match_info["preset_id"]
        if domain not in ("scene", "character"):
            return web.json_response({"error": "invalid domain"}, status=400)
        try:
            delete_preset(_custom_wildcards_root(), domain, preset_id)
        except PermissionError as exc:
            return web.json_response({"error": str(exc)}, status=403)
        except FileNotFoundError:
            return web.json_response({"error": "not found"}, status=404)
        return web.json_response({"ok": True})

    @PromptServer.instance.routes.get("/umbrae/clause/catalog")
    async def catalog_list(request):
        try:
            index = get_catalog_index(_custom_wildcards_root())
        except Exception:
            logger.exception("[umbrae clause] catalog index failed")
            return web.json_response({"products": [], "groups": []}, status=500)
        return web.json_response(index)

    @PromptServer.instance.routes.post("/umbrae/clause/catalog/refresh")
    async def catalog_refresh(request):
        invalidate_catalog_cache()
        invalidate_capabilities_cache()
        try:
            index = get_catalog_index(_custom_wildcards_root(), refresh=True)
        except Exception:
            logger.exception("[umbrae clause] catalog refresh failed")
            return web.json_response({"ok": False}, status=500)
        return web.json_response(
            {"ok": True, "product_count": len(index.get("products") or [])}
        )

    @PromptServer.instance.routes.get("/umbrae/clause/catalog/thumb")
    async def catalog_thumb(request):
        product = request.rel_url.query.get("product", "")
        kind = request.rel_url.query.get("kind", "")
        name = request.rel_url.query.get("name", "")
        if kind not in ("router", "template") or not product or not name:
            return web.Response(status=400)
        path = resolve_thumb_file(_custom_wildcards_root(), product, kind, name)
        if path is None or not path.is_file():
            return web.Response(status=404)
        return web.FileResponse(path)
