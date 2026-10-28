# umbrae_nodes/modules/expander/catalog.py — umbrae_nodes v0.9.0
#
# The user's whole wildcard collection as a folder tree, and the lines of any
# tag exactly as the engine would pool them (file, folder call, pattern), with
# their line indexes so the UI can pin one.

from __future__ import annotations

import re

from .. import umbrae_wildcards as wc

MAX_ENTRY_LIMIT = 500
_LINE_CUT = 300


def _all_keys() -> set[str]:
    """Same key universe the engine searches (both cache modes)."""
    if wc.is_on_demand_mode():
        return set(wc.available_wildcards) | set(wc.loaded_wildcards)
    return set(wc.wildcard_dict)


def _search_dict():
    return wc.available_wildcards if wc.is_on_demand_mode() else wc.wildcard_dict


def _loaded_count(key: str):
    """Line count when the key is already in memory (never forces a load)."""
    for store in (wc.wildcard_dict, wc.loaded_wildcards):
        v = store.get(key)
        if isinstance(v, (list, tuple)):
            return len(v)
    return None


# ── tree ──────────────────────────────────────────────────────────────────────

def collection_tree() -> dict:
    """{"roots": [...], "keys": N} - folders first, then files, case-insensitive.
    YAML keys are filed under their .yaml file (shown as a folder node of kind
    'yaml'), because YAML keys come from file content, not the path."""
    tags = wc.get_wildcard_list()
    root: dict = {"name": "", "path": "", "kind": "folder", "children": {}}
    nkeys = 0
    for t in tags:
        key = t[2:-2]
        nkeys += 1
        src = wc.key_sources.get(key)
        if src:
            path = [p for p in str(src).replace("\\", "/").split("/") if p] + key.split("/")
            yaml_depth = len(path) - len(key.split("/"))
        else:
            path = key.split("/")
            yaml_depth = -1
        node = root
        for depth, part in enumerate(path[:-1]):
            kids = node["children"]
            if part not in kids:
                kind = "yaml" if depth == yaml_depth - 1 else "folder"
                kids[part] = {"name": part, "path": "/".join(path[:depth + 1]), "kind": kind, "children": {}}
            node = kids[part]
        node["children"][path[-1]] = {
            "name": path[-1], "key": key, "kind": "key" if src else "file",
            "count": _loaded_count(key),
        }

    def finish(n: dict) -> dict:
        kids = n.pop("children", None)
        if kids is None:
            return n
        items = [finish(k) for k in kids.values()]
        items.sort(key=lambda k: (0 if "children" in k else 1, k["name"].lower()))
        n["children"] = items
        n["files"] = sum(k.get("files", 1) if "children" in k else 1 for k in items)
        # a folder is callable as a tag when it is a real wildcard folder (not a yaml file)
        n["callable"] = n["kind"] == "folder" and bool(n["path"])
        return n

    out = finish(root)
    return {"roots": out["children"], "keys": nkeys, "on_demand": wc.is_on_demand_mode()}


# ── entries ───────────────────────────────────────────────────────────────────

def tag_options(raw: str):
    """What __raw__ draws from, mirroring the engine: (chain_key, options | None,
    kind) with kind in file / folder / pattern / missing. chain_key is the key an
    edit must use ('x/y', 'x/y/' for a folder call, 'col*' / '*/name' for patterns)."""
    tag = (raw or "").strip()
    if tag.startswith("__") and tag.endswith("__") and len(tag) > 4:
        tag = tag[2:-2]
    key, folder_only = wc.normalize_tag_key(tag)
    if not key:
        return key, None, "missing"
    options = None if folder_only else wc.get_wildcard_value(key)
    if options is not None:
        return key, list(options), "file"
    if "*" not in key:
        prefix = key + "/"
        pooled = []
        for k in sorted(_all_keys()):
            if k.startswith(prefix):
                v = wc.get_wildcard_value(k)
                if v:
                    pooled.extend(v)
        if pooled:
            return key + "/", pooled, "folder"
        if "/" not in key and not folder_only:
            return tag_options("*/" + key)          # the engine's short-name fallback
        return key, None, "missing"
    total = []
    search = _search_dict()
    if key.startswith("*/") and len(key) > 2:
        base = key[2:]
        for k in list(search.keys()):
            if k == base or k.endswith("/" + base) or k.startswith(base + "/") or ("/" + base + "/") in k:
                v = wc.get_wildcard_value(k)
                if v:
                    total += list(v)
    else:
        sub = key.replace("*", ".*").replace("+", "\\+")
        for k in list(search.keys()):
            if re.match(sub, k) is not None or re.match(sub, k + "/") is not None:
                v = wc.get_wildcard_value(k)
                if v:
                    total += list(v)
    if total:
        return key, total, "pattern"
    return key, None, "missing"


def entries(raw: str, offset: int = 0, limit: int = 60, query: str = "") -> dict:
    """Paged lines of a tag with their indexes. `query`: every word must appear
    (case-insensitive); indexes stay the original ones so a pin still works."""
    chain_key, options, kind = tag_options(raw)
    try:
        offset = max(0, int(offset))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = max(1, min(MAX_ENTRY_LIMIT, int(limit)))
    except (TypeError, ValueError):
        limit = 60
    if options is None:
        return {"key": chain_key, "found": False, "kind": kind, "count": 0, "total": 0,
                "offset": 0, "lines": [], "source": ""}
    words = [w for w in (query or "").lower().split() if w]
    if words:
        idxs = [i for i, o in enumerate(options) if all(w in str(o).lower() for w in words)]
    else:
        idxs = range(len(options))
    total = len(idxs)
    page = list(idxs)[offset:offset + limit] if words else list(range(offset, min(len(options), offset + limit)))
    lines = [{"i": i, "text": wc.strip_option_weight(options[i]).strip()[:_LINE_CUT],
              "w": wc.option_weight_of(options[i])} for i in page]
    src = wc.key_sources.get(chain_key.rstrip("/"), "") if kind == "file" else ""
    return {"key": chain_key, "found": True, "kind": kind, "count": len(options), "total": total,
            "offset": offset, "lines": lines, "source": src}
