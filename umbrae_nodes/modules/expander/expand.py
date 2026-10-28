# umbrae_nodes/modules/expander/expand.py — umbrae_nodes v0.9.0
#
# Core of "wildcard expander [umbrae]": expand one prompt N times over a seed
# plan, with per-draw edits (pin a line, pick another, skip, custom text) that
# follow the SAME seed into every prompt, and a tree of what every __tag__
# became (from the engine's trace, see umbrae_wildcards.process(trace=)).
#
# Nothing here is specific to a wildcard pack: edits address a draw by the
# tag's key (as the engine resolved it: 'folder/file', 'folder/' for a folder
# call, 'col*' for a pattern) and by occurrence (the 3rd __color__ in a prompt
# is n=2), or by key alone (every occurrence).

from __future__ import annotations

import json
import logging
import random
import re

from .. import umbrae_wildcards as wc

logger = logging.getLogger(__name__)

CLASS_NAME = "UmbraeWildcardExpander"
FEEDBACK_EVENT = "umbrae-expander-feedback"

# fixed mode: prompts are kept in one text box, separated by a line that is only ---
_FIXED_SPLIT_RE = re.compile(r"^\s*---\s*$", re.MULTILINE)
FIXED_SEPARATOR = "\n---\n"

MAX_COUNT = 100
SEED_MASK = 0xFFFFFFFFFFFFFFFF

DEFAULT_SETTINGS = {
    "seed_mode": "sequential",   # sequential: seed, seed+step, ... | random: seed, then derived from it
    "seed_step": 1,
    "dedupe": False,             # drop prompts identical to an earlier one (extra seeds fill the gap)
    "tidy": True,                # collapse ", ," / " ," / double spaces left by skipped draws
    "joiner": "\n",              # separator for the `joined` output
}

EDIT_MODES = ("line", "text", "skip")


# ── settings / edits parsing ──────────────────────────────────────────────────

def parse_settings(raw) -> dict:
    """Settings JSON (string or dict) -> full dict with defaults."""
    out = dict(DEFAULT_SETTINGS)
    data = raw
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return out
        try:
            data = json.loads(raw)
        except ValueError:
            logger.warning("[umbrae expander] settings is not valid JSON - defaults used")
            return out
    if not isinstance(data, dict):
        return out
    mode = str(data.get("seed_mode") or out["seed_mode"]).lower()
    out["seed_mode"] = mode if mode in ("sequential", "random") else "sequential"
    try:
        out["seed_step"] = int(data.get("seed_step", out["seed_step"]))
    except (TypeError, ValueError):
        pass
    if out["seed_step"] == 0:
        out["seed_step"] = 1
    out["dedupe"] = bool(data.get("dedupe", out["dedupe"]))
    out["tidy"] = bool(data.get("tidy", out["tidy"]))
    joiner = data.get("joiner", out["joiner"])
    if isinstance(joiner, str):
        out["joiner"] = joiner.replace("\\n", "\n")
    return out


def parse_edits(raw) -> list[dict]:
    """Edits JSON (string / dict / list) -> list of validated edit records:
    {key, n (int | None = every occurrence), mode ('line' | 'text' | 'skip'),
     idx (int | None), text (str | None)}.
    Accepts {"pins": [...]} (the UI's shape) or a bare list."""
    data = raw
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except ValueError:
            logger.warning("[umbrae expander] edits is not valid JSON - ignored")
            return []
    if isinstance(data, dict):
        data = data.get("pins") or data.get("edits") or []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if not key:
            continue
        key = key.replace("\\", "/").lower()
        n = item.get("n", None)
        if n is not None:
            try:
                n = int(n)
            except (TypeError, ValueError):
                n = None
            if n is not None and n < 0:
                n = None
        mode = str(item.get("mode") or "line").lower()
        if mode not in EDIT_MODES:
            mode = "line"
        idx = item.get("idx", None)
        if idx is not None:
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                idx = None
        text = item.get("text", None)
        if text is not None:
            text = str(text)
        if mode == "line" and idx is None and not text:
            continue
        out.append({"key": key, "n": n, "mode": mode, "idx": idx, "text": text})
    return out


def _edit_lookup(edits: list[dict]):
    exact = {}
    every = {}
    for e in edits:
        if e["n"] is None:
            every[e["key"]] = e
        else:
            exact[(e["key"], e["n"])] = e
    return exact, every


def make_pick_hook(edits: list[dict], notes: list[str] | None = None, hits: set | None = None):
    """pick_hook for umbrae_wildcards.process(): applies the edits to the draws
    they address. `notes` collects warnings, `hits` the (key, n) pairs that an
    edit actually touched (so the UI can show stale pins)."""
    if not edits:
        return None
    exact, every = _edit_lookup(edits)

    def hook(chain_key, n, options, picked):
        edit = exact.get((chain_key, n)) or every.get(chain_key)
        if edit is None:
            return None
        if hits is not None:
            hits.add((edit["key"], edit["n"]))
        mode = edit.get("mode", "line")
        if mode == "skip":
            return ""
        if mode == "text":
            return edit.get("text") or ""
        idx, text = edit.get("idx"), edit.get("text")
        want = text.strip() if isinstance(text, str) else None
        if idx is not None and 0 <= idx < len(options):
            if want is None or wc.strip_option_weight(options[idx]).strip() == want:
                return idx
        if want is not None:
            for i, opt in enumerate(options):
                if wc.strip_option_weight(opt).strip() == want:
                    return i
        if notes is not None:
            where = f"#{n + 1}" if edit.get("n") is not None else "(every)"
            notes.append(f"pin on __{chain_key}__ {where}: line not found any more - random draw used")
        return None

    return hook


# ── seeds ─────────────────────────────────────────────────────────────────────

def seed_plan(seed: int, settings: dict):
    """Endless generator of seeds for the batch: the first is always `seed`."""
    seed = int(seed) & SEED_MASK
    yield seed
    if settings.get("seed_mode") == "random":
        rng = random.Random(seed)
        while True:
            yield rng.getrandbits(64) & SEED_MASK
    step = int(settings.get("seed_step") or 1)
    i = 1
    while True:
        yield (seed + i * step) & SEED_MASK
        i += 1


# ── tidy ──────────────────────────────────────────────────────────────────────

_TIDY_RULES = (
    (re.compile(r"[^\S\n]+"), " "),                     # runs of spaces / tabs
    (re.compile(r"\s+,"), ","),                         # space before comma
    (re.compile(r",(\s*,)+"), ","),                     # ", ," / ",,"
    (re.compile(r",\s*\.(?=\s|$)"), "."),               # ", ." -> "."
    (re.compile(r"\.\s*,"), ","),                       # ". ," -> ","
    (re.compile(r"\(\s*\)"), ""),                       # empty ()
    (re.compile(r"(?m)^[ ,]+"), ""),                    # leading commas on a line
    (re.compile(r"(?m)[ ,]+$"), ""),                    # trailing commas / spaces on a line
    (re.compile(r"\n{3,}"), "\n\n"),                    # at most one blank line
)


def tidy_text(text: str) -> str:
    """Remove the punctuation debris a skipped or empty draw leaves behind."""
    if not text:
        return ""
    out = text
    prev = None
    while prev != out:
        prev = out
        for rx, rep in _TIDY_RULES:
            out = rx.sub(rep, out)
    return out.strip()


# ── draw tree from the engine trace ───────────────────────────────────────────

def _display_text(raw: str) -> str:
    s = wc.strip_chain_markers(raw)
    s = wc.strip_protect_markers(s)
    try:
        s = wc.strip_aspect_markers(wc.finalize_output(s))
    except Exception:
        pass
    return s.strip()


def build_draw_tree(trace: dict) -> list[dict]:
    """trace from process(trace=) -> nested draws in document order:
    {seq, key, tag, n, idx, count, line, text, forced, children}. `line` is the
    raw line that was drawn (tags unexpanded), `text` what it became."""
    draws = trace.get("draws") or []
    marked = trace.get("marked") or ""
    by_seq = {d["seq"]: d for d in draws}
    roots: list[dict] = []
    stack: list[tuple[dict, int]] = []     # (node, start of inner text)
    seen = set()
    i = 0
    S, SEP, E, T = wc._CHAIN_START, wc._CHAIN_SEP, wc._CHAIN_END, wc._TRACE_SEP
    while i < len(marked):
        s = marked.find(S, i)
        e = marked.find(E, i)
        if s < 0 and e < 0:
            break
        if e < 0 or (0 <= s < e):
            sep = marked.find(SEP, s)
            if sep < 0:
                break
            label = marked[s + 1:sep]
            seq = None
            if T in label:
                try:
                    seq = int(label.rsplit(T, 1)[1])
                except ValueError:
                    seq = None
            rec = by_seq.get(seq) if seq is not None else None
            node = {
                "seq": seq,
                "key": rec["key"] if rec else label.split(T)[0].rpartition("#")[0],
                "tag": rec["tag"] if rec else "",
                "n": rec["n"] if rec else None,
                "idx": rec["idx"] if rec else None,
                "count": rec["count"] if rec else None,
                "line": (rec.get("line") or "") if rec else "",
                "forced": bool(rec and rec.get("forced")),
                "text": "",
                "children": [],
            }
            if seq is not None:
                seen.add(seq)
            (stack[-1][0]["children"] if stack else roots).append(node)
            stack.append((node, sep + 1))
            i = sep + 1
        else:
            if stack:
                node, start = stack.pop()
                node["text"] = _display_text(marked[start:e])
            i = e + 1
    while stack:                                   # unbalanced (should not happen)
        node, start = stack.pop()
        node["text"] = _display_text(marked[start:])
    # draws whose marker vanished (e.g. inside a dropped option) are still listed
    for d in draws:
        if d["seq"] in seen:
            continue
        roots.append({
            "seq": d["seq"], "key": d["key"], "tag": d["tag"], "n": d["n"], "idx": d["idx"],
            "count": d["count"], "line": d.get("line") or "", "forced": bool(d.get("forced")),
            "text": _display_text(d.get("line") or ""), "children": [], "detached": True,
        })
    return roots


# ── expansion ─────────────────────────────────────────────────────────────────

def expand_one(text: str, seed: int, *, switches="", edits=None, settings=None,
               cycle_scope=None, aspect=None, aspect_final=False, want_tree=True) -> dict:
    """One prompt: {seed, text, notes, draws}. Pure (no cycle reset)."""
    settings = settings or DEFAULT_SETTINGS
    notes: list[str] = []
    hits: set = set()
    trace: dict = {} if want_tree else None
    hook = make_pick_hook(parse_edits(edits or []), notes, hits)
    out = wc.process(text or "", int(seed), cycle_scope=cycle_scope,
                     switches=switches if isinstance(switches, str) else "",
                     aspect=aspect or {}, aspect_final=aspect_final,
                     pick_hook=hook, trace=trace)
    out = wc.finalize_output(out)
    out = wc.strip_aspect_markers(out)
    if settings.get("tidy", True):
        out = tidy_text(out)
    else:
        out = out.strip()
    result = {"seed": int(seed), "text": out, "notes": notes,
              "hits": sorted([k, -1 if n is None else n] for k, n in hits)}
    if want_tree:
        result["draws"] = build_draw_tree(trace)
    return result


def expand_batch(text: str, seed: int, count: int, *, switches="", edits=None, settings=None,
                 cycle_scope=None, aspect=None, aspect_final=False, want_trees=True) -> dict:
    """`count` prompts over the seed plan. dedupe: identical prompts are dropped
    and further seeds tried (up to 4x count)."""
    settings = parse_settings(settings) if not isinstance(settings, dict) or set(settings) != set(DEFAULT_SETTINGS) else settings
    edits = edits if isinstance(edits, list) else parse_edits(edits)
    try:
        count = max(1, min(MAX_COUNT, int(count)))
    except (TypeError, ValueError):
        count = 1
    prompts: list[dict] = []
    seen_text: set[str] = set()
    plan = seed_plan(seed, settings)
    attempts = 0
    limit = count * 4 if settings.get("dedupe") else count
    while len(prompts) < count and attempts < limit:
        attempts += 1
        s = next(plan)
        one = expand_one(text, s, switches=switches, edits=edits, settings=settings,
                         cycle_scope=cycle_scope, aspect=aspect, aspect_final=aspect_final,
                         want_tree=want_trees)
        if settings.get("dedupe"):
            sig = one["text"].strip().lower()
            if sig in seen_text:
                continue
            seen_text.add(sig)
        prompts.append(one)
    notes: list[str] = []
    for p in prompts:
        for n in p.get("notes") or []:
            if n not in notes:
                notes.append(n)
    if settings.get("dedupe") and len(prompts) < count:
        notes.append(f"dedupe: only {len(prompts)} distinct prompt(s) in {attempts} seeds")
    return {
        "prompts": prompts,
        "seeds": [p["seed"] for p in prompts],
        "notes": notes,
        "settings": settings,
        "edits": edits,
    }


def split_fixed(text: str) -> list[str]:
    """fixed mode: the box holds prompts separated by a line that is only ---"""
    parts = [p.strip() for p in _FIXED_SPLIT_RE.split(text or "")]
    return [p for p in parts if p] or [""]


def join_fixed(prompts: list[str]) -> str:
    return FIXED_SEPARATOR.join(p.strip() for p in prompts)
