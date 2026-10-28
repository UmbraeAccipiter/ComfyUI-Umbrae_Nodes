# wildcard expander [umbrae]  (umbrae_nodes v0.9.0)

One wildcard prompt in, **N prompts** out, every draw the engine made visible
and editable, over your **whole** wildcard collection. Nothing here depends on
how a pack is laid out: it works on any `.txt` / `.yaml` tree the wildcard
processor can read.

## What it does

- **Batch over a seed plan.** `count` prompts from `seed`: `seed, seed+step, …`
  (sequential) or seeds derived from `seed` (derived). The same seed and edits
  always give the same batch.
- **Draws panel.** For the selected prompt, every `__tag__` the engine resolved,
  nested the way the wildcards nested (a line that pulled in three more tags
  shows them under it), with the wildcard key, which line of how many, and
  what it became. Hover a row for its tools:
  - `⟲` reroll: pin another random line of that wildcard
  - `📌` pin: keep the line that was drawn
  - `☰` pick: a searchable, paged list of the wildcard's lines, or type your
    own text for that draw
  - `⏭` skip: remove the draw (tidy cleans the punctuation it leaves)
  - `✕` clear the edit
  An edit is addressed by **wildcard key + occurrence** (the second `__color__`
  in the prompt is occurrence 2), or by key alone ("every occurrence" in the
  picker). Edits are stored in the hidden `edits` widget as JSON, saved with
  the workflow, applied to every prompt of the batch and to the real run.
  Pinning never shifts the other draws: the engine still makes the random
  pick and only then swaps the result.
- **Prompts panel.** The batch; click one to see its draws. `Copy all`, or
  `→ fixed` to freeze the exact prompts (fixed mode, separated by `---` lines).
  After a run the panel shows what the run produced.
- **Collection** (collapsed). The whole collection as a folder tree with a
  search box. Click a file to see its lines; `＋` inserts the tag (or a folder
  call `__folder/__`), `📌` on a line pins it for every draw of that wildcard,
  `☰` opens the picker.
- **Pins & edits** (collapsed): the list of edits, copy / paste as JSON, clear
  all. Edits that did not match any draw in the current batch are dimmed.
- **Switches** (collapsed): the switches box of the wildcard processor.
- **Seed plan & output** (collapsed): sequential / derived seeds, step,
  dedupe (drop identical prompts, try more seeds), tidy, and the separator of
  the `joined` output.

Outputs: `prompts` (a **list**: a node wired here runs once per prompt),
`joined` (one string), `count`, `seeds` (list aligned with `prompts`).

Everything the wildcard processor understands works here: `{a|b}`, weights,
switches, variables, cycles, `{&=…}` pins, relative tags, folder calls,
`[[aspect]]` with the latent / width / height inputs.

## How it is built

- `umbrae_wildcards.process(pick_hook=, trace=)` (v0.9.0): `pick_hook(chain_key,
  occurrence, options, picked)` is called after each random draw and may return
  a line index, a text (`''` = skip) or `None`; `trace` comes back with one
  record per draw and the text with the recursion-chain markers still in it
  (`key#idxseq`), which `expand.build_draw_tree()` turns into the tree.
- `expand.py`: settings / edits parsing, the pick hook, seed plan, tidy, tree,
  `expand_one` / `expand_batch`, fixed-mode split / join.
- `catalog.py`: the collection tree; `tag_options()` mirrors how the engine
  resolves a tag (file → folder call → `*` pattern → `*/name` fallback) so the
  line indexes shown are the ones a pin needs.
- `server.py`: `GET /umbrae/expander/tree`, `GET /umbrae/expander/entries`,
  `POST /umbrae/expander/expand` (never advances cycles). Reload with the
  processor's `GET /umbrae/wildcards/refresh`. Event `umbrae-expander-feedback`
  after a run.
- `nodes.py`: `UmbraeWildcardExpander` ("wildcard expander [umbrae]", umbrae/text).
- UI: `web/expander/wildcard_expander.js` on the shared ud-* theme.
- Dev: `python3 dev/expander_dev_server.py 8766` serves the pack and the API
  without ComfyUI; open `dev/node_harness.html?only=UmbraeWildcardExpander`.

Compared with the clause expander (a port of ComfyUI-WildcardClause with 17
fixed override slots keyed to one pack's folder names), the expander has no
slot list: whatever your prompt draws is what you can edit.
