# umbrae_nodes

Custom nodes for ComfyUI. Everything you may want to open or edit is in the
pack root; the code is tucked away in `modules/`.

```
umbrae_nodes/
  __init__.py                 node registration (ComfyUI needs this here)
  README.md                   this file
  umbrae_wildcard_syntax.md   wildcard processor cheat sheet (same text as .txt / .docx)
  umbrae_wildcard_syntax.txt
  umbrae_wildcard_syntax.docx
  wildcards/                  YOUR wildcard files (highest priority, never overwritten)
  wildcard_examples/          shipped wildcards: aspect defaults + syntax examples
                              (lowest priority, replaced on update - copy, don't edit)
  web/                        front-end (JS); web/clause/ = clause expander UI,
                              web/expander/ = wildcard expander panel,
                              web/wildcard_highlight/ = syntax colours for the wildcard processor
  modules/                    all Python: nodes, wildcard engine, server routes
  modules/clause/             wildcard clause expander (see its README.md)
  modules/expander/           wildcard expander (see its README.md)
  modules/vlm/                HF vision-language / LLM loader + generate (see its README.md)
  modules/lora_loader/        lora loader: node, Civitai / HF client, routes (see its README.md)
  dev/                        browser harness for the UI lab (not loaded by ComfyUI)
```

Wildcard sources, in priority order: `wildcards/` → Impact Pack's custom
wildcards folder (if installed) → `wildcard_examples/`. Press **Refresh
Wildcards** on a node after adding or editing files.

Nodes: wildcard processor [umbrae], wildcard expander [umbrae] (one prompt ->
N prompts, pin / skip / replace any draw, browse the whole collection), wildcard
clause expander [umbrae], load vlm / llm (hf) [umbrae] + vlm generate [umbrae]
+ caption prompt (joycaption) [umbrae] (Hugging Face captioners / LLMs that
share VRAM with your diffusion models; models go in `ComfyUI/models/LLM/`),
lora loader [umbrae] (LoRA stack with a triggers output; the picker searches
your files, Civitai and Hugging Face and downloads into models/loras; the i
button shows the Civitai gallery, description and trigger words - see
`modules/lora_loader/README.md`),
run timer [umbrae] (whole-workflow stopwatch; ▲ / ▼ under the clock expand a
list of the last N run times, newest first, saved with the workflow),
plus the image / mask / crop / save utilities listed in `__init__.py`.

Syntax colours (v0.9.4; `web/wildcard_highlight/`): the wildcard processor's
wildcard_text box colours tags, variables, switches, overrides, pins,
replacements, protected text, aspect tokens, weights, escapes, comments and
brackets (nesting depth, partner highlight under the caret, same-name highlight,
alternating option colours). Red is only for warnings (unmatched brackets,
unknown `__tags__`). Everything is under Settings -> Umbrae -> WildcardHighlight
(dark preset by default, dark / light reset, a colour picker per category). It
only draws the text differently; it never changes it. See the syntax cheat sheet.

Training-data pipeline (`load images batch` -> detector -> `crop image` ->
`vlm generate` -> `training prep`): `crop image [umbrae]` emits one list item
per crop at its native size, `vlm generate` captions each item, and `training
prep [umbrae]` takes the whole list, pairs captions with crops by index and
saves every crop + `.txt` (+ mask) under its own name. Only one node in a graph
steps the batch loader per finished run (`web/umbrae_loop.js`), however many
training prep / crop image region / save nodes it contains.

Save naming (save image smart, save training pair; `modules/naming.py`): one
**filename** template (`{stem}` = source name without extension, `{n}` /
`{n4}` = the number, save image smart also takes `{model}` `{date}` …), a
**number files** switch with **start at** and **digits**, and **overwrite**.
A job is one batch-loader pass (or one queue press without a loader).
Overwrite on: the next job restarts at *start* and replaces the last job's
files. Off: it continues after the highest number already in the folder and
never replaces anything. Nothing wired + default template = just the number
(`0000.png` …). Older workflows' Rename Mode / Base Name / Pattern / Auto Index
settings are converted on load.

Resize mode **Bbox** (save image smart, load images batch): the crop is the
box wired into `bbox_override` (4 numbers, dict, tensor or a SEGS' first box).
**Min** grows the window around the box, in native pixels, until its short
edge reaches the value (never upscales); **Max** downscales the crop so its
long edge is at most the value; 0 = off. In resize mode Crop the same input
only supplies the window's centre. Optional **upscale_model** input (crop
image, training prep, save image smart): when the resize stage enlarges
(direction Up / Both) the model does the enlarging and Lanczos only the final
fit; output sizes are unchanged and masks follow the same geometry.
