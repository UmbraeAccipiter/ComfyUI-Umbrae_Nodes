# umbrae_wildcards.py — umbrae_nodes v0.8.6
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

import configparser
import logging
import os
import random
import re
import threading

import numpy as np
import yaml

# umbrae_nodes/wildcards - highest priority source.
wildcards_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "wildcards"))

RE_WildCardQuantifier = re.compile(r"(?P<quantifier>\d+)#__(?P<keyword>[\w.\-+/*\\]+?)__", re.IGNORECASE)
wildcard_lock = threading.Lock()
wildcard_dict = {}

# Cache size limit in bytes (default: 50MB)
WILDCARD_CACHE_LIMIT = 50 * 1024 * 1024
# Flag to track if on-demand mode is active
_on_demand_mode = False

# Two-phase loading support
# available_wildcards: All discovered wildcard files (metadata only)
# loaded_wildcards: Actually loaded wildcard data
available_wildcards = {}  # key -> file_path mapping
loaded_wildcards = {}     # key -> loaded data


class LazyWildcardLoader:
    """
    Lazy loader for wildcard data to reduce memory usage.
    Acts as a list-like proxy that loads data on first access.
    """
    def __init__(self, file_path, file_type='txt'):
        self.file_path = file_path
        self.file_type = file_type
        self._data = None
        self._loaded = False

    def _load_txt(self):
        """Load .txt wildcard file"""
        try:
            with open(self.file_path, 'r', encoding="ISO-8859-1") as f:
                lines = f.read().splitlines()
                return [x for x in lines if x.strip() and not x.strip().startswith('#')]
        except (yaml.reader.ReaderError, UnicodeDecodeError):
            with open(self.file_path, 'r', encoding="UTF-8", errors="ignore") as f:
                lines = f.read().splitlines()
                return [x for x in lines if x.strip() and not x.strip().startswith('#')]

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
        - In on-demand mode: only loaded wildcards (same as get_loaded_wildcard_list)
    """
    with wildcard_lock:
        if _on_demand_mode:
            return [f"__{x}__" for x in loaded_wildcards.keys()]
        return [f"__{x}__" for x in wildcard_dict.keys()]


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
    dirs.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
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
    umbrae_nodes/wildcards, then Impact's custom wildcards folder."""
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


def load_txt_wildcard(file_path):
    """Load a .txt wildcard file"""
    try:
        with open(file_path, 'r', encoding="ISO-8859-1") as f:
            lines = f.read().splitlines()
            return [x for x in lines if x.strip() and not x.strip().startswith('#')]
    except (yaml.reader.ReaderError, UnicodeDecodeError):
        with open(file_path, 'r', encoding="UTF-8", errors="ignore") as f:
            lines = f.read().splitlines()
            return [x for x in lines if x.strip() and not x.strip().startswith('#')]


def load_yaml_wildcard(file_path, key_prefix=''):
    """Load a .yaml/.yml wildcard file and expand nested structures"""
    global loaded_wildcards

    try:
        with open(file_path, 'r', encoding="ISO-8859-1") as f:
            yaml_data = yaml.load(f, Loader=yaml.FullLoader)
    except (yaml.reader.ReaderError, UnicodeDecodeError):
        with open(file_path, 'r', encoding="UTF-8", errors="ignore") as f:
            yaml_data = yaml.load(f, Loader=yaml.FullLoader)

    if not yaml_data:
        return []

    # For nested YAML structures, expand into loaded_wildcards
    result = []
    for k, v in yaml_data.items():
        if isinstance(v, list):
            sub_key = wildcard_normalize(f"{key_prefix}/{k}") if key_prefix else wildcard_normalize(k)
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
                    loaded_wildcards[sub_key] = v2
                    parent_values.extend(v2)
                elif isinstance(v2, str):
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
            loaded_wildcards[sub_key] = [v]
        elif isinstance(v, (int, float)):
            sub_key = wildcard_normalize(f"{key_prefix}/{k}") if key_prefix else wildcard_normalize(k)
            loaded_wildcards[sub_key] = [str(v)]

    return result if result else list(yaml_data.values())


def is_on_demand_mode():
    """Check if wildcards are running in on-demand mode"""
    return _on_demand_mode


def wildcard_normalize(x):
    return x.replace("\\", "/").replace(' ', '-').lower()


def read_wildcard(k, v, on_demand=False):
    """
    Read wildcard data with optional on-demand loading

    Args:
        k: wildcard key
        v: wildcard value (list, dict, str, or number)
        on_demand: if True, store LazyWildcardLoader instead of actual data
    """
    if isinstance(v, list):
        k = wildcard_normalize(k)
        wildcard_dict[k] = v
    elif isinstance(v, dict):
        for k2, v2 in v.items():
            new_key = f"{k}/{k2}"
            new_key = wildcard_normalize(new_key)
            read_wildcard(new_key, v2, on_demand)
    elif isinstance(v, str):
        k = wildcard_normalize(k)
        wildcard_dict[k] = [v]
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

                if on_demand:
                    # Store lazy loader instead of actual data
                    wildcard_dict[key] = LazyWildcardLoader(file_path, 'txt')
                else:
                    # Load data immediately (original behavior)
                    try:
                        with open(file_path, 'r', encoding="ISO-8859-1") as f:
                            lines = f.read().splitlines()
                            wildcard_dict[key] = [x for x in lines if x.strip() and not x.strip().startswith('#')]
                    except yaml.reader.ReaderError:
                        with open(file_path, 'r', encoding="UTF-8", errors="ignore") as f:
                            lines = f.read().splitlines()
                            wildcard_dict[key] = [x for x in lines if x.strip() and not x.strip().startswith('#')]
            elif file.endswith('.yaml') or file.endswith('.yml'):
                file_path = os.path.join(root, file)

                if on_demand:
                    # For YAML files in on-demand mode, we need to load and parse them
                    # since they may contain nested structures
                    loader = LazyWildcardLoader(file_path, 'yaml')
                    yaml_data = loader.get_data()
                    if isinstance(yaml_data, dict):
                        for k, v in yaml_data.items():
                            read_wildcard(k, v, on_demand)
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
                        for k, v in yaml_data.items():
                            read_wildcard(k, v, on_demand)
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
_RP_START_RE = re.compile(r'(?<!\\)\{(!!|!)(?=[^!=])')
_RP_BODY_RE = re.compile(r'^!!?[^={}]+=')


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
    """Remove every {!find=replace} / {!!find=replace} -> (text, [(strict, find, raw)])."""
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
        out.append((m.group(1) == '!!', find, body[eq + 1:].strip()))
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
    """rules: [(strict, find, value)]. Whole words / phrases only, ONE pass
    (swaps work, nothing is replaced twice). Exact (!!) rules win over
    case-insensitive (!) rules on the same text; longer finds first."""
    if not rules or not text:
        return text
    ordered = sorted(rules, key=lambda r: (not r[0], -len(r[1])))
    parts, table = [], {}
    for i, (strict, find, value) in enumerate(ordered):
        core = r'(?<!\w)' + re.escape(find) + r'(?!\w)'
        parts.append(f'(?P<r{i}>{core})' if strict else f'(?P<r{i}>(?i:{core}))')
        table[f'r{i}'] = (strict, value)
    pattern = re.compile('|'.join(parts))

    def repl(m):
        strict, value = table[m.lastgroup]
        return value if strict else case_like(m.group(0), value)
    # \n line-break markers count as word boundaries (protect \\n literals)
    text = text.replace('\\\\n', '\x01n').replace('\\n', '\x00')
    text = pattern.sub(repl, text)
    return text.replace('\x00', '\\n').replace('\x01n', '\\\\n')


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


def process(text, seed=None, cycle_scope=None, switches=None, defer_switches=False):
    text = process_comment_out(text)

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
    text_rules = {}               # {!find=..} / {!!find=..}  (v0.8.6)

    def collect_locked_and_rules(string):
        """Pull {@!name=...} overrides and {!find=...} replacement rules out of
        the text (prompt or freshly expanded wildcard file lines)."""
        string, locks = _extract_defs(string, _VAR_LOCK_RE)
        for name, raw in locks:
            if name in locked_vars and locked_vars[name] != raw:
                logging.warning(f"[umbrae wildcards] '@!{name}' defined more than once - the later one wins.")
            locked_vars[name] = raw
        string, rules = extract_replacements(string)
        for strict, find, raw in rules:
            key = (strict, find if strict else find.lower())
            if key in text_rules and text_rules[key][2] != raw:
                logging.warning(f"[umbrae wildcards] replacement '{'!!' if strict else '!'}{find}' defined "
                                f"more than once - the later one wins.")
            text_rules[key] = (strict, find, raw)
        return string, bool(locks or rules)

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
            options = match.group(1).split('|')

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
            group_body = match.group(1)
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

            if prefix_mode is not None:
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

    def replace_wildcard(string, pool=None):
        pattern = r"__([\w.\-+/*\\]+?)__"
        matches = re.findall(pattern, string)

        replacements_found = False

        for match in matches:
            keyword = match.lower()
            keyword = wildcard_normalize(keyword)

            # Use get_wildcard_value for on-demand loading support
            options = get_wildcard_value(keyword)

            if options is not None:
                if pool is not None and not pool:
                    pool.extend(options)
                # look for adjusted probability
                adjusted_probabilities = []
                total_prob = 0
                for option in options:
                    parts = option.split('::', 1)
                    if len(parts) == 2 and is_numeric_string(parts[0].strip()):
                        config_value = float(parts[0].strip())
                    else:
                        config_value = 1  # Default value if no configuration is provided

                    adjusted_probabilities.append(config_value)
                    total_prob += config_value

                normalized_probabilities = [prob / total_prob for prob in adjusted_probabilities]
                selected_item = random_gen.choice(options, p=normalized_probabilities, replace=False)
                replacement = re.sub(r'^\s*[0-9.]+::', '', selected_item, count=1)
                replacements_found = True
                string = string.replace(f"__{match}__", replacement, 1)
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
                            v = get_wildcard_value(k)
                            if v:
                                total_patterns += v
                                found = True
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
                    if pool is not None and not pool:
                        pool.extend(total_patterns)
                    replacement = random_gen.choice(total_patterns)
                    replacements_found = True
                    string = string.replace(f"__{match}__", replacement, 1)
            elif '/' not in keyword:
                string_fallback = string.replace(f"__{match}__", f"__*/{match}__", 1)
                string, replacements_found = replace_wildcard(string_fallback, pool)

        return string, replacements_found

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

        def resolve_assignment(name, source):
            nonlocal replacements_found
            pool = []

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

    # Text replacements run LAST (v0.8.6). If switch groups are still pending
    # they are carried forward instead, so they are applied exactly once.
    if text_rules:
        rules = [(strict, find, _resolve_fragment(raw)) for strict, find, raw in text_rules.values()]
        if deferred:
            text = ''.join('{%s%s=%s}' % ('!!' if st else '!', f, v) for st, f, v in rules) + text
        else:
            text = apply_text_replacements(text, rules)

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
                        load_yaml_wildcard(file_path, key_prefix='')
                        yaml_count += 1
                        logging.debug(f"[umbrae wildcards] Pre-loaded YAML file: {file_path}")
                    except Exception as e:
                        logging.warning(f"[umbrae wildcards] Failed to load YAML file {file_path}: {e}")
    except (OSError, FileNotFoundError) as e:
        logging.warning(f"[umbrae wildcards] Error scanning YAML files in {wildcard_path}: {e}")

    return yaml_count


def get_cache_limit():
    """Wildcard cache limit in bytes (Impact's default, 50 MB)."""
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
        _on_demand_mode = False

        roots = get_wildcard_roots(warn=True)
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
