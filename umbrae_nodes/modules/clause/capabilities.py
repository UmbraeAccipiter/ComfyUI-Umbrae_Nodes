# umbrae_nodes/modules/clause/capabilities.py — umbrae_nodes v0.8.8
# Ported from ComfyUI-WildcardClause (capabilities.py) to run on the umbrae wildcard
# engine (umbrae_wildcards.py) instead of Impact Pack's. Routes live under
# /umbrae/clause/, the node is UmbraeWildcardClauseExpander, the feedback event
# is umbrae-clause-feedback, so it runs alongside the original package.
"""Versioned Wildcard Clause capabilities document."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .catalog_index import get_catalog_index
from .contract import ENGINE_VERSION, OVERRIDE_FIELDS, SCHEMA_VERSION

_CORPUS_SUFFIXES = (".yaml", ".yml", ".txt")
_corpus_cache: dict[str, tuple[tuple[tuple[str, int, int], ...], str, int]] = {}


def _catalog_revision(custom_wildcards_root: Path) -> str:
    index = get_catalog_index(custom_wildcards_root)
    payload = json.dumps(index, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _wildcard_corpus_hash(custom_wildcards_root: Path) -> tuple[str, int]:
    root = custom_wildcards_root.resolve()
    entries: list[tuple[str, int, int]] = []
    digest = hashlib.sha256()
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in _CORPUS_SUFFIXES:
                continue
            rel = path.relative_to(root).as_posix()
            stat = path.stat()
            entries.append((rel, stat.st_size, stat.st_mtime_ns))
    revision = tuple(entries)
    cached = _corpus_cache.get(str(root))
    if cached and cached[0] == revision:
        return cached[1], cached[2]
    for rel, size, _mtime in entries:
        path = root / rel
        digest.update(rel.encode("utf-8"))
        digest.update(str(size).encode("utf-8"))
        digest.update(path.read_bytes())
    sha = digest.hexdigest()
    file_count = len(entries)
    _corpus_cache[str(root)] = (revision, sha, file_count)
    return sha, file_count


def invalidate_capabilities_cache() -> None:
    _corpus_cache.clear()


def override_fields_payload() -> list[dict[str, Any]]:
    return [
        {
            "id": f.id,
            "kind": f.kind,
            "group": f.group,
            "label": f.label,
            "tooltip": f.tooltip,
            "example": f.example,
            "order": f.order,
            "precedes": list(f.precedes),
        }
        for f in OVERRIDE_FIELDS
    ]


def precedence_payload() -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for field in OVERRIDE_FIELDS:
        for after in field.precedes:
            out.append({"before": field.id, "after": after})
    return out


def build_capabilities(custom_wildcards_root: Path) -> dict[str, Any]:
    corpus_sha, file_count = _wildcard_corpus_hash(custom_wildcards_root)
    return {
        "api_version": "1",
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "modes": ["populate", "fixed"],
        "states": ["default", "pinned", "skipped"],
        "override_fields": override_fields_payload(),
        "precedence": precedence_payload(),
        "endpoints": {
            "capabilities": {
                "method": "GET",
                "path": "/umbrae/clause/capabilities",
                "version": "1",
            },
            "preview": {
                "method": "POST",
                "path": "/umbrae/clause/preview",
                "version": "1",
            },
            "reroll": {
                "method": "POST",
                "path": "/umbrae/clause/reroll",
                "version": "1",
            },
            "catalog": {
                "method": "GET",
                "path": "/umbrae/clause/catalog",
                "version": "1",
            },
            "presets": {
                "path": "/umbrae/clause/presets",
                "version": "1",
            },
        },
        "wildcard_corpus": {"sha256": corpus_sha, "file_count": file_count},
        "catalog_revision": _catalog_revision(custom_wildcards_root),
    }
