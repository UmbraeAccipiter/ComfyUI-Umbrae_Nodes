# umbrae_nodes/modules/clause/preset_store.py — umbrae_nodes v0.8.8
# Ported from ComfyUI-WildcardClause (preset_store.py) to run on the umbrae wildcard
# engine (umbrae_wildcards.py) instead of Impact Pack's. Routes live under
# /umbrae/clause/, the node is UmbraeWildcardClauseExpander, the feedback event
# is umbrae-clause-feedback, so it runs alongside the original package.
from __future__ import annotations

import configparser
import json
import re
from pathlib import Path

from .clause_expand import SKIP_OVERRIDE_SENTINEL
from .contract import CHARACTER_OVERRIDE_KEYS, SCENE_OVERRIDE_KEYS

DOMAIN_KEYS = {
    "scene": SCENE_OVERRIDE_KEYS,
    "character": CHARACTER_OVERRIDE_KEYS,
}
DOMAIN_FOLDERS = {
    "scene": "scene-configurations",
    "character": "character-configurations",
}
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_USER_DIR = "user"
MAX_PRESET_BYTES = 65536


def slugify_name(name: str) -> str:
    slug = _SLUG_RE.sub("-", (name or "").strip().lower()).strip("-")
    return slug[:80] or "preset"


def filter_overrides_for_domain(domain: str, overrides: dict[str, str]) -> dict[str, str]:
    allowed = set(DOMAIN_KEYS[domain])
    out: dict[str, str] = {}
    for key, value in overrides.items():
        if key not in allowed:
            continue
        text = value or ""
        if text == SKIP_OVERRIDE_SENTINEL:
            out[key] = SKIP_OVERRIDE_SENTINEL
        elif text.strip():
            out[key] = text.strip()
    return out


def resolve_custom_wildcards_root(impact_pack_dir: Path | None = None) -> Path:
    if impact_pack_dir is None:
        # modules/clause -> modules -> umbrae_nodes -> custom_nodes
        impact_pack_dir = Path(__file__).resolve().parents[3] / "comfyui-impact-pack"
    ini_path = impact_pack_dir / "impact-pack.ini"
    if ini_path.is_file():
        cfg = configparser.ConfigParser()
        cfg.read(ini_path)
        raw = cfg.get("default", "custom_wildcards", fallback="").strip().strip("'\"")
        if raw:
            path = Path(raw)
            if path.is_dir():
                return path.resolve()
    return (impact_pack_dir / "custom_wildcards").resolve()


def domain_root(custom_wildcards: Path, domain: str) -> Path:
    if domain not in DOMAIN_FOLDERS:
        raise ValueError(f"invalid domain: {domain}")
    return (custom_wildcards / DOMAIN_FOLDERS[domain]).resolve()


def _assert_under_root(root: Path, target: Path) -> Path:
    root = root.resolve()
    target = target.resolve()
    if root == target or root in target.parents:
        return target
    raise ValueError("path escapes preset domain root")


def _preset_id_from_path(domain_root_path: Path, file_path: Path) -> str:
    rel = file_path.resolve().relative_to(domain_root_path.resolve())
    return str(rel.with_suffix("")).replace("\\", "/")


def _is_user_preset(domain_root_path: Path, file_path: Path) -> bool:
    rel = file_path.resolve().relative_to(domain_root_path.resolve())
    return bool(rel.parts) and rel.parts[0] == _USER_DIR


def list_presets(custom_wildcards: Path, domain: str) -> list[dict]:
    root = domain_root(custom_wildcards, domain)
    if not root.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(root.rglob("*.json")):
        if not path.is_file():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        preset_id = _preset_id_from_path(root, path)
        out.append(
            {
                "id": preset_id,
                "name": str(doc.get("name") or preset_id),
                "domain": domain,
                "source": "user" if _is_user_preset(root, path) else "pack",
                "filename": path.name,
                "mtime": int(path.stat().st_mtime),
            }
        )
    return out


def read_preset(custom_wildcards: Path, domain: str, preset_id: str) -> dict:
    root = domain_root(custom_wildcards, domain)
    path = _assert_under_root(root, root / f"{preset_id}.json")
    if not path.is_file():
        raise FileNotFoundError(preset_id)
    if path.stat().st_size > MAX_PRESET_BYTES:
        raise ValueError("preset too large")
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["overrides"] = filter_overrides_for_domain(domain, doc.get("overrides") or {})
    return doc


def save_preset(
    custom_wildcards: Path, domain: str, name: str, overrides: dict[str, str]
) -> dict:
    root = domain_root(custom_wildcards, domain)
    user_dir = root / _USER_DIR
    user_dir.mkdir(parents=True, exist_ok=True)
    slug = slugify_name(name)
    path = _assert_under_root(root, user_dir / f"{slug}.json")
    filtered = filter_overrides_for_domain(domain, overrides)
    if not filtered:
        raise ValueError("no non-empty overrides to save")
    doc = {
        "name": name.strip() or slug,
        "version": 1,
        "domain": domain,
        "overrides": filtered,
    }
    payload = json.dumps(doc, ensure_ascii=False, indent=2)
    if len(payload.encode("utf-8")) > MAX_PRESET_BYTES:
        raise ValueError("preset too large")
    path.write_text(payload + "\n", encoding="utf-8")
    return {"id": f"{_USER_DIR}/{slug}", "name": doc["name"], "path": str(path)}


def delete_preset(custom_wildcards: Path, domain: str, preset_id: str) -> None:
    root = domain_root(custom_wildcards, domain)
    path = _assert_under_root(root, root / f"{preset_id}.json")
    if not path.is_file():
        raise FileNotFoundError(preset_id)
    if not _is_user_preset(root, path):
        raise PermissionError("cannot delete pack preset")
    path.unlink()
