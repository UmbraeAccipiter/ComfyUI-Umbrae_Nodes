# lora loader [umbrae]

One node that stacks any number of LoRAs, finds new ones on Civitai or Hugging
Face, downloads them into `models/loras`, and shows everything Civitai knows
about each file: the full gallery, description, base model and trigger words.

```
inputs    model (MODEL), clip (CLIP, optional)
outputs   MODEL, CLIP, triggers (STRING)
category  umbrae/loaders
```

## The node face

```
 [+ Add LoRA]          [ 2 / 3 on ]  [⚙]
 [on] sdxl/ detail_tweaker   ▾  [1.00]  [i]
 [on] painterly_xl           ▾  [0.80]  [i]
 [  ] old_style              ▾  [1.00]  [i]
```

- **switch** turns the row on or off (an off row dims and is skipped).
- **name** opens the picker. Red with a ⚠ means the file is no longer where the
  row points; pick it again.
- **strength** - type a number, use the arrows, or focus it and scroll. With
  *one strength for model + clip* off (gear) a second, purple box sets the clip
  strength on its own.
- **i** opens the info panel. It lights up when the row has ticked trigger words.
- Right-click a row: move up / down, duplicate, copy the file name or the
  ticked words, remove.
- The band in the middle: **Add LoRA**, the all on/off switch with a count,
  and the gear.

## The picker (click a name)

Three tabs:

- **Local files** - search across every LoRA ComfyUI knows about (every word
  must match), or browse folder by folder. Rows show the preview picture when
  one exists. ↻ rescans the folder.
- **Civitai** - search by text, filter by base model, sort by downloads /
  rating / newest, pick a period, hide or include adult models. Click a card
  for the detail view: gallery (click a picture for full size, arrow keys to
  step through), version dropdown, trigger words, description, and the
  version's files with a **Download** button each. Downloads stream into
  `models/loras/<subfolder>` with a progress bar; when the file lands the row
  is set to it automatically and the Civitai data is saved beside it as
  `<name>.civitai.info`, so its info panel is complete and offline from the
  first click. An existing file is never overwritten silently - you get *use
  it* / *overwrite*.
- **Hugging Face** - searches repos tagged `lora`, sorted by downloads, likes,
  recently updated or trending. The detail view lists the weight files with
  sizes, the model card's trigger word, any preview pictures in the repo, and
  the base model from the repo tags. Downloads work the same way; gated repos
  need your HF token (gear).

## The info panel (click i)

Left: the gallery - Civitai's example pictures at full size, or the preview
picture beside the file. Click the big picture for the lightbox (prev / next,
*open full size*, *copy prompt* when Civitai has the picture's prompt, *use as
preview*). Under it: **Choose picture…** sets your own preview from a file; you
can also paste or drop an image onto the panel. Your own picture wins over the
automatic one and is kept in ComfyUI's user folder, never in the models
folder; **Remove own picture** goes back.

Right: base model, type, creator, dates, download and like counts, tags, and
the file facts read from the safetensors header (size, rank, alpha, training
images). Then:

- **Look up on Civitai** hashes the file (SHA256, cached per file) and asks
  Civitai for the exact-file match; **↻ Refresh** asks again; **Remove saved
  data** deletes the `.civitai.info` sidecar.
- **trigger words** - chips you tick to send to the `triggers` output. When a
  LoRA has both Civitai words and words in its file header, a *Civitai / file*
  toggle switches the list. *all* / *none* / *copy ticked*. Dashed chips are
  your own words: type one in the box, Enter; the × forgets it. Your words
  belong to the LoRA (any row, any workflow), stored on this computer.
- The first time a row gets a LoRA its real trigger words are ticked for you
  (Civitai's trainedWords, else the author's declared phrase; never the
  training tags). Un-ticking sticks.
- **description** and **version notes** from Civitai, expandable.

## The gear

Per node (and *Use these for new nodes*): default strength, arrow step, one
strength for model + clip, trigger separator, hide file extension, show
pictures, LoRA memory between runs (keep the last file / every file in the
stack / nothing).

This computer (kept in `<ComfyUI user dir>/umbrae/lora_account.json`, never in
a workflow): **Civitai API key** (lets the search and lookup see models hidden
from anonymous visitors, and download ones that need a sign-in; shown only as
its last four characters once saved), **ask first** (civitai.com or
civitai.red, the unrestricted address; the other is always the backup),
**allow adult pictures**, **Hugging Face token** (gated repos only), and the
default **download subfolder**.

## Files

```
modules/lora_loader/
  nodes.py      the node: applies the rows, joins the ticked words
  helpers.py    stdlib only: safetensors header, sidecars, Civitai / HF parsing, stores
  remote.py     stdlib only: Civitai / HF requests and the download jobs
  server.py     handle_* (dict in, dict out) + the aiohttp routes under /umbrae/lora/
web/lora_loader/
  index.js      node face, rows, sizing          state.js   the state JSON in the hidden widget
  picker.js     Local / Civitai / HF tabs        info.js    info panel + gallery
  settings.js   gear panel                       ui.js      helpers, stylesheet, overlay, lightbox
dev/lora_dev_server.py   serves the pack + the real routes without ComfyUI (port 8767)
```

The state the node sends to Python is one JSON string in the hidden `state`
widget: `{loras:[{name, on, sm, sc, triggers}], sep, cacheMode, …prefs}`.
Only switched-on rows whose file exists contribute words to `triggers`.

Sidecar format is Civitai's own model-version JSON (the same file other
Civitai helpers write), plus an `umbrae_model` block with the model's name,
description, tags, creator and stats; HF downloads write the same shape with
`umbrae_source: "hf"`.
