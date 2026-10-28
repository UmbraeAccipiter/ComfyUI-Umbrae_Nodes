# umbrae_nodes/modules/clause/clause_expand.py — umbrae_nodes v0.8.8
# Ported from ComfyUI-WildcardClause (clause_expand.py) to run on the umbrae wildcard
# engine (umbrae_wildcards.py) instead of Impact Pack's. Routes live under
# /umbrae/clause/, the node is UmbraeWildcardClauseExpander, the feedback event
# is umbrae-clause-feedback, so it runs alongside the original package.
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Escape `__` inside preview override injections so the engine does not expand nested tags.
_PREVIEW_UNDERSCORE_ESC = "\uE000WCUND\uE001"
_WILDCARD_TAG_RE = re.compile(r"__([\w.\-+/*\\]+?)__")
_PROB_PREFIX_RE = re.compile(r"^\s*[0-9.]+::")
# Brace choices and trailing aspect markers — not caption prose.
_BRACE_CHOICE_RE = re.compile(r"\{[^{}]*\}")
_ASPECT_MARKER_RE = re.compile(r"\[\d+:\d+\]")
# Identity/ethnicity composers use short fixed glue ("She has", "with … skin and … eyes").
# Caption pools (hair styles, poses, wardrobe lines) leave much longer residue → freeze.
_STRUCTURAL_RESIDUE_MAX = 40

from .contract import OVERRIDE_PARAM_TO_KIND, SKIP_OVERRIDE_SENTINEL

LEAF_OVERRIDE_KINDS = (
    "subject",
    "wardrobe",
    "environment",
    "medium",
    "lighting",
    "treatment",
)

# Scene leaf kinds first (subject excluded — matcher tests only), then character atoms.
SCENE_OVERRIDE_KINDS = tuple(k for k in LEAF_OVERRIDE_KINDS if k != "subject")
OVERRIDE_KIND_ORDER = SCENE_OVERRIDE_KINDS + (
    "hair",
    "body",
    "age",
    "eye_color",
    "nationality",
    "skin",
    "face",
    "jewelry",
    "skin_tone",
    "hair_color",
    "breast_size",
    "butt_size",
)

KIND_TO_PARAM = {kind: param for param, kind in OVERRIDE_PARAM_TO_KIND.items()}

_MARKER_PAIR_RE = re.compile(
    r"@@WC_START:(\w+)@@(.*?)@@WC_END:\1@@",
    re.DOTALL,
)


def _normalize_key(key: str) -> str:
    return key.replace("\\", "/").replace(" ", "-").lower()


def is_leaf_override_key(key: str, kind: str) -> bool:
    k = _normalize_key(key)
    if "/leaf/" not in k:
        return False
    if kind not in LEAF_OVERRIDE_KINDS:
        return False
    return k.endswith(f"/{kind}")


def is_atom_override_key(key: str, kind: str) -> bool:
    k = _normalize_key(key)
    if kind == "hair":
        return "/common/hair/" in k and "/hair-color/" not in k
    if kind == "body":
        return "/body-archetype/" in k
    if kind == "age":
        return "/common/age/" in k
    if kind == "eye_color":
        return "/eye-color/" in k
    if kind == "nationality":
        return "/nationality/" in k
    if kind == "skin":
        return "/common/skin/" in k and "/skin-tone/" not in k
    if kind == "face":
        return "/face-features/" in k
    if kind == "jewelry":
        return "/piercing/" in k or "/accessories/" in k
    if kind == "skin_tone":
        return "/skin-tone/" in k
    if kind == "hair_color":
        return "/hair-color/" in k
    if kind == "breast_size":
        return "/breast-size/" in k
    if kind == "butt_size":
        return "/butt-size/" in k
    return False


def is_override_key(key: str, kind: str) -> bool:
    if kind in LEAF_OVERRIDE_KINDS:
        return is_leaf_override_key(key, kind)
    return is_atom_override_key(key, kind)


_DOUBLE_COMMA_RE = re.compile(r",\s*,")
_PUNCT_ONLY_COMMA_GAP_RE = re.compile(r",\s*[.;:,!?\-–—]+\s*,")
_DANGLING_COMMA_PERIOD_RE = re.compile(r",\s*\.(?=\s|$)")
_PERIOD_COMMA_RE = re.compile(r"\.\s*,")
_INLINE_SPACE_RE = re.compile(r"[^\S\n]+")


def _clean_expand_artifacts(text: str) -> str:
    """Collapse comma gaps left when skipped clauses remove wildcard prose."""
    if text is None:
        return ""
    out = text
    prev = None
    while prev != out:
        prev = out
        out = _PUNCT_ONLY_COMMA_GAP_RE.sub(",", out)
        out = _DOUBLE_COMMA_RE.sub(",", out)
        out = _DANGLING_COMMA_PERIOD_RE.sub(".", out)
        out = _PERIOD_COMMA_RE.sub(",", out)
        out = _INLINE_SPACE_RE.sub(" ", out)
    return out


def is_skip_override(value: str) -> bool:
    return value == SKIP_OVERRIDE_SENTINEL


def classify_overrides(**overrides: str) -> tuple[dict[str, str], set[str]]:
    """Return text overrides and skip kinds from widget values."""
    active: dict[str, str] = {}
    skip_kinds: set[str] = set()
    for param, kind in OVERRIDE_PARAM_TO_KIND.items():
        raw = overrides.get(param) or ""
        if is_skip_override(raw):
            skip_kinds.add(kind)
            continue
        value = raw.strip()
        if value:
            active[kind] = value
    return active, skip_kinds


def collect_active_overrides(**overrides: str) -> dict[str, str]:
    """Return non-empty override map keyed by match kind, preserving precedence order."""
    active, _skip = classify_overrides(**overrides)
    return active


def ensure_wildcards():
    """The umbrae wildcard engine, loaded (umbrae_wildcard_server loads it at
    startup; this only covers an import order surprise). Returns the module."""
    from .. import umbrae_wildcards as wc

    if not wc.wildcard_dict and not wc.available_wildcards and not wc.loaded_wildcards:
        wc.wildcard_load()
    return wc


def reload_wildcards() -> int:
    """Re-read every umbrae wildcard root from disk. Returns tag count."""
    wc = ensure_wildcards()
    wc.wildcard_load()
    return len(wc.get_wildcard_list())


def _is_terminal_option(text) -> bool:
    """True when option has no ``__…__`` tags after stripping ``N::`` probability prefixes."""
    s = _PROB_PREFIX_RE.sub("", "" if text is None else str(text), count=1)
    return _WILDCARD_TAG_RE.search(s) is None


def _non_tag_residue(text) -> str:
    """Alphanumeric leftover after removing tags, brace choices, aspect markers, and punctuation."""
    s = _PROB_PREFIX_RE.sub("", "" if text is None else str(text), count=1)
    s = _WILDCARD_TAG_RE.sub(" ", s)
    s = _BRACE_CHOICE_RE.sub(" ", s)
    s = _ASPECT_MARKER_RE.sub(" ", s)
    return re.sub(r"[\s,.;:|/\\\-]+", " ", s).strip()


def _is_structural_option(text) -> bool:
    """True when option is composer/template structure (tags + short glue), not a caption line.

    Caption-variant pools mix prose with nested tags (hair styles, poses, wardrobe lines).
    Expanding those injects seed-dependent terminal sentences into live preview.
    """
    raw = "" if text is None else str(text)
    if _WILDCARD_TAG_RE.search(raw) is None:
        return False
    return len(_non_tag_residue(raw)) <= _STRUCTURAL_RESIDUE_MAX


def _should_unwrap_preview_options(options) -> bool:
    """Unwrap only structural composers; freeze terminal and caption-variant pools as ``__tags__``."""
    if not options:
        return False
    if all(_is_terminal_option(o) for o in options):
        return False
    return all(_is_structural_option(o) for o in options)


def _escape_preview_literals(text: str) -> str:
    return text.replace("__", _PREVIEW_UNDERSCORE_ESC)


def _unescape_preview_literals(text: str) -> str:
    return text.replace(_PREVIEW_UNDERSCORE_ESC, "__")


def _marker_start(kind: str) -> str:
    return f"@@WC_START:{kind}@@"


def _marker_end(kind: str) -> str:
    return f"@@WC_END:{kind}@@"


def _wrap_option_for_kind(option, kind: str) -> str:
    """Wrap option body in leaf markers; keep the ``N::`` weight prefix outside."""
    raw = "" if option is None else str(option)
    m = re.match(r"^(\s*[0-9.]+::)(.*)$", raw, re.DOTALL)
    if m:
        return f"{m.group(1)}{_marker_start(kind)}{m.group(2)}{_marker_end(kind)}"
    return f"{_marker_start(kind)}{raw}{_marker_end(kind)}"


def _is_tag_only_option(text) -> bool:
    """True when option is a single wildcard tag (composer redirect), not terminal prose."""
    s = _PROB_PREFIX_RE.sub("", "" if text is None else str(text), count=1).strip()
    return bool(re.fullmatch(r"__[\w.\-+/*\\]+?__", s))


def _wrap_options_for_kind(options, kind: str):
    if not options:
        return options
    if all(_is_tag_only_option(o) for o in options) and kind not in SCENE_OVERRIDE_KINDS:
        return options
    return [_wrap_option_for_kind(opt, kind) for opt in options]


def _match_map(matched: set[str]) -> dict[str, bool]:
    return {
        param: kind in matched
        for param, kind in OVERRIDE_PARAM_TO_KIND.items()
    }


def _unwrap_nested_markers(text: str) -> str:
    """Replace innermost ``@@WC_START:k@@…@@WC_END:k@@`` pairs with their inner text."""
    prev = None
    while prev != text:
        prev = text
        text = _MARKER_PAIR_RE.sub(r"\2", text)
    return text


def _strip_all_markers(text: str) -> str:
    return _unwrap_nested_markers(text if text is not None else "")


def _extract_leaf_content(marked: str, kind: str) -> str | None:
    start = _marker_start(kind)
    end = _marker_end(kind)
    idx = marked.find(start)
    if idx < 0:
        return None
    pos = idx + len(start)
    depth = 1
    while pos < len(marked) and depth > 0:
        next_start = marked.find(start, pos)
        next_end = marked.find(end, pos)
        if next_end < 0:
            return None
        if next_start >= 0 and next_start < next_end:
            depth += 1
            pos = next_start + len(start)
            continue
        depth -= 1
        if depth == 0:
            inner = marked[idx + len(start):next_end]
            return _unwrap_nested_markers(inner).strip() or None
        pos = next_end + len(end)
    return None


def _override_kwargs_from_params(
    wardrobe_override: str = "",
    environment_override: str = "",
    medium_override: str = "",
    lighting_override: str = "",
    treatment_override: str = "",
    hair_override: str = "",
    body_override: str = "",
    age_override: str = "",
    eye_color_override: str = "",
    nationality_override: str = "",
    skin_override: str = "",
    face_override: str = "",
    jewelry_override: str = "",
    skin_tone_override: str = "",
    hair_color_override: str = "",
    breast_size_override: str = "",
    butt_size_override: str = "",
) -> dict[str, str]:
    return {
        "wardrobe_override": wardrobe_override,
        "environment_override": environment_override,
        "medium_override": medium_override,
        "lighting_override": lighting_override,
        "treatment_override": treatment_override,
        "hair_override": hair_override,
        "body_override": body_override,
        "age_override": age_override,
        "eye_color_override": eye_color_override,
        "nationality_override": nationality_override,
        "skin_override": skin_override,
        "face_override": face_override,
        "jewelry_override": jewelry_override,
        "skin_tone_override": skin_tone_override,
        "hair_color_override": hair_color_override,
        "breast_size_override": breast_size_override,
        "butt_size_override": butt_size_override,
    }


def resolve_expand_report(
    text: str,
    seed: int | None,
    engine_kwargs: dict | None = None,
    wardrobe_override: str = "",
    environment_override: str = "",
    medium_override: str = "",
    lighting_override: str = "",
    treatment_override: str = "",
    hair_override: str = "",
    body_override: str = "",
    age_override: str = "",
    eye_color_override: str = "",
    nationality_override: str = "",
    skin_override: str = "",
    face_override: str = "",
    jewelry_override: str = "",
    skin_tone_override: str = "",
    hair_color_override: str = "",
    breast_size_override: str = "",
    butt_size_override: str = "",
) -> dict:
    """Full expand with per-kind leaf capture for seed-aligned UI ghosts.

    Returns ``populated`` (marker-free full expand), ``leaves`` mapping override
    widget names to fully expanded terminal prose for kinds that were hit and not
    user-overridden, and ``matches`` mapping every override widget to whether its
    kind was visited during expansion.
    """
    source = text if text is not None else ""
    override_params = _override_kwargs_from_params(
        wardrobe_override=wardrobe_override,
        environment_override=environment_override,
        medium_override=medium_override,
        lighting_override=lighting_override,
        treatment_override=treatment_override,
        hair_override=hair_override,
        body_override=body_override,
        age_override=age_override,
        eye_color_override=eye_color_override,
        nationality_override=nationality_override,
        skin_override=skin_override,
        face_override=face_override,
        jewelry_override=jewelry_override,
        skin_tone_override=skin_tone_override,
        hair_color_override=hair_color_override,
        breast_size_override=breast_size_override,
        butt_size_override=butt_size_override,
    )
    active, skip_kinds = classify_overrides(**override_params)
    matched: set[str] = set()
    targets: dict[str, str] = {}

    def _record_target(kind: str, key) -> None:
        param = KIND_TO_PARAM.get(kind)
        if param:
            targets[param] = str(key).replace("\\", "/")

    wc = ensure_wildcards()

    def hook(key, options):
        k = _normalize_key(str(key))
        for kind in OVERRIDE_KIND_ORDER:
            if kind in skip_kinds and is_override_key(k, kind):
                matched.add(kind)
                _record_target(kind, key)
                return [""]
            value = active.get(kind)
            if value and is_override_key(k, kind):
                matched.add(kind)
                _record_target(kind, key)
                return [value]
        for kind in OVERRIDE_KIND_ORDER:
            if kind in active or kind in skip_kinds:
                continue
            if is_override_key(k, kind):
                matched.add(kind)
                _record_target(kind, key)
                if options is None:
                    return None
                return _wrap_options_for_kind(options, kind)
        return options

    marked = wc.process(source, seed, value_hook=hook, **(engine_kwargs or {}))

    populated = _strip_all_markers(marked)
    leaves: dict[str, str] = {}
    for kind in OVERRIDE_KIND_ORDER:
        if kind in active or kind in skip_kinds:
            continue
        param = KIND_TO_PARAM.get(kind)
        if not param:
            continue
        content = _extract_leaf_content(marked, kind)
        if content:
            leaves[param] = content

    return {
        "populated": _clean_expand_artifacts(populated),
        "leaves": leaves,
        "matches": _match_map(matched),
        "targets": targets,
    }


def reroll_override_value(
    text: str,
    seed: int | None,
    param_key: str,
    wardrobe_override: str = "",
    environment_override: str = "",
    medium_override: str = "",
    lighting_override: str = "",
    treatment_override: str = "",
    hair_override: str = "",
    body_override: str = "",
    age_override: str = "",
    eye_color_override: str = "",
    nationality_override: str = "",
    skin_override: str = "",
    face_override: str = "",
    jewelry_override: str = "",
    skin_tone_override: str = "",
    hair_color_override: str = "",
    breast_size_override: str = "",
    butt_size_override: str = "",
) -> dict[str, str]:
    """Pick a new pool line for one override slot without changing other overrides."""
    if param_key not in OVERRIDE_PARAM_TO_KIND:
        raise ValueError(f"unknown override key {param_key!r}")

    override_params = _override_kwargs_from_params(
        wardrobe_override=wardrobe_override,
        environment_override=environment_override,
        medium_override=medium_override,
        lighting_override=lighting_override,
        treatment_override=treatment_override,
        hair_override=hair_override,
        body_override=body_override,
        age_override=age_override,
        eye_color_override=eye_color_override,
        nationality_override=nationality_override,
        skin_override=skin_override,
        face_override=face_override,
        jewelry_override=jewelry_override,
        skin_tone_override=skin_tone_override,
        hair_color_override=hair_color_override,
        breast_size_override=breast_size_override,
        butt_size_override=butt_size_override,
    )
    current = override_params.get(param_key, "") or ""
    if is_skip_override(current):
        raise ValueError("cannot reroll skipped override")

    discovery_params = dict(override_params)
    discovery_params[param_key] = ""
    report = resolve_expand_report(text, seed, **discovery_params)
    target = (report.get("targets") or {}).get(param_key)
    if not target:
        raise ValueError("no matching wildcard target")

    ghost = (report.get("leaves") or {}).get(param_key, "") or ""
    compare_current = current.strip() if current.strip() else ghost.strip()

    reroll_params = dict(override_params)
    reroll_params[param_key] = ""
    tag = f"__{target}__"
    base_seed = 0 if seed is None else int(seed)

    last_candidate = ""
    for i in range(1, 25):
        candidate_seed = base_seed + i * 1000003
        expanded = expand_with_overrides(tag, candidate_seed, **reroll_params)
        candidate = _clean_expand_artifacts(expanded).strip()
        last_candidate = candidate
        if candidate and candidate != compare_current:
            return {"value": candidate, "target": target}

    return {"value": last_candidate, "target": target}


def expand_with_overrides(
    text: str,
    seed: int | None,
    engine_kwargs: dict | None = None,
    wardrobe_override: str = "",
    environment_override: str = "",
    medium_override: str = "",
    lighting_override: str = "",
    treatment_override: str = "",
    hair_override: str = "",
    body_override: str = "",
    age_override: str = "",
    eye_color_override: str = "",
    nationality_override: str = "",
    skin_override: str = "",
    face_override: str = "",
    jewelry_override: str = "",
    skin_tone_override: str = "",
    hair_color_override: str = "",
    breast_size_override: str = "",
    butt_size_override: str = "",
) -> str:
    source = text if text is not None else ""
    active, skip_kinds = classify_overrides(
        wardrobe_override=wardrobe_override,
        environment_override=environment_override,
        medium_override=medium_override,
        lighting_override=lighting_override,
        treatment_override=treatment_override,
        hair_override=hair_override,
        body_override=body_override,
        age_override=age_override,
        eye_color_override=eye_color_override,
        nationality_override=nationality_override,
        skin_override=skin_override,
        face_override=face_override,
        jewelry_override=jewelry_override,
        skin_tone_override=skin_tone_override,
        hair_color_override=hair_color_override,
        breast_size_override=breast_size_override,
        butt_size_override=butt_size_override,
    )

    wc = ensure_wildcards()
    kwargs = dict(engine_kwargs or {})

    # The umbrae engine also resolves {a|b}, switches, variables, [[aspect]] ...
    # so plain text (no __tags__) still goes through it.
    if not active and not skip_kinds:
        return _clean_expand_artifacts(wc.process(source, seed, **kwargs))

    def hook(key, options):
        k = _normalize_key(str(key))
        for kind in OVERRIDE_KIND_ORDER:
            if kind in skip_kinds and is_override_key(k, kind):
                return [""]
            value = active.get(kind)
            if value and is_override_key(k, kind):
                return [value]
        return options

    return _clean_expand_artifacts(wc.process(source, seed, value_hook=hook, **kwargs))


def preview_expand_with_overrides(
    text: str,
    seed: int | None,
    wardrobe_override: str = "",
    environment_override: str = "",
    medium_override: str = "",
    lighting_override: str = "",
    treatment_override: str = "",
    hair_override: str = "",
    body_override: str = "",
    age_override: str = "",
    eye_color_override: str = "",
    nationality_override: str = "",
    skin_override: str = "",
    face_override: str = "",
    jewelry_override: str = "",
    skin_tone_override: str = "",
    hair_color_override: str = "",
    breast_size_override: str = "",
    butt_size_override: str = "",
) -> str:
    """Structural preview expand: unwrap composers; leave caption ``__tags__`` literal.

    Routers/templates/leaves and short-glue identity composers unwrap so the next
    layer of ``__tags__`` is visible. Terminal pools and caption-variant pools
    (prose mixed with nested tags — hair styles, poses, wardrobe lines) stay as
    ``__key__`` so seed changes do not inject random terminal sentences.

    Active overrides inject exact user text. Nested ``__tags__`` inside an override
    string are escaped before the engine's ``process`` and restored afterward so
    the user sees what they typed.
    """
    source = text if text is not None else ""
    active, skip_kinds = classify_overrides(
        wardrobe_override=wardrobe_override,
        environment_override=environment_override,
        medium_override=medium_override,
        lighting_override=lighting_override,
        treatment_override=treatment_override,
        hair_override=hair_override,
        body_override=body_override,
        age_override=age_override,
        eye_color_override=eye_color_override,
        nationality_override=nationality_override,
        skin_override=skin_override,
        face_override=face_override,
        jewelry_override=jewelry_override,
        skin_tone_override=skin_tone_override,
        hair_color_override=hair_color_override,
        breast_size_override=breast_size_override,
        butt_size_override=butt_size_override,
    )

    wc = ensure_wildcards()

    def hook(key, options):
        k = _normalize_key(str(key))
        for kind in OVERRIDE_KIND_ORDER:
            if kind in skip_kinds and is_override_key(k, kind):
                return [""]
            value = active.get(kind)
            if value and is_override_key(k, kind):
                return [_escape_preview_literals(value)]
        if options is None:
            return None
        if not _should_unwrap_preview_options(options):
            return False          # caption pool: keep the __tag__ as written
        return options

    return _clean_expand_artifacts(
        _unescape_preview_literals(wc.process(source, seed, value_hook=hook))
    )
