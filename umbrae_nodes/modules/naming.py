# naming.py — Umbrae
#
# One naming scheme for every save node:
#
#   filename template  + numbering  + overwrite
#
#   template   free text with tokens. {stem} = source filename without its
#              extension (empty when nothing is wired). {n} = the file number
#              ({n4} forces 4 digits; bare {n} uses the Digits setting). Save
#              image smart also resolves its metadata / date tokens first.
#   numbering  on: every saved file gets a number. It goes where {n} is, or is
#              appended as _{n}. A JOB is one pass of the batch loader (or one
#              queue press without a loader); the number counts up through the
#              job and never repeats inside it.
#   overwrite  on:  a new job restarts at Start and replaces the last job's
#                   files; an existing file with the same name is replaced.
#              off: a new job continues after the highest number already in
#                   the folder, and nothing on disk is ever replaced.
#
# An empty name is never written: it falls back to the number alone, or to
# "image" when numbering is off.

import os
import re

NUM_RX = re.compile(r"\{n(\d*)\}")


def sanitize(s):
    s = re.sub(r"[\x00-\x1f\x7f]", "", str(s or ""))
    s = re.sub(r'[\\/:*?"<>|]', "_", s)
    return s.strip(" .")


def has_number_token(template):
    return bool(NUM_RX.search(template or ""))


def apply_number(template, n, digits):
    return NUM_RX.sub(lambda m: str(n).zfill(int(m.group(1) or digits)), template or "")


def build_filename(template, tokens=None, number=None, digits=4):
    """Resolve {tokens}, place the number, sanitize. Never returns ''."""
    name = template or ""
    for k, v in (tokens or {}).items():
        name = name.replace("{" + k + "}", str(v or ""))
    if number is not None:
        if has_number_token(name):
            name = apply_number(name, number, digits)
        else:
            num = str(number).zfill(max(1, int(digits)))
            core = sanitize(name)
            name = f"{core}_{num}" if core else num
    name = sanitize(name)
    return name or "image"


def highest_number(folder, template, tokens, ext, digits=4):
    """Highest number among files in `folder` that this template (with these
    token values) could have produced. None when there are none."""
    try:
        files = os.listdir(folder)
    except Exception:
        return None
    probe = build_filename(template, tokens, 0, digits)
    # Turn the digits of the probe's number into a capture group. The number's
    # width is the {nK} width when the template sets one, else `digits`.
    m = NUM_RX.search(template or "")
    width = int(m.group(1)) if (m and m.group(1)) else max(1, int(digits))
    zero = "0" * width
    pos = probe.rfind(zero)
    if pos < 0:
        return None
    rx = re.compile("^" + re.escape(probe[:pos]) + r"(\d+)" + re.escape(probe[pos + len(zero):])
                    + r"\." + re.escape(ext.lstrip(".")) + "$", re.IGNORECASE)
    best = None
    for f in files:
        m = rx.match(f)
        if m:
            try:
                v = int(m.group(1))
                best = v if best is None else max(best, v)
            except ValueError:
                pass
    return best


def free_path(folder, stem, ext, digits=4):
    """stem.ext if free, else stem_0001.ext … (for un-numbered names with
    overwrite off). Returns (path, final_stem)."""
    ext = "." + ext.lstrip(".")
    p = os.path.join(folder, stem + ext)
    if not os.path.exists(p):
        return p, stem
    k = 1
    while True:
        s = f"{stem}_{str(k).zfill(max(1, int(digits)))}"
        p = os.path.join(folder, s + ext)
        if not os.path.exists(p):
            return p, s
        k += 1


def current_prompt_id():
    """ComfyUI's id of the prompt being executed, or None outside the server."""
    try:
        from server import PromptServer
        return getattr(PromptServer.instance, "last_prompt_id", None)
    except Exception:
        return None


class JobCounter:
    """Per-node-instance file number. begin() once per prompt; take() per file."""

    def __init__(self):
        self.prompt_id = object()   # never equal to a real id
        self.value = None

    def begin(self, prompt_id, job_pos, start, overwrite, scan):
        """prompt_id: current prompt (None = unknown). job_pos: loader index of
        this run (0 = first image of a job, -1/None = no loader -> every run is
        its own job). scan(): highest number already on disk, or None."""
        if prompt_id is not None and prompt_id == self.prompt_id:
            return                                   # same prompt, e.g. list input
        self.prompt_id = prompt_id
        job_start = job_pos is None or int(job_pos) <= 0
        if job_start or self.value is None:
            if overwrite:
                self.value = int(start)
            else:
                hi = scan()
                self.value = int(start) if hi is None else max(int(start), hi + 1)

    def take(self):
        if self.value is None:
            self.value = 0
        v = self.value
        self.value += 1
        return v
