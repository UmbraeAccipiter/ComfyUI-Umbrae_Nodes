# umbrae_wildcards.py — umbrae_nodes v0.9.0 (pick_hook + trace for the wildcard expander)
#
# Wildcard engine for "wildcard processor [umbrae]".
#
# Derived from ComfyUI-Impact-Pack (modules/impact/wildcards.py, v8.28.3)
# Copyright (C) Dr.Lt.Data (ltdrdata) and contributors.
# Licensed under the GNU General Public License v3.0 (GPL-3.0).
# This file is a modified version, distributed under the same license:
#
#   This program is free software: you can redistribute it and/or modify it
#   under the terms of the GNU General Public License as published by the Free
#   Software Foundation, either version 3 of the License, or (at your option)
#   any later version. This program is distributed in the hope that it will be
#   useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General
#   Public License for more details: <https://www.gnu.org/licenses/>.
#
# Modifications (Umbrae):
#   * earlier local patches: custom-path fallback, in-place cache refresh,
#     `count$$$sep1$sep2$$` joins, {@name} variables, {a^b^c} cycles
#   * v0.8.2: standalone (no Impact imports); reads umbrae_nodes/wildcards and
#     Impact's custom wildcards folder (umbrae wins on duplicate keys);
#     group prefixes  -::  (written order)  and  N+::  (no-repeat history);
#     LoRA / SEGS helpers removed (processor only); per-node cycle reset.
#   * v0.8.3: switches {&name=N} / {&name:a|b|c} (+ node `switches` box,
#     deferred resolution); finalize_output() for \n line breaks and \& literal.
#   * v0.8.4: undefined / non-number switch -> one weighted random value per
#     name per run, shared by every group of that name (warning logged).
#   * v0.8.6: {@!name=...} variable override, {&!name=...} switch override,
#     {!find=replace} (case-following) / {!!find=replace} (exact) text
#     replacement, applied last in one whole-word pass; \! literal.
#   * v0.9.5: {!!!find=replace} any-case match, replacement inserted exactly as
#     written; {!!!!find=replace} = alias of {!!} (exact match, exact insert).
#   * v0.8.7: [[aspect]] inserts an orientation description line for the
#     image size connected to the node (latent or width/height); bracket
#     tokens [orientation] [ratio] [width] [height] filled last; [W:H] typed
#     override. Shipped wildcard_examples/ folder as the lowest-priority
#     wildcard root (user files override, never overwritten by an update).
#   * v0.8.8: relative tags __./x__ and __../x__ (resolved when the file is
#     loaded, so a pack folder can be renamed or moved); __x.txt__ works like
#     __x__; __folder/__ (trailing slash) and a missing file both pool every
#     file under that folder; recursion guard - a line already open on the
#     current branch is never drawn again (self-referencing files terminate
#     instead of repeating the same line until the 100-pass limit).
#     process(value_hook=) lets a caller (clause expander) override or wrap
#     the options of any key for ONE call - no global monkeypatching.

import configparser
import logging
import math
import os
import random
import re
import threading

import numpy as np
import yaml

# umbrae_nodes/wildcards - highest priority source (user files, never shipped).
# (this file lives in umbrae_nodes/modules/; the user folders are in the pack root)
_PACK_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
wildcards_path = os.path.join(_PACK_ROOT, "wildcards")
# umbrae_nodes/wildcard_examples - LOWEST priority source: shipped with the pack
# (aspect defaults + syntax examples). A same-named file in any other root wins,
# so users edit copies in their own folder and updates never overwrite them.
examples_path = os.path.join(_PACK_ROOT, "wildcard_examples")

RE_WildCardQuantifier = re.compile(r"(?P<quantifier>\d+)#__(?P<keyword>[\w.\-+/*\\]+?)__", re.IGNORECASE)
wildcard_lock = threading.Lock()
wildcard_dict = {}

# Cache size limit in bytes: text on disk below this -> full cache (v0.8.9: 250MB, Impact default was 50MB)
WILDCARD_CACHE_LIMIT = 250 * 1024 * 1024
# Flag to track if on-demand mode is active
_on_demand_mode = False

# Two-phase loading support
# available_wildcards: All discovered wildcard files (metadata only)
# loaded_wildcards: Actually loaded wildcard data
available_wildcards = {}  # key -> file_path mapping
loaded_wildcards = {}     # key -> loaded data
key_sources = {}          # YAML key -> file it came from (relative, for the picker)
_roots_cache = []         # roots of the last wildcard_load() (for relative-tag bases)


class LazyWildcardLoader:
    """
    Lazy loader for wildcard data to reduce memory usage.
    Acts as a list-like proxy that loads data on first access.
    """
    def __init__(self, file_path, file_type='txt', base_key=None):
        self.file_path = file_path
        self.file_type = file_type
        self.base_key = base_key      # folder key the file lives in (None = work it out)
        self._data = None
        self._loaded = False

    def _load_txt(self):
        """Load .txt wildcard file"""
        return load_txt_wildcard(self.file_path, self.base_key)

    def _load_yaml(self):
        """Load .yaml/.yml wildcard file"""
        try:
            with open(self.file_path, 'r', encoding="ISO-8859-1") as f:
                return yaml.load(f, Loader=yaml.FullLoader)
        except (yaml.reader.ReaderError, UnicodeDecodeError):
            with open(self.file_path, 'r', encoding="UTF-8", errors="ignore") as f:
                return yaml.load(f, Loader=yaml.FullLoader)

    def get_data(self):
        """Get wildcard data, loading if necessary"""
        if not self._loaded:
            with wildcard_lock:
                if not self._loaded:  # Double-check locking
                    if self.file_type == 'txt':
                        self._data = self._load_txt()
                    elif self.file_type in ('yaml', 'yml'):
                        self._data = self._load_yaml()
                    self._loaded = True
        return self._data

    # List-like interface methods
    def __getitem__(self, index):
        """Support indexing like a list"""
        return self.get_data()[index]

    def __iter__(self):
        """Support iteration"""
        return iter(self.get_data())

    def __len__(self):
        """Support len() function"""
        return len(self.get_data())

    def __contains__(self, item):
        """Support 'in' operator"""
        return item in self.get_data()

    def __repr__(self):
        """String representation"""
        if self._loaded:
            return f"LazyWildcardLoader({self.file_path}, loaded={len(self._data)} items)"
        return f"LazyWildcardLoader({self.file_path}, not loaded)"

    def __bool__(self):
        """Support boolean evaluation"""
        return len(self.get_data()) > 0

    # Common list methods that may be used
    def count(self, value):
        """Count occurrences of value"""
        return self.get_data().count(value)

    def index(self, value, start=0, stop=None):
        """Find index of value"""
        if stop is None:
            return self.get_data().index(value, start)
        return self.get_data().index(value, start, stop)


def calculate_directory_size(directory_path, limit=None):
    """
    Calculate total size of all wildcard files in directory.

    Args:
        directory_path: Path to scan
        limit: Optional size limit in bytes. If provided, stops scanning immediately
               when total_size >= limit (for fast mode detection)

    Returns:
        Total size in bytes (or limit if exceeded)
    """
    total_size = 0
    try:
        for root, directories, files in os.walk(directory_path, followlinks=True):
            for file in files:
                if file.endswith(('.txt', '.yaml', '.yml')):
                    file_path = os.path.join(root, file)
                    try:
                        total_size += os.path.getsize(file_path)

                        # Early termination: stop scanning when limit exceeded
                        if limit and total_size >= limit:
                            return total_size
                    except (OSError, FileNotFoundError):
                        pass
    except (OSError, FileNotFoundError):
        pass
    return total_size


def scan_wildcard_metadata(wildcard_path):
    """
    Scan directory for wildcard files and collect metadata only (no data loading).

    This is much faster than full loading for large wildcard collections.
    Only stores file paths in available_wildcards, actual data loaded on-demand.

    Args:
        wildcard_path: Directory to scan for wildcard files

    Returns:
        Number of wildcard files discovered
    """
    global available_wildcards

    discovered = 0
    try:
        for root, directories, files in os.walk(wildcard_path, followlinks=True):
            for file in files:
                if file.endswith('.txt'):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, wildcard_path)
                    key = wildcard_normalize(os.path.splitext(rel_path)[0])
                    available_wildcards[key] = file_path
                    discovered += 1
                elif file.endswith('.yaml') or file.endswith('.yml'):
                    file_path = os.path.join(root, file)
                    rel_path = os.path.relpath(file_path, wildcard_path)
                    # YAML files are stored with their extension for proper loading
                    key_base = wildcard_normalize(os.path.splitext(rel_path)[0])
                    available_wildcards[key_base] = file_path
                    discovered += 1
    except (OSError, FileNotFoundError) as e:
        logging.warning(f"[umbrae wildcards] Error scanning wildcard directory {wildcard_path}: {e}")

    return discovered


def get_wildcard_list():
    """
    Get list of all available wildcards.

    Returns:
        - In full cache mode: all loaded wildcards
        - In on-demand mode: every discovered .txt wildcard plus everything
          already loaded (YAML keys). v0.8.9: before this the list held only
          the loaded keys, i.e. just the YAML ones, so TXT folders never showed.
    """
    with wildcard_lock:
        if _on_demand_mode:
            keys = [k for k, path in available_wildcards.items()
                    if str(path).lower().endswith('.txt')]
            seen = set(keys)
            keys.extend(k for k in loaded_wildcards.keys() if k not in seen)
            return [f"__{x}__" for x in keys]
        return [f"__{x}__" for x in wildcard_dict.keys()]


def get_wildcard_entries():
    """Picker entries [{tag, label}], sorted so every folder stays together.
    TXT: label = key (the folder is already in it). YAML keys come from file
    CONTENT, so they are filed under the .yaml's own folder:
    'uw-modular/krea2/x.yaml > key'. Inserting an entry always adds its tag."""
    tags = get_wildcard_list()
    out = []
    for t in tags:
        key = t[2:-2]
        src = key_sources.get(key)
        out.append({'tag': t, 'label': f"{src} \u203a {key}" if src else key})
    out.sort(key=lambda e: e['label'].lower())
    return out


def get_loaded_wildcard_list():
    """
    Get list of actually loaded wildcards (on-demand mode only).

    Returns:
        List of wildcards that have been loaded into memory.
        In full cache mode, returns same as get_wildcard_list().
    """
    with wildcard_lock:
        if _on_demand_mode:
            return [f"__{x}__" for x in loaded_wildcards.keys()]
        return [f"__{x}__" for x in wildcard_dict.keys()]


def get_wildcard_dict():
    global wildcard_dict
    with wildcard_lock:
        return wildcard_dict


def _custom_nodes_dirs():
    """Every custom_nodes directory ComfyUI knows about, plus our own parent."""
    dirs = []
    try:
        import folder_paths
        dirs.extend(folder_paths.get_folder_paths("custom_nodes"))
    except Exception:
        pass
    dirs.append(os.path.dirname(_PACK_ROOT))        # our own custom_nodes folder
    out = []
    for d in dirs:
        d = os.path.abspath(d)
        if d not in out and os.path.isdir(d):
            out.append(d)
    return out


def get_impact_custom_wildcards_path(warn=False):
    """
    Locate Impact Pack's custom wildcards folder, if one exists.

    Looks for a `comfyui-impact-pack` folder (any case, - or _) in custom_nodes.
    Uses the `custom_wildcards` path from its impact-pack.ini when that path
    exists on this machine, otherwise `<impact-pack>/custom_wildcards`. Works
    even if Impact itself is uninstalled but the folder was left behind.
    Returns None when nothing usable exists.
    """
    for base in _custom_nodes_dirs():
        try:
            entries = os.listdir(base)
        except OSError:
            continue
        for name in entries:
            if name.lower().replace('_', '-') != 'comfyui-impact-pack':
                continue
            pack = os.path.join(base, name)
            ini = os.path.join(pack, 'impact-pack.ini')
            if os.path.isfile(ini):
                try:
                    cp = configparser.ConfigParser()
                    cp.read(ini, encoding='utf-8')
                    configured = cp.get('default', 'custom_wildcards', fallback='').strip()
                    if configured:
                        if os.path.isdir(configured):
                            return os.path.abspath(configured)
                        if warn:
                            logging.warning(f"[umbrae wildcards] Impact custom_wildcards path not found: "
                                            f"'{configured}'. Trying '{os.path.join(pack, 'custom_wildcards')}'")
                except Exception as e:
                    if warn:
                        logging.warning(f"[umbrae wildcards] could not read {ini}: {e}")
            default_custom = os.path.join(pack, 'custom_wildcards')
            if os.path.isdir(default_custom):
                return os.path.abspath(default_custom)
    return None


def get_wildcard_roots(warn=False):
    """Existing wildcard folders in PRIORITY order (first wins on duplicate keys):
    umbrae_nodes/wildcards, then Impact's custom wildcards folder, then the
    shipped umbrae_nodes/wildcard_examples."""
    roots = []
    try:
        os.makedirs(wildcards_path, exist_ok=True)
    except OSError:
        pass
    if os.path.isdir(wildcards_path):
        roots.append(wildcards_path)
    impact_path = get_impact_custom_wildcards_path(warn=warn)
    if impact_path and os.path.abspath(impact_path) not in roots:
        roots.append(os.path.abspath(impact_path))
    if os.path.isdir(examples_path) and examples_path not in roots:
        roots.append(examples_path)
    return roots


def find_wildcard_file(key):
    """
    Dynamically find a wildcard file by key (on-demand mode), searching the
    wildcard roots in priority order (umbrae first).

    For YAML nested keys like "colors/warm", falls back to the parent file
    "colors.yaml".

    Returns:
        Tuple of (file_path, is_yaml_nested) if found, (None, False) otherwise
    """
    roots = get_wildcard_roots()

    # Case 1: Direct file match (TXT or top-level YAML)
    potential_paths = [f"{key}.txt", f"{key}.yaml", f"{key}.yml"]
    for root in roots:
        for rel_path in potential_paths:
            file_path = os.path.join(root, rel_path)
            if os.path.isfile(file_path):
                return (file_path, file_path.endswith(('.yaml', '.yml')))

    # Case 2: YAML nested key (e.g., "colors/warm" -> "colors.yaml")
    if '/' in key:
        parent_key = key.split('/')[0]
        yaml_paths = [f"{parent_key}.yaml", f"{parent_key}.yml"]
        for root in roots:
            for rel_path in yaml_paths:
                file_path = os.path.join(root, rel_path)
                if os.path.isfile(file_path):
                    return (file_path, True)

    return (None, False)


def get_wildcard_value(key):
    """
    Get wildcard value from dictionary, automatically handling LazyWildcardLoader
    and on-demand loading.

    Args:
        key: wildcard key

    Returns:
        List of wildcard options (loaded if necessary), or None if not found
    """
    global loaded_wildcards

    # On-demand mode: dynamic file discovery and loading
    if _on_demand_mode:
        # Check if already loaded in cache (TXT on-demand or YAML pre-loaded)
        if key in loaded_wildcards:
            return loaded_wildcards[key]

        # Try to find and load TXT files dynamically
        # YAML files are already pre-loaded, so if not in cache, it doesn't exist
        file_path, is_yaml = find_wildcard_file(key)
        if file_path is None:
            # Fallback: Try pattern matching to find wildcards at any depth
            # Example: "dragon" matches "dragon.txt", "fantasy/dragon.txt", "dragon/fire.txt", etc.
            matched_keys = []
            for k in available_wildcards.keys():
                if (k == key or
                    k.endswith('/' + key) or
                    k.startswith(key + '/') or
                    ('/' + key + '/') in k):
                    matched_keys.append(k)

            if matched_keys:
                # Collect all options from matched keys
                all_options = []
                for matched_key in matched_keys:
                    # Load each matched wildcard
                    value = get_wildcard_value(matched_key)
                    if value:
                        all_options.extend(value)

                if all_options:
                    # Cache the combined result
                    loaded_wildcards[key] = all_options
                    logging.info(f"[umbrae wildcards] Wildcard '{key}' resolved via depth-agnostic pattern matching to {len(matched_keys)} keys: {matched_keys}")
                    return all_options

            return None

        # YAML files should already be loaded
        if is_yaml or file_path.endswith(('.yaml', '.yml')):
            # YAML was pre-loaded but key not found
            logging.warning(f"[umbrae wildcards] YAML wildcard '{key}' not found (pre-load issue)")
            return None

        # Load TXT file on-demand
        try:
            data = load_txt_wildcard(file_path)
            loaded_wildcards[key] = data
            logging.debug(f"[umbrae wildcards] Loaded TXT wildcard '{key}' on-demand from {file_path}")
            return data
        except Exception as e:
            logging.warning(f"[umbrae wildcards] Failed to load wildcard {key} from {file_path}: {e}")
            return None

    # Full cache mode or fallback: use wildcard_dict
    value = wildcard_dict.get(key)
    if isinstance(value, LazyWildcardLoader):
        return value.get_data()
    return value


def load_txt_wildcard(file_path, base_key=None):
    """Load a .txt wildcard file. Relative tags (__./x__, __../x__) are resolved
    against the folder the file lives in (base_key; worked out from the wildcard
    roots when None)."""
    try:
        with open(file_path, 'r', encoding="ISO-8859-1") as f:
            lines = f.read().splitlines()
    except (yaml.reader.ReaderError, UnicodeDecodeError):
        with open(file_path, 'r', encoding="UTF-8", errors="ignore") as f:
            lines = f.read().splitlines()
    lines = [x for x in lines if x.strip() and not x.strip().startswith('#')]
    if base_key is None:
        base_key = base_key_for_file(file_path)
    return relativize_options(lines, base_key)


def load_yaml_wildcard(file_path, key_prefix=''):
    """Load a .yaml/.yml wildcard file and expand nested structures"""
    global loaded_wildcards

    try:
        with open(file_path, 'r', encoding="ISO-8859-1") as f:
            yaml_data = yaml.load(f, Loader=yaml.FullLoader)
    except (yaml.reader.ReaderError, UnicodeDecodeError):
        with open(file_path, 'r', encoding="UTF-8", errors="ignore") as f:
            yaml_data = yaml.load(f, Loader=yaml.FullLoader)

    if not yaml_data or not isinstance(yaml_data, dict):
        return []

    # Relative tags inside the YAML are anchored to the FILE's folder (v0.8.8).
    base = base_key_for_file(file_path)
    rel = lambda vals: relativize_options(vals, base)

    # For nested YAML structures, expand into loaded_wildcards
    result = []
    for k, v in yaml_data.items():
        if isinstance(v, list):
            sub_key = wildcard_normalize(f"{key_prefix}/{k}") if key_prefix else wildcard_normalize(k)
            v = rel(v)
            loaded_wildcards[sub_key] = v
            result.extend(v)
        elif isinstance(v, dict):
            # Recursive nested dict - register both parent and children keys
            # Collect all values from nested structure for parent key
            parent_key = wildcard_normalize(k)
            parent_values = []

            for k2, v2 in v.items():
                sub_key = wildcard_normalize(f"{k}/{k2}")
                if isinstance(v2, list):
                    v2 = rel(v2)
                    loaded_wildcards[sub_key] = v2
                    parent_values.extend(v2)
                elif isinstance(v2, str):
                    v2 = rel([v2])[0]
                    loaded_wildcards[sub_key] = [v2]
                    parent_values.append(v2)
                elif isinstance(v2, (int, float)):
                    loaded_wildcards[sub_key] = [str(v2)]
                    parent_values.append(str(v2))

            # Register parent key with all child values
            if parent_values:
                loaded_wildcards[parent_key] = parent_values
                result.extend(parent_values)
        elif isinstance(v, str):
            sub_key = wildcard_normalize(f"{key_prefix}/{k}") if key_prefix else wildcard_normalize(k)
            loaded_wildcards[sub_key] = rel([v])
        elif isinstance(v, (int, float)):
            sub_key = wildcard_normalize(f"{key_prefix}/{k}") if key_prefix else wildcard_normalize(k)
            loaded_wildcards[sub_key] = [str(v)]

    return result if result else list(yaml_data.values())


def is_on_demand_mode():
    """Check if wildcards are running in on-demand mode"""
    return _on_demand_mode


def wildcard_normalize(x):
    return x.replace("\\", "/").replace(' ', '-').lower()


# ---------------------------------------------------------------------------
# v0.8.8: relative tags, extension stripping, folder calls, recursion chain
# ---------------------------------------------------------------------------
_KEY_EXT_RE = re.compile(r'\.(txt|ya?ml)$', re.IGNORECASE)
# __./x__  __../x__  __./__  __..__  (a trailing / is kept = folder call)
_REL_TAG_RE = re.compile(r'__(\.\.?(?:/[\w.\-+/*\\]*?)?)__')

# Chain markers: every inserted wildcard line is wrapped as
#   START key#index SEP line END
# so a tag found later can see which (key, line) picks are open above it and
# never draw one of those lines again. Stripped before process() returns.
_CHAIN_START = '\uE010'
_CHAIN_SEP = '\uE011'
_CHAIN_END = '\uE012'
_CHAIN_LABEL_RE = re.compile('\uE010[^\uE011]*\uE011')
# v0.9.0: with process(trace=...) the label is  key#index\uE015seq  so the
# caller can map every marker back to its draw record (see chain_at).
_TRACE_SEP = '\uE015'


# Protected spans {-=text=-} (v0.8.9): shielded from {!find=...} replacements.
_PROT_START = '\uE013'
_PROT_END = '\uE014'
_PROT_RE = re.compile(r'(?<!\\)\{-=(.*?)=-\}', re.DOTALL)
_PROT_BARE_RE = re.compile(r'(?<![\w\\-])-=(.*?)=-', re.DOTALL)


def protect_spans(text):
    """{-=text=-} and the bare -=text=- (inside option lists) -> text wrapped in
    private-use markers (the {-= / -= wrapper goes away)."""
    if '-=' not in text:
        return text
    wrap = lambda m: _PROT_START + m.group(1) + _PROT_END
    return _PROT_BARE_RE.sub(wrap, _PROT_RE.sub(wrap, text))


def in_protected_span(text, pos):
    """True when text[pos] sits inside an open {-= =-} span."""
    head = text[:pos]
    return head.count(_PROT_START) > head.count(_PROT_END)


def split_protected_options(body):
    """'a|-=b|c=-|d' (markers already private-use) -> [(clean_text, protected)].
    An option is protected when it starts inside / opens a span, or carries an
    unbalanced marker. Markers are removed from the returned text."""
    out, depth = [], 0
    for raw in body.split('|'):
        opens, closes = raw.count(_PROT_START), raw.count(_PROT_END)
        starts_inside = depth > 0 or raw.lstrip().startswith(_PROT_START)
        protected = starts_inside or opens != closes
        depth = max(0, depth + opens - closes)
        out.append((strip_protect_markers(raw), protected))
    return out


def wrap_protected(text):
    return _PROT_START + text + _PROT_END


def option_weight_of(text):
    m = re.match(r'^\s*([0-9.]+)::', str(text))
    try:
        return float(m.group(1)) if m else 1.0
    except ValueError:
        return 1.0


def strip_option_weight(text):
    return re.sub(r'^\s*[0-9.]+::', '', str(text), count=1)


def locked_group_source(source, override, mode):
    """Rewrite a file-defined option list for an @! override that has protected
    options (-=..=-). mode '' : every UNprotected option becomes the override
    (own weight kept), so the override only shows when such an option is drawn.
    mode 'r': all unprotected options collapse into ONE entry (override) that
    inherits the highest weight among them, before the draw.
    Returns None when the source has no protected options / is not a list."""
    body = source.strip()
    if body.startswith('{') and body.endswith('}') and _balanced_close(body, 1) == len(body) - 1:
        body = body[1:-1]
    if _PROT_START not in body and _PROT_END not in body:
        return None
    if len(_split_top(body, '|')) != len(body.split('|')):
        return None                         # nested groups with pipes: leave alone
    items = split_protected_options(body)
    if not any(p for _t, p in items) or all(p for _t, p in items):
        return None if not any(p for _t, p in items) else '{' + '|'.join(wrap_protected(t) for t, _p in items) + '}'
    ov = override.strip()
    if len(_split_top(ov, '|')) > 1:
        ov = '{' + ov + '}'
    parts, replaced = [], []
    for t, prot in items:
        if prot:
            parts.append(wrap_protected(t))
        elif mode == 'r':
            replaced.append(option_weight_of(t))
        else:
            w = option_weight_of(t)
            parts.append((f'{w:g}::' if w != 1 else '') + ov)
    if mode == 'r' and replaced:
        w = max(replaced)
        parts.append((f'{w:g}::' if w != 1 else '') + ov)
    return '{' + '|'.join(parts) + '}'


def pin_index(options, choice):
    """choice: 1-based number, or text found in an option -> index or None."""
    c = str(choice).strip()
    if re.fullmatch(r'\d+', c):
        i = int(c) - 1
        return i if 0 <= i < len(options) else None
    pat = re.compile(r'(?<!\w)' + re.escape(c) + r'(?!\w)', re.IGNORECASE)
    for i, o in enumerate(options):
        if pat.search(strip_option_weight(o)):
            return i
    return None


def pin_list_key(options):
    return tuple(strip_option_weight(o).strip().lower() for o in options)


def extract_pins(text):
    """Remove every {&=CHOICE:TARGET} -> (text, [(choice, target)])."""
    pins, pieces, pos = [], [], 0
    while True:
        i = text.find('{&=', pos)
        if i < 0 or (i > 0 and text[i - 1] == '\\'):
            if i >= 0:
                pieces.append(text[pos:i + 3]); pos = i + 3; continue
            pieces.append(text[pos:])
            break
        end = _balanced_close(text, i + 3)
        if end < 0:
            pieces.append(text[pos:])
            break
        body = text[i + 3:end]
        choice, colon, target = body.partition(':')
        if colon and choice.strip() and target.strip():
            pins.append((choice.strip(), target.strip()))
            pieces.append(text[pos:i])
        else:
            pieces.append(text[pos:end + 1])
        pos = end + 1
    return ''.join(pieces), pins


def strip_protect_markers(text):
    return text.replace(_PROT_START, '').replace(_PROT_END, '')


def restore_protect_syntax(text):
    return text.replace(_PROT_START, '{-=').replace(_PROT_END, '=-}')


def strip_key_extension(key):
    """__x.txt__ / __x.yaml__ mean the same as __x__ (keys never carry extensions)."""
    return _KEY_EXT_RE.sub('', key)


def resolve_relative_key(rel, base_key):
    """Resolve './x' or '../x' against base_key (the folder key the calling
    file lives in; '' = wildcard root). Returns the absolute key, '' when it
    points at the root itself. A trailing '/' (folder call) is kept."""
    rel = wildcard_normalize(rel)
    folder = rel.endswith('/')
    segs = [s for s in base_key.split('/') if s] if base_key else []
    for part in rel.split('/'):
        if part in ('', '.'):
            continue
        if part == '..':
            if segs:
                segs.pop()
            continue
        segs.append(part)
    key = '/'.join(segs)
    if folder and key:
        key += '/'
    return key


def resolve_relative_tags(text, base_key):
    """Rewrite __./x__ and __../x__ in one wildcard line to absolute tags."""
    def _sub(m):
        key = resolve_relative_key(m.group(1), base_key)
        return f"__{key}__" if key else m.group(0)
    return _REL_TAG_RE.sub(_sub, text)


def relativize_options(values, base_key):
    """Apply resolve_relative_tags to every string option of a wildcard key."""
    out = []
    for v in values:
        if isinstance(v, str) and '__.' in v:
            out.append(resolve_relative_tags(v, base_key))
        else:
            out.append(v)
    return out


def base_key_for_file(file_path, root=None):
    """Folder key ('' = root) of a wildcard file, relative to the root it
    lives in (the given root, else the roots of the last wildcard_load())."""
    roots = [root] if root else (list(_roots_cache) or get_wildcard_roots())
    fp = os.path.abspath(file_path)
    for r in roots:
        try:
            rel = os.path.relpath(fp, os.path.abspath(r))
        except ValueError:          # different drive on Windows
            continue
        if rel == '..' or rel.startswith('..' + os.sep) or rel.startswith('../'):
            continue
        d = os.path.dirname(rel)
        return '' if d in ('', '.') else wildcard_normalize(d)
    return ''


def normalize_tag_key(raw):
    """Tag text -> (key, folder_only). Handles case / backslashes / spaces,
    a relative tag typed straight into the prompt box (resolved against the
    root), a trailing .txt/.yaml and a trailing / (folder call)."""
    key = wildcard_normalize(raw)
    if key.startswith('.'):
        key = resolve_relative_key(key, '')
    folder_only = key.endswith('/')
    key = strip_key_extension(key.rstrip('/'))
    return key, folder_only


def chain_at(text, pos):
    """(key, line index) picks that are still open at position pos."""
    stack = []
    i = 0
    while True:
        s = text.find(_CHAIN_START, i, pos)
        e = text.find(_CHAIN_END, i, pos)
        if s < 0 and e < 0:
            break
        if e < 0 or (0 <= s < e):
            sep = text.find(_CHAIN_SEP, s)
            if sep < 0:
                break
            ck, _, idx = text[s + 1:sep].rpartition('#')
            idx = idx.split(_TRACE_SEP)[0]
            try:
                stack.append((ck, int(idx)))
            except ValueError:
                stack.append((ck, -1))
            i = sep + 1
        else:
            if stack:
                stack.pop()
            i = e + 1
    return stack


def strip_chain_markers(text):
    if _CHAIN_START not in text and _CHAIN_END not in text:
        return text
    return _CHAIN_LABEL_RE.sub('', text).replace(_CHAIN_END, '')


def read_wildcard(k, v, on_demand=False, base_key=''):
    """
    Read wildcard data with optional on-demand loading

    Args:
        k: wildcard key
        v: wildcard value (list, dict, str, or number)
        on_demand: if True, store LazyWildcardLoader instead of actual data
    """
    if isinstance(v, list):
        k = wildcard_normalize(k)
        wildcard_dict[k] = relativize_options(v, base_key)
    elif isinstance(v, dict):
        for k2, v2 in v.items():
            new_key = f"{k}/{k2}"
            new_key = wildcard_normalize(new_key)
            read_wildcard(new_key, v2, on_demand, base_key)
    elif isinstance(v, str):
        k = wildcard_normalize(k)
        wildcard_dict[k] = relativize_options([v], base_key)
    elif isinstance(v, (int, float)):
        k = wildcard_normalize(k)
        wildcard_dict[k] = [str(v)]

def read_wildcard_dict(wildcard_path, on_demand=False):
    """
    Read wildcard dictionary with optional on-demand loading

    Args:
        wildcard_path: path to wildcard directory
        on_demand: if True, use lazy loading to reduce memory usage

    Returns:
        wildcard_dict
    """
    global wildcard_dict
    for root, directories, files in os.walk(wildcard_path, followlinks=True):
        for file in files:
            if file.endswith('.txt'):
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, wildcard_path)
                key = wildcard_normalize(os.path.splitext(rel_path)[0])
                base_key = key.rpartition('/')[0]      # folder the file lives in

                if on_demand:
                    # Store lazy loader instead of actual data
                    wildcard_dict[key] = LazyWildcardLoader(file_path, 'txt', base_key)
                else:
                    # Load data immediately (original behavior)
                    try:
                        wildcard_dict[key] = load_txt_wildcard(file_path, base_key)
                    except Exception as e:
                        logging.warning(f"[umbrae wildcards] Failed to load {file_path}: {e}")
            elif file.endswith('.yaml') or file.endswith('.yml'):
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, wildcard_path)
                base_key = wildcard_normalize(os.path.splitext(rel_path)[0]).rpartition('/')[0]

                if on_demand:
                    # For YAML files in on-demand mode, we need to load and parse them
                    # since they may contain nested structures
                    loader = LazyWildcardLoader(file_path, 'yaml')
                    yaml_data = loader.get_data()
                    if isinstance(yaml_data, dict):
                        _before = set(wildcard_dict)
                        for k, v in yaml_data.items():
                            read_wildcard(k, v, on_demand, base_key)
                        _src = os.path.relpath(file_path, wildcard_path).replace(os.sep, '/')
                        for k in set(wildcard_dict) - _before:
                            key_sources[k] = _src
                else:
                    # Load data immediately (original behavior)
                    # One bad / empty YAML file must not stop the rest of the folder loading.
                    try:
                        try:
                            with open(file_path, 'r', encoding="ISO-8859-1") as f:
                                yaml_data = yaml.load(f, Loader=yaml.FullLoader)
                        except yaml.reader.ReaderError:
                            with open(file_path, 'r', encoding="UTF-8", errors="ignore") as f:
                                yaml_data = yaml.load(f, Loader=yaml.FullLoader)

                        if not isinstance(yaml_data, dict):
                            if yaml_data is not None:
                                logging.warning(f"[umbrae wildcards] Skipped YAML file {file_path}: top level is not a mapping")
                            continue
                        _before = set(wildcard_dict)
                        for k, v in yaml_data.items():
                            read_wildcard(k, v, on_demand, base_key)
                        _src = os.path.relpath(file_path, wildcard_path).replace(os.sep, '/')
                        for k in set(wildcard_dict) - _before:
                            key_sources[k] = _src
                    except Exception as e:
                        logging.warning(f"[umbrae wildcards] Failed to load YAML file {file_path}: {e}")

    return wildcard_dict


def process_comment_out(text):
    # A '#' line is removed on its own; the other lines keep their line breaks.
    lines = [line for line in text.split('\n') if not line.lstrip().startswith('#')]
    return '\n'.join(lines)


# A cycle survives process() calls, but deliberately resets on a ComfyUI restart.
_cycle_lock = threading.Lock()
_cycle_states = {}
_cycle_sources = set()


def _split_cycle_options(value):
    """Split only unescaped carets at this brace level."""
    parts = []
    start = 0
    depth = 0
    i = 0
    while i < len(value):
        if value[i] == '\\':
            i += 2
            continue
        if value[i] == '{':
            depth += 1
        elif value[i] == '}':
            depth -= 1
        elif value[i] == '^' and depth == 0:
            parts.append(value[start:i])
            start = i + 1
        i += 1
    parts.append(value[start:])
    return parts


# ── group prefixes (v0.8.2) ──────────────────────────────────────────────────
#   -::    written order. With '^' (or a lone __wildcard__ and no count) the
#          position persists across runs; with '|' it applies within the run
#          (useful with a count: {2$$-::a|b|c} -> "a b").
#   N+::   no-repeat history: never pick any of the last N items used (N
#          defaults to 1). Persistent across runs; works with '|' and '^'.
# A prefix sits right after '{' or right after a count header (N$$ / N$$sep$$
# / N$$$s1$s2$$). '\+::' and '\-::' are literal text.
_PREFIX_RE = re.compile(r'^\s*(?:(?P<n>\d*)(?P<plus>\+)::|(?P<minus>-)::)')
_PREFIX_ANY_RE = re.compile(r'(?<!\\)(?:\d*\+|(?<![\w])-)::')
_WEIGHT_RE = re.compile(r'^\s*[0-9.]+::')


def _parse_prefix(option_text):
    """-> (mode, n, stripped) where mode is None, 'minus' or 'plus'."""
    m = _PREFIX_RE.match(option_text)
    if not m:
        return None, 0, option_text
    if m.group('minus'):
        return 'minus', 0, option_text[m.end():]
    n = int(m.group('n')) if m.group('n') else 1
    return 'plus', max(1, n), option_text[m.end():]


def _strip_weight(option):
    return _WEIGHT_RE.sub('', str(option), count=1)


def _option_weight(option):
    parts = str(option).split('::', 1)
    if len(parts) == 2 and is_numeric_string(parts[0].strip()):
        return float(parts[0].strip())
    return 1.0


def _scope_matches(scope, node_id):
    """scope = (class_name, node_id_str). node_id None = every scope.
    A subgraph execution id 'a:b' matches a plain node id 'b'."""
    if node_id is None:
        return True
    try:
        sid = str(scope[1])
    except Exception:
        return False
    nid = str(node_id)
    return sid == nid or sid.endswith(':' + nid)


def reset_cycles(node_id=None):
    """Clear every persistent selection state ('^' bags, '-::' cursors, '+::'
    histories) for one node (or all nodes when node_id is None).
    Returns the number of states removed."""
    with _cycle_lock:
        keys = [k for k in _cycle_states if _scope_matches(k[0], node_id)]
        for k in keys:
            del _cycle_states[k]
        for src in [s for s in _cycle_sources if _scope_matches(s[0], node_id)]:
            _cycle_sources.discard(src)
    return len(keys)


def cycle_is_changed(text, cycle_scope=None):
    """Only stateful prompts need to bypass the node's fixed-input cache."""
    if not isinstance(text, str):
        return False
    source = process_comment_out(text)
    with _cycle_lock:
        # The recorded source also covers cycles discovered inside wildcard files.
        return ('^' in source or _PREFIX_ANY_RE.search(source) is not None
                or (cycle_scope, source) in _cycle_sources)


# ── switches (v0.8.3) ────────────────────────────────────────────────────────
#   {&name=value}        define a switch (value may be any syntax resolving to a
#                        number, e.g. {1|2} or {-::1^2}); removed from the output
#   {&name:a|b|c}        pick option number <value> (1-based)
#   The node's `switches` box (name=value pairs and/or {&name=value}) overrides
#   same-named definitions in the text. Out of range -> last option + warning.
#   Undefined name / non-number value -> one random value per name per run
#   (weighted by the first group's N:: weights), shared by all its groups +
#   warning. While deferred (box value pending) groups are left for execution.
_SW_NAME = r'[A-Za-z_][A-Za-z0-9_.-]*'
_SW_DEF_RE = re.compile(r'(?<!\\)\{&(' + _SW_NAME + r')\s*=\s*')
_SW_USE_RE = re.compile(r'(?<!\\)\{&(' + _SW_NAME + r')\s*:')
_SW_PAIR_RE = re.compile(r'^\s*(' + _SW_NAME + r')\s*=\s*(.*?)\s*$', re.S)
_SW_BODY_RE = re.compile(r'^&!?' + _SW_NAME + r'\s*[:=]')


def _balanced_close(s, i):
    """i = index just after an opening '{'. Returns the index of the matching
    '}' (escapes skipped), or -1 if unbalanced."""
    depth = 1
    while i < len(s):
        c = s[i]
        if c == '\\':
            i += 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _split_top(value, sep='|'):
    """Split on `sep` at brace depth 0, skipping escapes."""
    parts, start, depth, i = [], 0, 0, 0
    while i < len(value):
        c = value[i]
        if c == '\\':
            i += 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        elif c == sep and depth == 0:
            parts.append(value[start:i])
            start = i + 1
        i += 1
    parts.append(value[start:])
    return parts


_SW_LOCK_RE = re.compile(r'(?<!\\)\{&!(' + _SW_NAME + r')\s*=\s*')
_VAR_LOCK_RE = re.compile(r'(?<!\\)\{@!(' + _SW_NAME + r')\s*=\s*')
_RP_START_RE = re.compile(r'(?<!\\)\{(!!!!|!!!|!!|!)(?=[^!=])')
_RP_BODY_RE = re.compile(r'^!{1,4}[^={}]+=')


def _extract_defs(text, start_re):
    """Remove every {<prefix>name=value} matched by start_re ->
    (text, [(name, raw_value), ...])."""
    defs, pieces, pos = [], [], 0
    while True:
        m = start_re.search(text, pos)
        if m is None:
            pieces.append(text[pos:])
            break
        end = _balanced_close(text, m.end())
        if end < 0:
            pieces.append(text[pos:])
            break
        defs.append((m.group(1), text[m.end():end].strip()))
        pieces.append(text[pos:m.start()])
        pos = end + 1
    return ''.join(pieces), defs


def _find_top_equals(body):
    depth, i = 0, 0
    while i < len(body):
        c = body[i]
        if c == '\\':
            i += 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        elif c == '=' and depth == 0:
            return i
        i += 1
    return -1


def extract_replacements(text):
    """Remove every {!find=replace} / {!!find=...} / {!!!find=...} / {!!!!find=...}
    -> (text, [(mode, find, raw)]); mode is '!' (any case, case follows), '!!' (exact
    case, literal insert; {!!!!} is an alias), '!!!' (any case, literal insert)."""
    out, pieces, pos = [], [], 0
    while True:
        m = _RP_START_RE.search(text, pos)
        if m is None:
            pieces.append(text[pos:])
            break
        end = _balanced_close(text, m.end())
        if end < 0:
            pieces.append(text[pos:])
            break
        body = text[m.end():end]
        eq = _find_top_equals(body)
        find = body[:eq].strip() if eq > 0 else ''
        if eq <= 0 or not find or '{' in find:
            pieces.append(text[pos:end + 1])        # not a replacement: leave it
            pos = end + 1
            continue
        mode = '!!' if m.group(1) == '!!!!' else m.group(1)
        out.append((mode, find, body[eq + 1:].strip()))
        pieces.append(text[pos:m.start()])
        pos = end + 1
    return ''.join(pieces), out


def case_like(matched, repl):
    """Case-follow for {!find=...}: all lower -> lower, ALL CAPS -> UPPER,
    multi-word Title Case -> Title Case, Capitalised -> first letter
    capitalised, anything else -> as written."""
    letters = [c for c in matched if c.isalpha()]
    if not letters or not repl:
        return repl
    if all(c.islower() for c in letters):
        return repl.lower()
    if len(letters) > 1 and all(c.isupper() for c in letters):
        return repl.upper()
    words = [w for w in matched.split() if w[:1].isalpha()]
    if len(words) >= 2 and all(w[0].isupper() and w[1:] == w[1:].lower() for w in words):
        return ' '.join(w[:1].upper() + w[1:] for w in repl.split(' '))
    if letters[0].isupper() and all(c.islower() for c in letters[1:]):
        for i, c in enumerate(repl):
            if c.isalpha():
                return repl[:i] + c.upper() + repl[i + 1:]
        return repl
    return repl


def apply_text_replacements(text, rules):
    """rules: [(mode, find, value)], mode '!' (any case, replacement follows the
    matched case), '!!' (exact case, literal) or '!!!' (any case, literal).
    Whole words / phrases only, ONE pass (swaps work, nothing is replaced
    twice). Exact (!!) rules win over the any-case rules on the same text,
    then longer finds first, then !!! before !."""
    if not rules or not text:
        return text
    rank = {'!!': 0, '!!!': 1, '!': 2}
    ordered = sorted(rules, key=lambda r: (r[0] != '!!', -len(r[1]), rank[r[0]]))
    parts, table = [], {}
    for i, (mode, find, value) in enumerate(ordered):
        core = r'(?<!\w)' + re.escape(find) + r'(?!\w)'
        parts.append(f'(?P<r{i}>{core})' if mode == '!!' else f'(?P<r{i}>(?i:{core}))')
        table[f'r{i}'] = (mode, value)
    pattern = re.compile('|'.join(parts))

    def repl(m):
        mode, value = table[m.lastgroup]
        return case_like(m.group(0), value) if mode == '!' else value

    def run(chunk):
        # \n line-break markers count as word boundaries (protect \\n literals)
        chunk = chunk.replace('\\\\n', '\x01n').replace('\\n', '\x00')
        chunk = pattern.sub(repl, chunk)
        return chunk.replace('\x00', '\\n').replace('\x01n', '\\\\n')

    if _PROT_START not in text:
        return run(text)
    # {-=...=-} spans are copied through untouched (markers kept, stripped later)
    out, buf, depth = [], [], 0
    for ch in text:
        if ch == _PROT_START:
            if depth == 0:
                out.append(run(''.join(buf)))
                buf = []
            depth += 1
            out.append(ch)
        elif ch == _PROT_END and depth:
            depth -= 1
            out.append(ch)
        elif depth:
            out.append(ch)
        else:
            buf.append(ch)
    out.append(run(''.join(buf)))
    return ''.join(out)


def extract_switch_defs(text):
    """Remove every {&name=value} from text -> (text, [(name, raw_value), ...])."""
    defs, pieces, pos = [], [], 0
    while True:
        m = _SW_DEF_RE.search(text, pos)
        if m is None:
            pieces.append(text[pos:])
            break
        end = _balanced_close(text, m.end())
        if end < 0:
            pieces.append(text[pos:])
            break
        defs.append((m.group(1), text[m.end():end].strip()))
        pieces.append(text[pos:m.start()])
        pos = end + 1
    return ''.join(pieces), defs


def parse_switch_box(box):
    """The node's `switches` box -> {name: raw_value}. Accepts {&name=value}
    definitions and/or bare name=value pairs separated by commas / new lines,
    in any mix. Later entries win. Anything else is skipped (logged)."""
    if not isinstance(box, str) or not box.strip():
        return {}
    rest, locked = _extract_defs(box, _SW_LOCK_RE)
    rest, defs = extract_switch_defs(rest)
    defs = locked + defs
    out = {}
    for name, raw in defs:
        out[name] = raw
    for chunk in _split_top(rest.replace('\n', ','), ','):
        if not chunk.strip():
            continue
        m = _SW_PAIR_RE.match(chunk)
        if m:
            out[m.group(1)] = m.group(2)
        else:
            logging.info(f"[umbrae wildcards] switches box: skipped '{chunk.strip()}' (not name=value)")
    return out


def finalize_output(text):
    """Node-output step (applied once, by the node): '\\n' -> line break,
    '\\\\n' -> literal '\\n', '\\&' -> '&'. Kept out of process() so populate +
    execute (which both process the text) never convert twice."""
    if not isinstance(text, str):
        return text
    return re.sub(r'\\(\\n|n|&|!)', lambda m: {'\\n': '\\n', 'n': '\n', '&': '&', '!': '!'}[m.group(1)], text)


# ---------------------------------------------------------------------------
# Aspect ratio from the workflow + bracket tokens (v0.8.7)
#
# The node reads the image size from what is connected to it (latent, or
# width / height ints) and adapts the TEXT to it. Nothing is read from the
# prompt to size the image.
#
#   [[aspect]]  request: inserts one line from __aspect/[orientation]__
#               (aspect/horizontal, aspect/vertical or aspect/square; defaults
#               ship in wildcard_examples/) on its own line, for the connected
#               size. Unknown size at queue time -> left as-is, resolved when
#               the node runs.
#   [name]      tokens, filled last: [orientation] [ratio] [width] [height].
#               Unknown names are left as typed.
#   [W:H]       optional override typed in the text, used only when nothing is
#               connected; removed from the node output. [[W:H]] = request +
#               override in one.
# ---------------------------------------------------------------------------
ASPECT_WILDCARD_DEFAULT = "__aspect/[orientation]__"
_ASPECT_REQUEST_RE = re.compile(r'\[\[\s*(?:(\d+)\s*:\s*(\d+)|aspect)\s*\]\]', re.IGNORECASE)
_ASPECT_MARKER_RE = re.compile(r'(?<!\[)\[\s*(\d+)\s*:\s*(\d+)\s*\](?!\])')
_TOKEN_RE = re.compile(r'\[([A-Za-z_][A-Za-z0-9_]*)\]')
_ASPECT_TOKEN_RE = re.compile(r'\[(orientation|ratio|width|height)\]', re.IGNORECASE)
_TAG_RE = re.compile(r'__([\w.\-+/*\\]+?)__')
# Common ratios the pixel size snaps to (within _RATIO_TOLERANCE); else reduced fraction.
_COMMON_RATIOS = ((1, 1), (5, 4), (4, 3), (3, 2), (16, 10), (16, 9), (2, 1), (21, 9),
                  (4, 5), (3, 4), (2, 3), (10, 16), (9, 16), (1, 2), (9, 21))
_RATIO_TOLERANCE = 0.03


def aspect_orientation(w, h):
    """'horizontal', 'vertical' or 'square' (exact equality) for a W:H ratio."""
    if w > h:
        return 'horizontal'
    if w < h:
        return 'vertical'
    return 'square'


def ratio_from_size(width, height):
    """Nearest common W:H for a pixel size (e.g. 1328x752 -> 16:9), else the reduced fraction."""
    try:
        w, h = int(width), int(height)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    target = w / h
    best = min(_COMMON_RATIOS, key=lambda r: abs(r[0] / r[1] - target))
    if abs(best[0] / best[1] - target) / target <= _RATIO_TOLERANCE:
        return best
    g = math.gcd(w, h)
    return (w // g, h // g)


def find_aspect_marker(text):
    """Last [W:H] override in the text -> (w, h), or None. Warns when markers disagree."""
    if not isinstance(text, str) or '[' not in text:
        return None
    found = [(int(a), int(b)) for a, b in _ASPECT_MARKER_RE.findall(text) if int(a) > 0 and int(b) > 0]
    if not found:
        return None
    if len(set(found)) > 1:
        logging.warning(f"[umbrae wildcards] several aspect markers {sorted(set(found))} in one prompt - "
                        f"the last one ({found[-1][0]}:{found[-1][1]}) wins.")
    return found[-1]


def strip_aspect_markers(text):
    """Remove every [W:H] override (node output step) and tidy the whitespace it leaves."""
    if not isinstance(text, str) or not _ASPECT_MARKER_RE.search(text):
        return text
    out = _ASPECT_MARKER_RE.sub('', text)
    out = re.sub(r'[ \t]+([,.;:!?])', r'\1', out)      # "shot , a" -> "shot, a"
    out = re.sub(r'[ \t]{2,}', ' ', out)
    out = re.sub(r'[ \t]+\n', '\n', out)
    out = re.sub(r'\n[ \t]+', '\n', out)
    out = re.sub(r'\n{3,}', '\n\n', out)
    return out.strip()


def fill_tokens(text, values):
    """Replace [name] tokens (case-insensitive) from values; unknown names stay as typed."""
    if not isinstance(text, str) or '[' not in text or not values:
        return text
    lookup = {str(k).lower(): str(v) for k, v in values.items()}
    return _TOKEN_RE.sub(lambda m: lookup.get(m.group(1).lower(), m.group(0)), text)


def aspect_config(width=None, height=None):
    """The connected image size, as passed to process(aspect=...). {} when unknown."""
    try:
        w, h = int(width), int(height)
    except (TypeError, ValueError):
        return {}
    if w <= 0 or h <= 0:
        return {}
    return {'width': w, 'height': h}


def resolve_aspect(text, aspect=None):
    """(ratio_w, ratio_h, width_px, height_px) - connected size first, else a [W:H]
    override in the text (pixel size then None); None when neither exists."""
    cfg = aspect or {}
    if cfg.get('width') and cfg.get('height'):
        r = ratio_from_size(cfg['width'], cfg['height'])
        if r:
            return r[0], r[1], cfg['width'], cfg['height']
    m = find_aspect_marker(text)
    if m:
        return m[0], m[1], None, None
    return None


def aspect_tokens(text, aspect=None):
    """Token values for the resolved aspect, or None when nothing is known yet."""
    r = resolve_aspect(text, aspect)
    if r is None:
        return None
    w, h, pw, ph = r
    tokens = {'orientation': aspect_orientation(w, h), 'ratio': f'{w}:{h}'}
    if pw and ph:
        tokens['width'] = pw
        tokens['height'] = ph
    return tokens


def apply_aspect_tokens(text, aspect=None, final=False):
    """Fill the aspect tokens anywhere in the text. Unknown size: untouched until the
    node runs (final=True), then 1:1 with a warning."""
    if not isinstance(text, str) or not _TOKEN_RE.search(text):
        return text
    tokens = aspect_tokens(text, aspect)
    if tokens is None:
        if not final or not _ASPECT_TOKEN_RE.search(text):
            return text
        logging.warning("[umbrae wildcards] aspect tokens used but no latent / width / height is connected "
                        "and the text has no [W:H] - using 1:1.")
        tokens = {'orientation': 'square', 'ratio': '1:1'}
    return fill_tokens(text, tokens)


def process(text, seed=None, cycle_scope=None, switches=None, defer_switches=False,
            aspect=None, aspect_final=False, value_hook=None, pick_hook=None, trace=None):
    """value_hook(key, options) -> options to use for that key (v0.8.8):
    None = treat as not found, False = leave the tag exactly as written.

    pick_hook(chain_key, occurrence, options, picked) (v0.9.0, wildcard expander):
    called for every __tag__ draw AFTER the random pick (so forcing one draw never
    shifts the others). Return None to keep the pick, an int to force that line,
    a str to insert that text instead ('' = skip the tag). `occurrence` counts
    draws of the same chain_key in this call (0-based); folder calls use
    'folder/' as chain_key, patterns use the pattern.

    trace (v0.9.0): pass a dict and it comes back with trace['draws'] = one record
    per __tag__ draw ({seq, key, tag, n, idx, count, line, forced}) and
    trace['marked'] = the text with the recursion-chain markers still in place
    (START key#idx\uE015seq SEP text END), i.e. the full tree of what each tag
    became, before switches / text replacements / aspect tokens ran."""
    text = process_comment_out(text)
    aspect_cfg = aspect or {}

    if seed is not None:
        random.seed(seed)
    random_gen = np.random.default_rng(seed)

    local_wildcard_dict = get_wildcard_dict()
    wildcard_variables = {}
    wildcard_variable_pools = {}
    wildcard_definitions = {}
    resolving_variables = set()
    cycle_source = text
    cycle_occurrences = {}

    option_occurrences = {}

    # switches: box values override same-named definitions found in the text
    switch_box = dict(switches) if isinstance(switches, dict) else parse_switch_box(switches)
    switch_text_defs = {}
    switch_locked = {}            # {&!name=...}  (v0.8.6)
    switch_resolved = {}
    switch_warned = set()
    locked_vars = {}              # {@!name=...}  (v0.8.6)
    text_rules = {}               # {!find=..} / {!!find=..} / {!!!find=..}  (v0.8.6, !!! v0.9.5)
    locked_modes = {}             # @!name=r=...  -> 'r' (v0.8.9)
    locked_built = {}             # @!name with protected options -> rewritten group
    pin_lists = {}                # {&=N:a|b}   exact option list -> choice
    pin_vars = {}                 # {&=N:@name}
    pin_tags = {}                 # {&=N:__key__}
    pick_counts = {}              # chain_key -> draws so far (v0.9.0 pick_hook / trace)
    trace_draws = trace.setdefault('draws', []) if isinstance(trace, dict) else None

    def collect_locked_and_rules(string):
        """Pull {@!name=...} overrides and {!find=...} replacement rules out of
        the text (prompt or freshly expanded wildcard file lines)."""
        string, locks = _extract_defs(string, _VAR_LOCK_RE)
        string, pins = extract_pins(string)
        for choice, target in pins:
            t = target.strip()
            if t.startswith('@') and re.fullmatch(r'@' + _SW_NAME, t):
                pin_vars[t[1:]] = choice
            elif re.fullmatch(r'__[\w.\-+/*\\]+?__', t):
                pin_tags[normalize_tag_key(t[2:-2])[0]] = choice
            else:
                pin_lists[pin_list_key(t.split('|'))] = choice
        for name, raw in locks:
            rm = re.match(r'^r\s*=(?!=)\s*(.*)$', raw, re.S)
            if rm:
                raw = rm.group(1).strip()
                locked_modes[name] = 'r'
            else:
                locked_modes.pop(name, None)
            if name in locked_vars and locked_vars[name] != raw:
                logging.warning(f"[umbrae wildcards] '@!{name}' defined more than once - the later one wins.")
            locked_vars[name] = raw
        string, rules = extract_replacements(string)
        for mode, find, raw in rules:
            key = (mode, find if mode == '!!' else find.lower())
            if key in text_rules and text_rules[key][2] != raw:
                logging.warning(f"[umbrae wildcards] replacement '{mode}{find}' defined "
                                f"more than once - the later one wins.")
            text_rules[key] = (mode, find, raw)
        shielded = protect_spans(string)
        changed = shielded != string
        return shielded, bool(locks or rules or changed or pins)

    def _resolve_fragment(value):
        """Resolve ordinary syntax inside a switch value ({1|2}, {-::1^2}, ...)."""
        for _ in range(50):
            previous = value
            value = replace_cycles(value)
            value, again = replace_options(value)
            while again:
                value, again = replace_options(value)
            value, _found = replace_wildcard(value)
            if value == previous:
                break
        return value

    def switch_value(name):
        if name in switch_resolved:
            return switch_resolved[name]
        if name in switch_box:
            raw = switch_box[name]
        elif name in switch_locked:
            raw = switch_locked[name]
        else:
            raw = switch_text_defs.get(name)
        if raw is None:
            return None
        switch_resolved[name] = None          # recursion guard
        resolved = _resolve_fragment(str(raw)).strip()
        try:
            val = int(float(resolved))
        except ValueError:
            logging.warning(f"[umbrae wildcards] switch '&{name}' value '{resolved}' is not a number - ignored.")
            val = None
        switch_resolved[name] = val
        return val

    def apply_switches(string):
        """Collect {&name=...} definitions, then resolve every {&name:...} group
        whose value is known. Unknown names are left as-is."""
        string, locks = _extract_defs(string, _SW_LOCK_RE)
        for name, raw in locks:
            if name in switch_locked and switch_locked[name] != raw:
                logging.warning(f"[umbrae wildcards] '&!{name}' defined more than once - the later one wins.")
            switch_locked[name] = raw
            if name not in switch_box:
                switch_resolved.pop(name, None)
        string, defs = extract_switch_defs(string)
        for name, raw in defs:
            switch_text_defs[name] = raw
            if name not in switch_box and name not in switch_locked:
                switch_resolved.pop(name, None)
        changed = bool(defs or locks)
        pieces, pos = [], 0
        while True:
            m = _SW_USE_RE.search(string, pos)
            if m is None:
                pieces.append(string[pos:])
                break
            end = _balanced_close(string, m.end())
            if end < 0:
                pieces.append(string[pos:])
                break
            name = m.group(1)
            options = _split_top(string[m.end():end])
            # Deferred: the box value is only known at execution and may override
            # ANY name, so every switch group waits (definitions are carried).
            val = None if defer_switches else switch_value(name)
            if val is None and not defer_switches:
                # v0.8.4 fallback: undefined (or non-number) switch -> pick ONE
                # random value for this name (weighted by this group's N::
                # weights, seeded like every other pick) and reuse it for every
                # later group of the same name, so they stay consistent.
                w = np.asarray([max(0.0, _option_weight(o)) for o in options], dtype=float)
                p = w / w.sum() if w.sum() > 0 else None
                val = int(random_gen.choice(len(options), p=p)) + 1
                switch_resolved[name] = val
                if name not in switch_warned:
                    switch_warned.add(name)
                    logging.warning(f"[umbrae wildcards] switch '&{name}' is not defined - picked {val} "
                                    f"at random (used for every '&{name}' group in this prompt).")
            if val is None:
                # deferred: the switches box is only known at execution
                pieces.append(string[pos:end + 1])
            else:
                if 1 <= val <= len(options):
                    idx = val - 1
                else:
                    idx = len(options) - 1
                    logging.warning(f"[umbrae wildcards] switch '&{name}'={val} is out of range "
                                    f"(1-{len(options)}) - using the last option.")
                pieces.append(string[pos:m.start()])
                pieces.append(_strip_weight(options[idx]))
                changed = True
            pos = end + 1
        return ''.join(pieces), changed

    def _state_key(kind, body):
        # Identical groups in different positions have independent state.
        counter = cycle_occurrences if kind == 'cycle' else option_occurrences
        occurrence = counter.get(body, 0)
        counter[body] = occurrence + 1
        if kind == 'cycle':
            return (cycle_scope, cycle_source, body, occurrence)  # unchanged key shape
        return (cycle_scope, cycle_source, kind, body, occurrence)

    def _draw_ordered(key, n):
        """Persistent written-order cursor -> index, wraps after the last item."""
        with _cycle_lock:
            state = _cycle_states.get(key)
            if state is None or state.get('kind') != 'ordered' or state.get('n') != n:
                state = {'kind': 'ordered', 'n': n, 'cursor': 0}
                _cycle_states[key] = state
            idx = state['cursor'] % n
            state['cursor'] = (idx + 1) % n
            _cycle_sources.add((cycle_scope, cycle_source))
        return idx

    def _history_window(history, texts, need, hist_n):
        """Largest recent-history window (<= hist_n) that still leaves `need`
        eligible options. Returns the set of excluded texts."""
        k = min(hist_n, len(history))
        while k > 0:
            excluded = set(history[-k:])
            if sum(1 for t in texts if t not in excluded) >= need:
                return excluded
            k -= 1
        return set()

    def _remember(state, picked_texts, hist_n):
        state['history'].extend(picked_texts)
        if len(state['history']) > hist_n:
            del state['history'][:-hist_n]

    def draw_cycle(body, options, mode=None, hist_n=0):
        if mode == 'minus':
            key = _state_key('cycle', body)
            return _strip_weight(options[_draw_ordered(key, len(options))])
        if mode == 'plus':
            # Shuffled bag (same order rules as plain '^'); at a bag boundary the
            # next pick skips anything in the last `hist_n` items used.
            key = _state_key('cycle', body)
            texts = [_strip_weight(o) for o in options]
            with _cycle_lock:
                state = _cycle_states.get(key)
                if state is None or state.get('kind') != 'bag_hist' or len(state['order']) != len(options):
                    state = {'kind': 'bag_hist', 'seed': seed, 'order': None, 'remaining': [], 'history': []}
                    _cycle_states[key] = state
                if not state['remaining']:
                    if state['order'] is None or seed is None or seed != state['seed']:
                        order = list(range(len(options)))
                        np.random.default_rng(seed).shuffle(order)
                        state['order'] = order
                        state['seed'] = seed
                    state['remaining'] = list(state['order'])
                excluded = _history_window(state['history'], [texts[i] for i in state['remaining']], 1, hist_n)
                pick = next((i for i in state['remaining'] if texts[i] not in excluded), state['remaining'][0])
                state['remaining'].remove(pick)
                _remember(state, [texts[pick]], hist_n)
                _cycle_sources.add((cycle_scope, cycle_source))
            return texts[pick]

        return _draw_plain_cycle(body, options)

    def select_prefixed(body, options, mode, hist_n, count, lone_file):
        """Selection for a '|' group carrying a -:: or N+:: prefix.
        Returns the chosen option texts (weights stripped)."""
        texts = [_strip_weight(o) for o in options]
        if not texts:
            return []
        count = max(0, min(int(count), len(texts)))
        if mode == 'minus':
            if lone_file:
                # persistent written order through a wildcard file
                return [texts[_draw_ordered(_state_key('ordered_opt', body), len(texts))]]
            return texts[:count]                      # written order, this run only
        # 'plus': weighted random excluding the last hist_n items used
        key = _state_key('hist', body)
        with _cycle_lock:
            state = _cycle_states.get(key)
            if state is None or state.get('kind') != 'hist':
                state = {'kind': 'hist', 'history': []}
                _cycle_states[key] = state
            excluded = _history_window(state['history'], texts, count, hist_n)
            cand = [i for i, t in enumerate(texts) if t not in excluded]
            if count >= len(cand):
                order = list(cand)
                random_gen.shuffle(order)
                picks = order
            else:
                w = np.asarray([max(0.0, _option_weight(options[i])) for i in cand], dtype=float)
                p = w / w.sum() if np.count_nonzero(w) >= count else None
                picks = list(random_gen.choice(cand, p=p, size=count, replace=False))
            chosen = [texts[int(i)] for i in picks]
            _remember(state, chosen, hist_n)
            _cycle_sources.add((cycle_scope, cycle_source))
        return chosen

    def _draw_plain_cycle(body, options):
        # plain '^' - original behaviour, unchanged
        key = _state_key('cycle', body)
        with _cycle_lock:
            state = _cycle_states.get(key)
            if state is None or state['cursor'] == len(options):
                if state is None or seed is None or seed != state['seed']:
                    order = list(range(len(options)))
                    np.random.default_rng(seed).shuffle(order)
                    state = {'seed': seed, 'order': order, 'cursor': 0}
                    _cycle_states[key] = state
                else:
                    state['cursor'] = 0
            option = options[state['order'][state['cursor']]]
            state['cursor'] += 1
            _cycle_sources.add((cycle_scope, cycle_source))
        return re.sub(r'^\s*[0-9.]+::', '', option, count=1)

    def replace_cycles(string, pool=None):
        # Select the outer cycle before expanding its nested choices. This keeps
        # the bag identity stable even when an option contains a random wildcard.
        pieces = []
        position = 0
        i = 0
        while i < len(string):
            if string[i] == '\\':
                i += 2
                continue
            if string[i] != '{':
                i += 1
                continue
            start = i
            depth = 1
            i += 1
            body_start = i
            while i < len(string) and depth:
                if string[i] == '\\':
                    i += 2
                    continue
                if string[i] == '{':
                    depth += 1
                elif string[i] == '}':
                    depth -= 1
                i += 1
            if depth:
                break
            body = string[body_start:i-1]
            # Definitions must reach the variable resolver intact, including
            # their original pool for #name exclusions.
            if re.match(r'^@!?[A-Za-z_][A-Za-z0-9_.-]*(?:\s*=|$)', body) or _RP_BODY_RE.match(body):
                replacement = string[start:i]
            elif _SW_BODY_RE.match(body):
                # switch group: never a cycle itself; its options are only
                # resolved after apply_switches has chosen one
                replacement = string[start:i]
            else:
                options = _split_cycle_options(body)
                if len(options) > 1:
                    mode, hist_n, first = _parse_prefix(options[0])
                    if mode is not None:
                        options = [first] + options[1:]
                    if pool is not None and not pool:
                        pool.extend(options)
                    replacement = replace_cycles(draw_cycle(body, options, mode, hist_n))
                else:
                    replacement = '{' + replace_cycles(body, pool) + '}'
            pieces.append(string[position:start])
            pieces.append(replacement)
            position = i
        pieces.append(string[position:])
        return ''.join(pieces)

    def replace_options(string, pool=None):
        replacements_found = False

        def replace_option(match):
            nonlocal replacements_found
            # Named references and assignments belong to the variable resolver.
            if re.match(r'^@!?[A-Za-z_][A-Za-z0-9_.-]*(?:\s*=|$)', match.group(1)) or _RP_BODY_RE.match(match.group(1)):
                return match.group(0)
            # Switch groups belong to apply_switches (left as-is when undefined).
            if _SW_BODY_RE.match(match.group(1)):
                return match.group(0)
            # v0.8.9: protected options (-=..=-) are picked like any other but
            # keep their shield (and are exempt from pins)
            body = match.group(1)
            prot_texts = set()
            if _PROT_START in body or _PROT_END in body:
                items = split_protected_options(body)
                body = '|'.join(t for t, _p in items)
                prot_texts = {t for t, p in items if p}
            options = body.split('|')

            multi_select_pattern = options[0].split('$$')
            select_range = None
            select_sep = ' '
            select_last_sep = None  # when set, used as separator before the final item (oxford-style joins)

            # PATTERN: count$$$ sep1 $ sep2 $$ options
            # e.g. {5-10$$$, $ and $$__some/wildcard__}  ->  "x, x, x, x and x"
            # sep1 (between "$$$" and the single "$") joins all items except the last pair,
            # sep2 (between "$" and "$$") joins the final two items.
            if '$$$' in options[0]:
                head, rest = options[0].split('$$$', 1)
                if '$$' in rest:
                    sep_part, opt_part = rest.split('$$', 1)
                    if '$' in sep_part:
                        sep1, sep2 = sep_part.split('$', 1)
                        select_last_sep = sep2
                        # Rebuild options[0] into the plain "count$$options" form so the
                        # existing parsing below handles the range and wildcard expansion.
                        options[0] = head + '$$' + opt_part
                        multi_select_pattern = [head, opt_part]
                        select_sep = sep1

            # v0.8.2 group prefix (-:: / N+::): sits on the first option, i.e.
            # after any count header. Strip it before range parsing / expansion.
            group_body = body
            prefix_mode, prefix_n, stripped = _parse_prefix(multi_select_pattern[-1])
            if prefix_mode is not None:
                multi_select_pattern[-1] = stripped
                options[0] = '$$'.join(multi_select_pattern) if len(multi_select_pattern) > 1 else stripped
            range_pattern = r'(\d+)(-(\d+))?'
            range_pattern2 = r'-(\d+)'
            wildcard_pattern = r"__([\w.\-+/*\\]+?)__"

            if len(multi_select_pattern) > 1:
                r = re.match(range_pattern, options[0])

                if r is None:
                    r = re.match(range_pattern2, options[0])
                    if r is None:
                        # '$$' without a count ({foo$$bar}): malformed, leave the group as written
                        return match.group(0)
                    a = '1'
                    b = r.group(1).strip()
                else:
                    a = r.group(1).strip()
                    b = r.group(3)
                    if b is not None:
                        b = b.strip()
                    else:
                        b = a

                if r is not None:
                    if b is not None and is_numeric_string(a) and is_numeric_string(b):
                        # PATTERN: num1-num2
                        select_range = int(a), int(b)
                    elif is_numeric_string(a):
                        # PATTERN: num
                        x = int(a)
                        select_range = (x, x)

                    # Expand wildcard path or return the string after $$
                    def expand_wildcard_or_return_string(options, pattern, wildcard_pattern):
                        matches = re.findall(wildcard_pattern, pattern)
                        if len(options) == 1 and matches:
                            # $$<single wildcard>
                            return get_wildcard_options(pattern)
                        else:
                            # $$opt1|opt2|...
                            options[0] = pattern
                            return options

                    if select_range is not None and len(multi_select_pattern) == 2:
                        # PATTERN: count$$
                        options = expand_wildcard_or_return_string(options, multi_select_pattern[1], wildcard_pattern )
                    elif select_range is not None and len(multi_select_pattern) == 3:
                        # PATTERN: count$$ sep $$
                        select_sep = multi_select_pattern[1]
                        options = expand_wildcard_or_return_string(options, multi_select_pattern[2], wildcard_pattern )

            # C2: a prefixed lone __wildcard__ (no count) uses the file's lines
            # as the option list ({-::__emotions__}, {3+::__emotions__}).
            lone_file = False
            if (prefix_mode is not None and select_range is None and len(options) == 1
                    and re.fullmatch(r'\s*__([\w.\-+/*\\]+?)__\s*', str(options[0]))):
                expanded = get_wildcard_options(str(options[0]).strip())
                if expanded:
                    options = list(expanded)
                    lone_file = True

            if pool is not None and not pool:
                pool.extend(options)

            adjusted_probabilities = []

            total_prob = 0

            for option in options:
                parts = option.split('::', 1) if isinstance(option, str) else f"{option}".split('::', 1)

                if len(parts) == 2 and is_numeric_string(parts[0].strip()):
                    config_value = float(parts[0].strip())
                else:
                    config_value = 1  # Default value if no configuration is provided

                adjusted_probabilities.append(config_value)
                total_prob += config_value

            normalized_probabilities = [prob / total_prob for prob in adjusted_probabilities]

            if select_range is None:
                select_count = 1
            else:
                def calculate_max(_options_length, _max_select_range):
                    return min(_max_select_range + 1, _options_length + 1) if _max_select_range > 0 else _options_length + 1

                def calculate_select_count(_max_value, _min_select_range, random_gen):
                    if max(_max_value, _min_select_range) <= 0:
                        return 0
                    # fix: low >= high
                    elif _max_value == _min_select_range:
                        return _max_value
                    else:
                        # fix: low >= high
                        _low_value = min(_min_select_range, _max_value)
                        _high_value = max(_min_select_range, _max_value)
                        return random_gen.integers(low=_low_value, high=_high_value, size=1)
                select_count = calculate_select_count(calculate_max(len(options), select_range[1]), select_range[0], random_gen)

            forced = None
            if (pin_lists and select_range is None and prefix_mode is None and len(options) > 1
                    and not prot_texts and not in_protected_span(match.string, match.start())):
                choice = pin_lists.get(pin_list_key(options))
                if choice is not None:
                    forced = pin_index(options, choice)
                    if forced is None:
                        logging.warning(f"[umbrae wildcards] pin '{choice}' on {{{'|'.join(map(str, options))}}}: "
                                        f"no such option - ignored.")
            if forced is not None:
                selected_items = [options[forced]]
            elif prefix_mode is not None:
                selected_items = select_prefixed(group_body, options, prefix_mode, prefix_n,
                                                 int(np.asarray(select_count).reshape(-1)[0]),
                                                 lone_file)
            elif select_count > len(options) or total_prob <= 1:
                random_gen.shuffle(options)
                selected_items = options
            else:
                selected_items = random_gen.choice(options, p=normalized_probabilities, size=select_count, replace=False)

            # x may be numpy.int32, convert to string
            selected_items2 = [re.sub(r'^\s*[0-9.]+::', '', str(x), count=1) for x in selected_items]
            if prot_texts:
                selected_items2 = [wrap_protected(re.sub(r'^\s*[0-9.]+::', '', str(x), count=1))
                                   if str(x) in prot_texts else y
                                   for x, y in zip(selected_items, selected_items2)]
            if select_last_sep is not None and len(selected_items2) > 1:
                replacement = select_sep.join(selected_items2[:-1]) + select_last_sep + selected_items2[-1]
            else:
                replacement = select_sep.join(selected_items2)
            if '::' in replacement:
                pass

            replacements_found = True
            return replacement

        pattern = r'(?<!\\)\{((?:[^{}]|(?<=\\)[{}])*?)(?<!\\)\}'
        replaced_string = re.sub(pattern, replace_option, string)

        return replaced_string, replacements_found

    def get_wildcard_options(string):
        pattern = r"__([\w.\-+/*\\]+?)__"
        matches = re.findall(pattern, string)

        options = []

        for match in matches:
            keyword = match.lower()
            keyword = wildcard_normalize(keyword)

            if '*' in keyword:
                logging.info(f"[umbrae wildcards] [get_wildcard_options] Processing wildcard pattern: keyword={keyword}")

            # Use get_wildcard_value for on-demand loading support
            wildcard_value = get_wildcard_value(keyword)

            if wildcard_value is not None:
                options.extend(wildcard_value)
            elif '*' in keyword:
                total_patterns = []
                found = False

                # For wildcard patterns, search through available wildcards
                search_dict = available_wildcards if _on_demand_mode else local_wildcard_dict

                # Special case: __*/name__ should match both 'name' and 'name/*' at any depth
                if keyword.startswith('*/') and len(keyword) > 2:
                    base_name = keyword[2:]  # Remove '*/' prefix

                    logging.info(f"[umbrae wildcards] [get_wildcard_options] Pattern: keyword={keyword}, base={base_name}, on_demand={_on_demand_mode}, search_dict_size={len(search_dict)}")

                    matched_count = 0
                    for k in search_dict.keys():
                        # Match if key ends with base_name or contains base_name/subdirs
                        # Pattern matching examples for base_name="dragon":
                        #   "dragon" -> match (exact)
                        #   "fantasy/dragon" -> match (nested file)
                        #   "dragon/fire" -> match (subfolder)
                        #   "fantasy/dragon/fire" -> match (deeply nested)
                        if (k == base_name or
                            k.endswith('/' + base_name) or
                            k.startswith(base_name + '/') or
                            ('/' + base_name + '/') in k):
                            logging.info(f"[umbrae wildcards] [get_wildcard_options] Matched: {k}")
                            v = get_wildcard_value(k)
                            if v:
                                total_patterns += v
                                found = True
                                matched_count += 1

                    logging.info(f"[umbrae wildcards] [get_wildcard_options] Result: matched={matched_count}, patterns={len(total_patterns)}")
                else:
                    # General wildcard pattern matching
                    subpattern = keyword.replace('*', '.*').replace('+', '\\+')
                    for k in search_dict.keys():
                        if re.match(subpattern, k) is not None or re.match(subpattern, k+'/') is not None:
                            # Load on-demand if needed
                            v = get_wildcard_value(k)
                            if v:
                                total_patterns += v
                                found = True

                if found:
                    options.extend(total_patterns)
            # Note: Fallback to __*/name__ is handled in replace_wildcard, not here

        return options

    def _lookup(key):
        """get_wildcard_value + the per-call value_hook (clause expander)."""
        options = get_wildcard_value(key)
        if value_hook is None:
            return options
        return value_hook(key, options)

    def _search_keys():
        """Every key that exists right now (both cache modes)."""
        if _on_demand_mode:
            keys = set(available_wildcards.keys())
            keys.update(loaded_wildcards.keys())
            return keys
        return set(local_wildcard_dict.keys())

    def _folder_options(folder_key):
        """v0.8.8 folder call: every line of every key under folder_key/ (sorted
        by key so line indexes are stable between passes)."""
        prefix = folder_key + '/'
        total = []
        for k in sorted(_search_keys()):
            if k.startswith(prefix):
                v = _lookup(k)
                if v:
                    total += list(v)
        return total

    def _pick(options, chain_key, chain, weighted):
        """Pick one option index, never one already open on this branch
        (recursion guard). Returns (index, text without N:: weight) or None."""
        used = {idx for ck, idx in chain if ck == chain_key}
        cand = [i for i in range(len(options)) if i not in used]
        if not cand:
            return None
        if weighted:
            w = np.asarray([max(0.0, _option_weight(options[i])) for i in cand], dtype=float)
            p = w / w.sum() if w.sum() > 0 else None
            idx = cand[int(random_gen.choice(len(cand), p=p))]
        else:
            idx = cand[int(random_gen.choice(len(cand)))]
        return idx, re.sub(r'^\s*[0-9.]+::', '', str(options[idx]), count=1)

    def _pinned_pick(keyword, options, chain_key, chain):
        """{&=N:__key__}: that tag always draws the pinned line (short names match
        like ordinary tags: fabric_colors reaches basic/fabric_colors)."""
        for pk, choice in pin_tags.items():
            if keyword == pk or keyword.endswith('/' + pk) or pk.endswith('/' + keyword):
                idx = pin_index(options, choice)
                if idx is None:
                    logging.warning(f"[umbrae wildcards] pin '{choice}' on __{pk}__: no such line - ignored.")
                    return None
                if any(ck == chain_key and i == idx for ck, i in chain):
                    return None                 # recursion guard still wins
                return idx, strip_option_weight(options[idx])
        return None

    def _apply_pick_hook(chain_key, keyword, options, picked):
        """v0.9.0: let pick_hook force this draw (int line / str text / None=keep).
        The random draw was already consumed, so the rest of the prompt is stable."""
        n = pick_counts.get(chain_key, 0)
        pick_counts[chain_key] = n + 1
        forced = None
        if pick_hook is not None:
            try:
                forced = pick_hook(chain_key, n, options, picked)
            except Exception as e:
                logging.warning(f"[umbrae wildcards] pick_hook failed on __{keyword}__: {e}")
                forced = None
        if isinstance(forced, bool):
            forced = None
        if isinstance(forced, int):
            if 0 <= forced < len(options):
                picked = (forced, strip_option_weight(options[forced]))
            else:
                logging.warning(f"[umbrae wildcards] pick_hook: line {forced} out of range for "
                                f"__{keyword}__ ({len(options)} lines) - ignored.")
                forced = None
        elif isinstance(forced, str):
            picked = ((picked[0] if picked else 0), forced)
        elif forced is not None:
            forced = None
        return n, picked, forced is not None

    def _insert(string, tag, chain_key, picked, keyword, options=()):
        n, picked, forced = _apply_pick_hook(chain_key, keyword, options, picked)
        if trace_draws is not None:
            trace_draws.append({'seq': len(trace_draws), 'key': chain_key, 'tag': keyword, 'n': n,
                                'idx': None if picked is None else picked[0],
                                'count': len(options),
                                'line': None if picked is None else picked[1],
                                'forced': forced})
        if picked is None:
            logging.warning(f"[umbrae wildcards] __{keyword}__: every line is already in use further up "
                            f"this branch (recursive wildcard) - tag removed.")
            return string.replace(tag, '', 1)
        idx, rep = picked
        label = f"{chain_key}#{idx}"
        if trace_draws is not None:
            label += f"{_TRACE_SEP}{len(trace_draws) - 1}"
        return string.replace(tag, f"{_CHAIN_START}{label}{_CHAIN_SEP}{rep}{_CHAIN_END}", 1)

    def replace_wildcard(string, pool=None):
        pattern = r"__([\w.\-+/*\\]+?)__"
        matches = re.findall(pattern, string)

        replacements_found = False

        for match in matches:
            tag = f"__{match}__"
            pos = string.find(tag)
            if pos < 0:
                continue
            chain = chain_at(string, pos)
            # v0.8.8: ./ ../ typed in the prompt, trailing .txt, trailing / = folder
            keyword, folder_only = normalize_tag_key(match)
            chain_key = keyword

            # Use get_wildcard_value for on-demand loading support
            options = None if folder_only else _lookup(keyword)
            if options is False:            # hook: leave this tag as written
                continue

            if options is None and '*' not in keyword and keyword:
                # No such file / key: pool everything under that folder (v0.8.8).
                folder_opts = _folder_options(keyword)
                if folder_opts:
                    options = folder_opts
                    chain_key = keyword + '/'

            if options is not None:
                if pool is not None and not pool:
                    pool.extend(options)
                picked = None
                if pin_tags and not folder_only and not in_protected_span(string, pos):
                    picked = _pinned_pick(keyword, options, chain_key, chain)
                if picked is None:
                    picked = _pick(options, chain_key, chain, weighted=True)
                replacements_found = True
                string = _insert(string, tag, chain_key, picked, keyword, options)
            elif '*' in keyword:
                total_patterns = []
                found = False

                # For wildcard patterns, search through available wildcards
                search_dict = available_wildcards if _on_demand_mode else local_wildcard_dict

                # Special case: __*/name__ should match both 'name' and 'name/*' at any depth
                if keyword.startswith('*/') and len(keyword) > 2:
                    base_name = keyword[2:]  # Remove '*/' prefix

                    for k in search_dict.keys():
                        # Match if key ends with base_name or contains base_name/subdirs
                        # Pattern matching examples for base_name="dragon":
                        #   "dragon" -> match (exact)
                        #   "fantasy/dragon" -> match (nested file)
                        #   "dragon/fire" -> match (subfolder)
                        #   "fantasy/dragon/fire" -> match (deeply nested)
                        if (k == base_name or
                            k.endswith('/' + base_name) or
                            k.startswith(base_name + '/') or
                            ('/' + base_name + '/') in k):
                            v = _lookup(k)
                            if v:
                                total_patterns += v
                                found = True
                else:
                    # General wildcard pattern matching
                    subpattern = keyword.replace('*', '.*').replace('+', '\\+')
                    for k in search_dict.keys():
                        if re.match(subpattern, k) is not None or re.match(subpattern, k+'/') is not None:
                            # Load on-demand if needed
                            v = _lookup(k)
                            if v:
                                total_patterns += v
                                found = True

                if found:
                    if pool is not None and not pool:
                        pool.extend(total_patterns)
                    picked = None
                    if pin_tags and not in_protected_span(string, pos):
                        picked = _pinned_pick(keyword, total_patterns, keyword, chain)
                    if picked is None:
                        picked = _pick(total_patterns, keyword, chain, weighted=False)
                    replacements_found = True
                    string = _insert(string, tag, keyword, picked, keyword, total_patterns)
            elif '/' not in keyword and keyword:
                string_fallback = string.replace(tag, f"__*/{keyword}__", 1)
                string, replacements_found = replace_wildcard(string_fallback, pool)

        return string, replacements_found

    def replace_aspect_requests(string):
        """[[aspect]] -> a description line on its own line for the connected size
        (one line from __aspect/[orientation]__). Size unknown: left as-is so the
        node resolves it when it runs (aspect_final), or dropped with a warning
        when it is final and still unknown. [[W:H]] -> same, for that explicit
        ratio, leaving the [W:H] override behind. Runs inside the expansion loop,
        so requests that come out of a switch, a variable or a wildcard file line
        are handled too."""
        if '[[' not in string:
            return string, False
        found = False
        dropped = False

        def sub(m):
            nonlocal found, dropped
            marker = ''
            # An aspect description line may itself say [[aspect]] where it means
            # the word ("The crop is [[aspect]]"): inside a line drawn from
            # aspect/*, that is the orientation token, not another insertion.
            if not m.group(1) and any(ck.startswith('aspect/') for ck, _i in chain_at(string, m.start())):
                return '[orientation]'
            if m.group(1):
                w, h = int(m.group(1)), int(m.group(2))
                if w <= 0 or h <= 0:
                    return ''
                marker = f' [{w}:{h}]'
            else:
                r = resolve_aspect('', aspect_cfg)
                if r is None:
                    if not aspect_final:
                        return m.group(0)                      # resolved when the node runs
                    logging.warning("[umbrae wildcards] [[aspect]]: no latent / width / height connected "
                                    "to the node - nothing inserted.")
                    found = dropped = True
                    return ''
                w, h = r[0], r[1]
            found = True
            tokens = {'orientation': aspect_orientation(w, h), 'ratio': f'{w}:{h}'}
            insert = fill_tokens(ASPECT_WILDCARD_DEFAULT, tokens).strip()
            missing = [t for t in _TAG_RE.findall(insert) if not get_wildcard_value(wildcard_normalize(t.lower()))]
            if missing:
                logging.warning(f"[umbrae wildcards] aspect wildcard "
                                f"{', '.join('__' + t + '__' for t in missing)} not found - nothing inserted. "
                                f"Default files live in umbrae_nodes/wildcard_examples/aspect/.")
                dropped = True
                return marker.strip()
            before = string[:m.start()]
            after = string[m.end():]
            lead = '' if (not before or before.endswith('\n')) else '\n'
            trail = '' if (not after or after.startswith('\n')) else '\n'
            return f'{lead}{insert}{marker}{trail}'

        out = _ASPECT_REQUEST_RE.sub(sub, string)
        if found:
            # the request sat inside a line: drop the spaces now stranded at the line edges
            out = re.sub(r'[ \t]+\n', '\n', out)
            out = re.sub(r'\n[ \t]+', '\n', out)
        if dropped:
            out = re.sub(r'[ \t]{2,}', ' ', out)
        return out, found

    def replace_wildcard_variables(string):
        reference_pattern = r'(?<!\\)\{@([A-Za-z_][A-Za-z0-9_.-]*)\}'
        replacements_found = False

        variable_name = r'[A-Za-z_][A-Za-z0-9_.-]*'
        bare_reference_pattern = rf'(?<![\w@\\])@({variable_name})'
        exclusion_pattern = rf'#{variable_name}(?:\s*,\s*#{variable_name})*'

        def resolve_name(name):
            if name in wildcard_variables:
                return wildcard_variables[name]
            if name not in wildcard_definitions:
                return None
            if name in resolving_variables:
                raise ValueError(f"Circular wildcard variable reference: @{name}")
            resolving_variables.add(name)
            try:
                resolve_assignment(name, wildcard_definitions[name])
                val = wildcard_variables[name]
                # An @! override may point at a variable that a wildcard file has
                # not defined yet: don't cache it until it fully resolves.
                if name in locked_vars and re.search(r'(?<![\w@\\])@[A-Za-z_]', val or ''):
                    wildcard_variables.pop(name, None)
                return val
            finally:
                resolving_variables.remove(name)

        def collect_assignments(value):
            # Balanced scanning preserves nested options/references in definitions.
            start_pattern = r'(?<!\\)\{@([A-Za-z_][A-Za-z0-9_.-]*)\s*=\s*'
            pieces = []
            position = 0
            while True:
                match = re.search(start_pattern, value[position:])
                if match is None:
                    pieces.append(value[position:])
                    break
                start = position + match.start()
                body_start = position + match.end()
                depth = 1
                end = body_start
                while end < len(value):
                    if value[end] == "\\":
                        end += 2
                        continue
                    if value[end] == '{':
                        depth += 1
                    elif value[end] == '}':
                        depth -= 1
                        if depth == 0:
                            break
                    end += 1
                if depth:
                    pieces.append(value[position:])
                    break
                name = match.group(1)
                if name not in locked_vars:          # an @! override always wins
                    wildcard_definitions[name] = value[body_start:end].strip()
                    wildcard_variables.pop(name, None)
                    wildcard_variable_pools.pop(name, None)
                else:
                    # ...unless the file marks options protected (-=..=-): then the
                    # override only replaces the unprotected ones (v0.8.9)
                    built = locked_group_source(value[body_start:end], locked_vars[name],
                                                locked_modes.get(name, ''))
                    if built is not None and locked_built.get(name) != built:
                        locked_built[name] = built
                        wildcard_definitions[name] = built
                        wildcard_variables.pop(name, None)
                        wildcard_variable_pools.pop(name, None)
                pieces.append(value[position:start])
                position = end + 1
            return ''.join(pieces)

        def resolve_bare_reference(match):
            name = match.group(1)
            value = resolve_name(name)
            # A sentence-ending period is not part of an otherwise known name.
            if value is None and name.endswith('.'):
                trimmed = name.rstrip('.')
                value = resolve_name(trimmed)
                if value is not None:
                    return value + name[len(trimmed):]
            return match.group(0) if value is None else value

        def resolve_variable_value(value, pool=None):
            value = value.strip()

            # The assignment regex strips the surrounding braces, so option syntax like
            # "2-3$$ and $$__x__" or "3$$$, $ and $$__x__" or "a|b|c" arrives bare and
            # replace_options() would never see it. Re-wrap it so selection runs first.
            if len(_split_cycle_options(value)) > 1 or (('$$' in value or '|' in value) and '{' not in value):
                value = '{' + value + '}'

            # Resolve any normal Impact option/wildcard syntax inside the assignment
            # before storing, so every later {@name} reference reuses the same final text.
            depth = 100
            while depth > 1:
                depth -= 1

                previous = value
                value = replace_cycles(value, pool)
                value = collect_assignments(value)
                value = re.sub(reference_pattern, replace_reference, value)
                value = re.sub(bare_reference_pattern, resolve_bare_reference, value)
                value, is_replaced1 = replace_options(value, pool)
                while is_replaced1:
                    value, is_replaced1 = replace_options(value)

                value = re.sub(bare_reference_pattern, resolve_bare_reference, value)
                value, is_replaced2 = replace_wildcard(value, pool)

                if value == previous:
                    break

            return value

        def pin_variable_source(name, source):
            """{&=N:@name}: the variable takes the chosen option of its own list."""
            body = source.strip()
            if body.startswith('{') and body.endswith('}') and _balanced_close(body, 1) == len(body) - 1:
                body = body[1:-1]
            lone = re.fullmatch(r'\s*__([\w.\-+/*\\]+?)__\s*', body)
            if lone:
                options, flags = list(get_wildcard_options(body.strip()) or []), None
            elif len(_split_top(body, '|')) > 1 or _PROT_START in body:
                items = split_protected_options(body)
                options, flags = [t for t, _p in items], [p for _t, p in items]
            else:
                options, flags = [], None
            idx = pin_index(options, pin_vars[name]) if options else None
            if idx is None:
                logging.warning(f"[umbrae wildcards] pin '{pin_vars[name]}' on @{name}: no such option - ignored.")
                return source
            chosen = strip_option_weight(options[idx])
            return wrap_protected(chosen) if flags and flags[idx] else chosen

        def resolve_assignment(name, source):
            nonlocal replacements_found
            pool = []
            if name in pin_vars:
                source = pin_variable_source(name, source)

            # #a,#b draws from a's original pool, excluding only the named
            # fixed values. Derived variables retain that same original pool.
            if re.fullmatch(exclusion_pattern, source):
                names = re.findall(rf'#({variable_name})', source)
                for ref in names:
                    resolve_name(ref)
                if all(ref in wildcard_variables for ref in names):
                    pool = list(wildcard_variable_pools[names[0]])
                    excluded = {wildcard_variables[ref] for ref in names}
                    candidates = []
                    weights = []
                    for option in pool:
                        parts = str(option).split('::', 1)
                        weighted = len(parts) == 2 and is_numeric_string(parts[0].strip())
                        weight = float(parts[0].strip()) if weighted else 1.0
                        candidate = resolve_variable_value(parts[1] if weighted else str(option))
                        if candidate not in excluded and weight > 0:
                            candidates.append(candidate)
                            weights.append(weight)
                    if candidates:
                        probabilities = np.asarray(weights, dtype=float)
                        probabilities /= probabilities.sum()
                        value = str(random_gen.choice(candidates, p=probabilities))
                    else:
                        value = ''
                else:
                    # Keep unresolved names literal, as with unknown @ references.
                    value = source
                    pool = [source]
            else:
                value = resolve_variable_value(source, pool)
                alias = re.fullmatch(rf'@({variable_name})', source)
                if alias and alias.group(1) in wildcard_variable_pools:
                    pool = list(wildcard_variable_pools[alias.group(1)])
                elif not pool:
                    pool = [value]
                else:
                    # Freeze references to existing variables in the saved pool.
                    pool = [re.sub(bare_reference_pattern, resolve_bare_reference, str(x)) for x in pool]

            wildcard_variables[name] = value
            wildcard_variable_pools[name] = pool
            replacements_found = True
            return ''

        def replace_reference(match):
            nonlocal replacements_found
            name = match.group(1)
            value = resolve_name(name)
            if value is not None:
                replacements_found = True
                return value
            return match.group(0)

        original = string
        string = collect_assignments(string)
        replacements_found = string != original
        # @! overrides replace whatever ordinary definition exists for the name
        for name, raw in locked_vars.items():
            raw = locked_built.get(name, raw)
            if wildcard_definitions.get(name) != raw:
                wildcard_definitions[name] = raw
                wildcard_variables.pop(name, None)
                wildcard_variable_pools.pop(name, None)
        # Register every definition before resolving any dependencies.
        for name in list(wildcard_definitions):
            resolve_name(name)
        string = re.sub(reference_pattern, replace_reference, string)
        string = re.sub(bare_reference_pattern, resolve_bare_reference, string)
        replacements_found = replacements_found or string != original

        return string, replacements_found

    replace_depth = 100
    stop_unwrap = False
    while not stop_unwrap and replace_depth > 1:
        replace_depth -= 1  # prevent infinite loop

        option_quantifier = [e.groupdict() for e in RE_WildCardQuantifier.finditer(text)]
        for match in option_quantifier:
            keyword = match['keyword'].lower()
            quantifier = int(match['quantifier']) if match['quantifier'] else 1
            replacement = '__|__'.join([keyword,] * quantifier)
            wilder_keyword = keyword.replace('*', '\\*')
            RE_TEMP = re.compile(fr"(?P<quantifier>\d+)#__(?P<keyword>{wilder_keyword})__", re.IGNORECASE)
            text = RE_TEMP.sub(f"__{replacement}__", text)

        # Switches first: definitions are pulled out and each {&name:...} group is
        # reduced to its chosen option before anything inside it is resolved.
        text, is_collected = collect_locked_and_rules(text)
        text, is_switched = apply_switches(text)
        is_switched = is_switched or is_collected

        # Aspect requests [[aspect]] / [[W:H]] -> description line (v0.8.7)
        text, is_aspect = replace_aspect_requests(text)
        is_switched = is_switched or is_aspect

        # Select cycles before resolving nested variables or ordinary options.
        text = replace_cycles(text)

        # pass0: replace wildcard variable assignments/references
        text, is_replaced0 = replace_wildcard_variables(text)
        is_replaced0 = is_replaced0 or is_switched

        # pass1: replace options
        pass1, is_replaced1 = replace_options(text)

        while is_replaced1:
            pass1, is_replaced1 = replace_options(pass1)

        # pass2: replace wildcards
        text, is_replaced2 = replace_wildcard(pass1)
        stop_unwrap = not is_replaced0 and not is_replaced1 and not is_replaced2

    # Recursion-chain markers (v0.8.8) have done their job once nothing expands.
    if isinstance(trace, dict):
        trace['marked'] = text          # v0.9.0: the expander reads the tree from this
    text = strip_chain_markers(text)

    deferred = bool(defer_switches and _SW_USE_RE.search(text))

    # Deferred switches (box value only known at execution): carry this text's
    # own definitions forward so the execute-time pass can still use them.
    if deferred and (switch_text_defs or switch_locked):
        carried = []
        for name, raw in switch_text_defs.items():
            if name in switch_locked:
                continue
            val = switch_value(name)
            carried.append('{&%s=%s}' % (name, val if val is not None else raw))
        for name, raw in switch_locked.items():
            val = switch_value(name)
            carried.append('{&!%s=%s}' % (name, val if val is not None else raw))
        text = ''.join(carried) + text

    # Aspect tokens ([orientation] [ratio] [width] [height]) from the connected
    # size (or a [W:H] override in the text) - idempotent, so the populate and
    # execute passes may both run it; unknown size waits for the execute pass.
    text = apply_aspect_tokens(text, aspect_cfg, final=aspect_final)

    # Text replacements run LAST (v0.8.6). If switch groups are still pending
    # they are carried forward instead, so they are applied exactly once.
    if text_rules:
        rules = [(mode, find, _resolve_fragment(raw)) for mode, find, raw in text_rules.values()]
        if deferred:
            text = ''.join('{%s%s=%s}' % (mode, f, v) for mode, f, v in rules) + text
        else:
            text = apply_text_replacements(text, rules)

    # protected spans: back to syntax while a deferred pass still has to run,
    # otherwise the markers have done their job
    text = restore_protect_syntax(text) if deferred else strip_protect_markers(text)

    # escaped prefixes are literal text
    text = text.replace('\\+::', '+::').replace('\\-::', '-::')
    return text


def is_numeric_string(input_str):
    return re.match(r'^-?(\d*\.?\d+|\d+\.?\d*)$', input_str) is not None


def safe_float(x):
    if is_numeric_string(x):
        return float(x)
    else:
        return 1.0


def load_yaml_files_only(wildcard_path):
    """
    Load only YAML wildcard files from a directory (for on-demand mode).

    YAML files must be pre-loaded because wildcard keys are inside the file contents.
    Unlike TXT files where "samples/flower.txt" → "__samples/flower__" (file path = key),
    YAML files like "colors.yaml" can contain multiple keys (colors/warm, colors/cold, etc.)
    that are only discoverable by parsing the entire file content.

    Example:
        colors.yaml:
            warm: [red, orange, yellow]   → __colors/warm__
            cold: [blue, green, purple]   → __colors/cold__

        To know that "colors/warm" exists, we must parse colors.yaml completely.
        Therefore, YAML files cannot be truly on-demand loaded.

    Args:
        wildcard_path: Directory to scan for YAML files

    Returns:
        Number of YAML wildcard files loaded (not keys)
    """
    global loaded_wildcards

    yaml_count = 0
    try:
        for root, directories, files in os.walk(wildcard_path, followlinks=True):
            for file in files:
                if file.endswith('.yaml') or file.endswith('.yml'):
                    file_path = os.path.join(root, file)
                    try:
                        # Load YAML file and register all sub-keys
                        _before = set(loaded_wildcards)
                        load_yaml_wildcard(file_path, key_prefix='')
                        _src = os.path.relpath(file_path, wildcard_path).replace(os.sep, '/')
                        for k in set(loaded_wildcards) - _before:
                            key_sources[k] = _src
                        yaml_count += 1
                        logging.debug(f"[umbrae wildcards] Pre-loaded YAML file: {file_path}")
                    except Exception as e:
                        logging.warning(f"[umbrae wildcards] Failed to load YAML file {file_path}: {e}")
    except (OSError, FileNotFoundError) as e:
        logging.warning(f"[umbrae wildcards] Error scanning YAML files in {wildcard_path}: {e}")

    return yaml_count


def get_cache_limit():
    """Wildcard cache limit in bytes (250 MB; Impact's default was 50 MB)."""
    return WILDCARD_CACHE_LIMIT


def wildcard_load():
    """
    (Re)load every wildcard root. Total size < cache limit -> full cache mode;
    otherwise on-demand mode (TXT discovered by path, YAML pre-loaded).

    Roots are read in REVERSE priority order so the higher-priority root
    (umbrae_nodes/wildcards) overwrites duplicate keys from Impact's folder.
    Containers are cleared IN PLACE (other code may hold references to them).
    """
    global _on_demand_mode

    with wildcard_lock:
        wildcard_dict.clear()
        available_wildcards.clear()
        loaded_wildcards.clear()
        key_sources.clear()
        _on_demand_mode = False

        roots = get_wildcard_roots(warn=True)
        _roots_cache[:] = roots
        cache_limit = get_cache_limit()
        total_size = 0
        for root in roots:
            if total_size >= cache_limit:
                break
            total_size += calculate_directory_size(root, limit=cache_limit - total_size)

        load_order = list(reversed(roots))   # lowest priority first

        if total_size >= cache_limit:
            _on_demand_mode = True
            logging.info(f"[umbrae wildcards] Wildcard total size ({total_size / (1024*1024):.2f} MB) "
                         f"exceeds cache limit ({cache_limit / (1024*1024):.2f} MB). Using on-demand loading mode.")
            txt_count = 0
            yaml_count = 0
            for root in load_order:
                txt_count += scan_wildcard_metadata(root)
            for root in load_order:
                yaml_count += load_yaml_files_only(root)
            logging.info(f"[umbrae wildcards] On-demand mode active. Discovered {txt_count} TXT wildcards, "
                         f"pre-loaded {yaml_count} YAML wildcard files.")
        else:
            for root in load_order:
                try:
                    read_wildcard_dict(root, on_demand=False)
                except Exception as e:
                    logging.warning(f"[umbrae wildcards] Failed to load wildcards from {root}: {e}")

        logging.info(f"[umbrae wildcards] Sources (priority order): {roots}")
        if _on_demand_mode:
            logging.info(f"[umbrae wildcards] Wildcards loading done. ({len(available_wildcards)} TXT wildcards available, {len(loaded_wildcards)} pre-loaded)")
        else:
            logging.info(f"[umbrae wildcards] Wildcards loading done. ({len(wildcard_dict)} wildcards loaded)")
