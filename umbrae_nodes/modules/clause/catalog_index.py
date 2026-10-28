# umbrae_nodes/modules/clause/catalog_index.py — umbrae_nodes v0.8.8
# Ported from ComfyUI-WildcardClause (catalog_index.py) to run on the umbrae wildcard
# engine (umbrae_wildcards.py) instead of Impact Pack's. Routes live under
# /umbrae/clause/, the node is UmbraeWildcardClauseExpander, the feedback event
# is umbrae-clause-feedback, so it runs alongside the original package.
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

import yaml

EXCLUDED_DIR_NAMES = frozenset({"releases", "bow", "mega", "dynamic-unleashed"})
_EXCLUDED_PREFIXES = ("_archive",)

_TEMPLATE_REF_RE = re.compile(r"/template/([^/_]+)__")

_cache: dict[str, dict] = {}


def is_templates_yaml_path(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith(".yaml") and "templates" in name


def product_id_from_yaml(path: Path) -> str:
    return path.stem


def derive_label(name: str) -> str:
    text = (name or "").replace("-", " ").strip()
    if not text:
        return ""
    parts = text.split()
    parts[0] = parts[0].capitalize()
    return " ".join(parts)


_GROUP_LABEL_OVERRIDES = {
    "krea2": "Krea 2",
    "ideogram4": "Ideogram 4",
    "minimax-h3": "MiniMax H3",
    "flux2": "Flux 2",
    "illustrious": "Illustrious",
}


def derive_group_label(segment: str) -> str:
    key = (segment or "").strip().lower()
    if key in _GROUP_LABEL_OVERRIDES:
        return _GROUP_LABEL_OVERRIDES[key]
    return derive_label(segment)


def group_path_from_rel_yaml(rel_yaml: str) -> str:
    parts = Path(rel_yaml).parts
    if not parts or parts[0] != "user-wildcards":
        return ""
    inner = Path(*parts[1:])
    if len(inner.parts) <= 1:
        return ""
    return inner.parent.as_posix()


def build_groups(products: list[dict]) -> list[dict]:
    product_by_id = {p["id"]: p for p in products}
    by_path: dict[str, dict] = {}

    def ensure_group(path: str) -> dict:
        if path in by_path:
            return by_path[path]
        parts = [p for p in path.split("/") if p] if path else []
        parent_path = "/".join(parts[:-1]) if len(parts) > 1 else ""
        if parent_path:
            ensure_group(parent_path)
        label = derive_group_label(parts[-1]) if parts else "General"
        by_path[path] = {
            "id": path or "_root",
            "path": path,
            "label": label,
            "parent_path": parent_path,
            "product_ids": [],
            "child_paths": [],
        }
        return by_path[path]

    for product in products:
        gp = product.get("group_path") or ""
        ensure_group(gp)
        by_path[gp]["product_ids"].append(product["id"])

    for path in list(by_path):
        parts = [p for p in path.split("/") if p] if path else []
        for i in range(1, len(parts)):
            parent = "/".join(parts[:i])
            ensure_group(parent)

    for path, group in by_path.items():
        parent = group["parent_path"]
        if parent in by_path and path not in by_path[parent]["child_paths"]:
            by_path[parent]["child_paths"].append(path)
        ids = group["product_ids"]
        group["router_count"] = sum(
            len(product_by_id[pid].get("routers") or [])
            for pid in ids
            if pid in product_by_id
        )
        group["template_count"] = sum(
            len(product_by_id[pid].get("templates") or [])
            for pid in ids
            if pid in product_by_id
        )
        group["child_paths"] = sorted(group["child_paths"], key=lambda p: by_path[p]["label"].lower())

    return sorted(by_path.values(), key=lambda g: (g["parent_path"], g["label"].lower()))


def catalog_dir_for_yaml(yaml_path: Path) -> Path:
    return yaml_path.with_suffix(".catalog")


def _path_under_dir(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _tag(root: str, kind: str, name: str) -> str:
    return f"__{root}/{kind}/{name}__"


def _extract_template_refs(value) -> list[str]:
    names: list[str] = []
    if not isinstance(value, list):
        return names
    for item in value:
        if not isinstance(item, str):
            continue
        m = _TEMPLATE_REF_RE.search(item)
        if m:
            names.append(m.group(1))
    return names


def parse_template_yaml(yaml_path: Path, custom_wildcards_root: Path) -> dict:
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or len(data) != 1:
        raise ValueError(f"expected single root key in {yaml_path}")
    root_key = next(iter(data))
    block = data[root_key] or {}
    rel_yaml = yaml_path.resolve().relative_to(custom_wildcards_root.resolve()).as_posix()
    catalog_rel = Path(rel_yaml).with_suffix(".catalog").as_posix()
    product_id = product_id_from_yaml(yaml_path)
    routers_raw = block.get("router") or {}
    templates_raw = block.get("template") or {}
    templates_by_name = {
        name: {
            "name": name,
            "tag": _tag(root_key, "template", name),
            "label": derive_label(name),
        }
        for name in templates_raw
    }
    routers = []
    for name, refs in routers_raw.items():
        linked = _extract_template_refs(refs)
        routers.append(
            {
                "name": name,
                "tag": _tag(root_key, "router", name),
                "label": derive_label(name),
                "templates": linked,
                "template_count": len(linked),
            }
        )
    return {
        "id": product_id,
        "label": derive_label(
            product_id.replace("-templates", "")
            .replace("krea2-nsfw-", "")
            .replace("krea2-sfw-", "")
        ),
        "yaml_path": rel_yaml,
        "group_path": group_path_from_rel_yaml(rel_yaml),
        "catalog_dir": catalog_rel,
        "root": root_key,
        "routers": routers,
        "templates": list(templates_by_name.values()),
    }


def write_catalog_meta_skeleton(catalog_dir: Path, product: dict) -> bool:
    meta_path = catalog_dir / "catalog.json"
    if meta_path.is_file():
        return False
    routers = {r["name"]: {"label": ""} for r in product.get("routers") or []}
    templates = {t["name"]: {"label": ""} for t in product.get("templates") or []}
    skeleton = {
        "version": 1,
        "product_label": product.get("label") or "",
        "routers": routers,
        "templates": templates,
    }
    catalog_dir.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(skeleton, indent=2) + "\n", encoding="utf-8")
    return True


def scan_catalog(custom_wildcards_root: Path) -> dict:
    root = custom_wildcards_root.resolve()
    user_root = root / "user-wildcards"
    products = []
    if not user_root.is_dir():
        return {"products": products, "groups": []}
    for yaml_path in sorted(user_root.rglob("*.yaml")):
        if not is_templates_yaml_path(yaml_path):
            continue
        rel_parts = yaml_path.relative_to(user_root).parts
        if any(p in EXCLUDED_DIR_NAMES or p.startswith(_EXCLUDED_PREFIXES) for p in rel_parts):
            continue
        try:
            product = parse_template_yaml(yaml_path, root)
            catalog_dir = root / product["catalog_dir"]
            write_catalog_meta_skeleton(catalog_dir, product)
            products.append(apply_catalog_meta(product, catalog_dir))
        except Exception:
            continue
    return {"products": products, "groups": build_groups(products)}


def load_catalog_meta(catalog_dir: Path) -> dict:
    meta_path = catalog_dir / "catalog.json"
    if not meta_path.is_file():
        return {}
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def apply_catalog_meta(product: dict, catalog_dir: Path) -> dict:
    meta = load_catalog_meta(catalog_dir)
    if meta.get("product_label"):
        product = {**product, "label": meta["product_label"]}
    router_meta = meta.get("routers") or {}
    template_meta = meta.get("templates") or {}
    routers = []
    for r in product.get("routers") or []:
        m = router_meta.get(r["name"]) or {}
        if m.get("hidden"):
            continue
        routers.append({**r, "label": m.get("label") or r["label"]})
    templates = []
    for t in product.get("templates") or []:
        m = template_meta.get(t["name"]) or {}
        if m.get("hidden"):
            continue
        templates.append({**t, "label": m.get("label") or t["label"]})
    return {**product, "routers": routers, "templates": templates}


def resolve_router_cover_path(catalog_dir: Path, meta: dict, router: dict) -> Path | None:
    name = router.get("name") or ""
    rel = (meta.get("routers") or {}).get(name, {}).get("cover")
    if rel:
        candidate = (catalog_dir / rel).resolve()
        if candidate.is_file() and _path_under_dir(candidate, catalog_dir):
            return candidate
    default = catalog_dir / "router" / f"{name}.png"
    if default.is_file():
        return default
    for tmpl_name in router.get("templates") or []:
        thumb = resolve_thumb_path(catalog_dir, meta, "template", tmpl_name)
        if thumb is not None:
            return thumb
    return None


def resolve_thumb_path(catalog_dir: Path, meta: dict, kind: str, name: str) -> Path | None:
    if kind == "router":
        return resolve_router_cover_path(
            catalog_dir, meta, {"name": name, "templates": []}
        )
    rel = None
    if kind == "template":
        rel = (meta.get("templates") or {}).get(name, {}).get("thumb")
    if rel:
        candidate = (catalog_dir / rel).resolve()
        if candidate.is_file() and _path_under_dir(candidate, catalog_dir):
            return candidate
    default = catalog_dir / kind / f"{name}.png"
    return default if default.is_file() else None


def enrich_index_with_urls(index: dict) -> dict:
    products = []
    for p in index.get("products") or []:
        pid = quote(p["id"], safe="")
        routers = []
        for r in p.get("routers") or []:
            name = quote(r["name"], safe="")
            routers.append(
                {
                    **r,
                    "cover_url": (
                        f"/umbrae/clause/catalog/thumb?product={pid}"
                        f"&kind=router&name={name}"
                    ),
                }
            )
        templates = []
        for t in p.get("templates") or []:
            name = quote(t["name"], safe="")
            templates.append(
                {
                    **t,
                    "thumb_url": (
                        f"/umbrae/clause/catalog/thumb?product={pid}"
                        f"&kind=template&name={name}"
                    ),
                }
            )
        products.append({**p, "routers": routers, "templates": templates})
    groups = index.get("groups") or build_groups(products)
    return {"products": products, "groups": groups}


def get_catalog_index(custom_wildcards_root: Path, *, refresh: bool = False) -> dict:
    cache_key = str(custom_wildcards_root.resolve())
    if refresh or cache_key not in _cache:
        _cache[cache_key] = enrich_index_with_urls(scan_catalog(custom_wildcards_root))
    return _cache[cache_key]


def invalidate_catalog_cache() -> None:
    _cache.clear()


def resolve_thumb_file(
    custom_wildcards_root: Path, product_id: str, kind: str, name: str
) -> Path | None:
    index = get_catalog_index(custom_wildcards_root)
    root = custom_wildcards_root.resolve()
    for p in index.get("products") or []:
        if p["id"] != product_id:
            continue
        catalog_dir = root / p["catalog_dir"]
        meta = load_catalog_meta(catalog_dir)
        if kind == "router":
            router = next(
                (r for r in p.get("routers") or [] if r["name"] == name),
                {"name": name, "templates": []},
            )
            return resolve_router_cover_path(catalog_dir, meta, router)
        return resolve_thumb_path(catalog_dir, meta, kind, name)
    return None


__all__ = [
    "EXCLUDED_DIR_NAMES",
    "apply_catalog_meta",
    "build_groups",
    "catalog_dir_for_yaml",
    "derive_group_label",
    "derive_label",
    "enrich_index_with_urls",
    "group_path_from_rel_yaml",
    "get_catalog_index",
    "invalidate_catalog_cache",
    "is_templates_yaml_path",
    "load_catalog_meta",
    "parse_template_yaml",
    "product_id_from_yaml",
    "resolve_router_cover_path",
    "resolve_thumb_file",
    "resolve_thumb_path",
    "scan_catalog",
    "write_catalog_meta_skeleton",
]
