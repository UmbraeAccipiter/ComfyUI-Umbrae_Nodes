# wildcard clause expander [umbrae]  (umbrae_nodes v0.8.8, testing port)

Port of **ComfyUI-WildcardClause** (Wildcard Clause Expander) onto the umbrae
wildcard engine. Same node layout, same 17 override fields, same web UI (live
preview, ghosts, Pin / Skip / Regenerate, presets, template catalog), but every
expansion runs through `umbrae_wildcards.process()`:

- seeded picks (same seed = same text), `{a|b}`, `N::` weights, switches,
  variables, cycles, `[[aspect]]`, relative tags `__./x__`, folder calls
  `__folder/__`, recursion guard - everything in umbrae_wildcard_syntax.md
- wildcard sources = the umbrae roots (umbrae_nodes/wildcards, Impact's
  custom wildcards folder, wildcard_examples), so the UW pack keeps working
- overrides are applied through `process(value_hook=...)`, per call, instead of
  monkeypatching Impact's module

| Original | umbrae port |
|---|---|
| node `WildcardClauseExpander` | `UmbraeWildcardClauseExpander` ("wildcard clause expander [umbrae]", category umbrae/text) |
| routes `/wildcardclause/*` | `/umbrae/clause/*` |
| picker `/impact/wildcards/list` | `/umbrae/wildcards/list` |
| event `wildcardclause-node-feedback` | `umbrae-clause-feedback` |
| presets / catalog root | Impact's custom wildcards folder when it exists, else umbrae_nodes/wildcards |

Both packages can be installed at the same time; nothing is shared.

Files: `__init__.py` (registers routes + queue-time populate hook), `nodes.py`,
`clause_expand.py` (override matching, preview, reroll), `preview_server.py`,
`prompt_hooks.py`, `preset_store.py`, `capabilities.py`, `catalog_index.py`,
`contract.py` (field list) and `../../web/clause/*.js`.

Override matching is by key PATH, so a plain folder tree works as well as the
UW YAML: `…/leaf/<scene>/wardrobe|environment|medium|lighting|treatment`,
`…/common/hair/…`, `…/common/age/…`, `…/body-archetype/…`, `…/eye-color/…`,
`…/nationality/…`, `…/common/skin/…`, `…/face-features/…`, `…/piercing/…` or
`…/accessories/…`, `…/skin-tone/…`, `…/hair-color/…`, `…/breast-size/…`,
`…/butt-size/…` (see `is_atom_override_key` in clause_expand.py).

Not changed from the original: the structural-preview heuristic (pools whose
lines are mostly tags unwrap, caption pools stay as `__tags__`), the preset JSON
format, and the catalog scan (`user-wildcards/**/*templates*.yaml`).
