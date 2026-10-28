# umbrae_wildcards (v0.9.6)

The **wildcard processor [umbrae]** node on its own, for people who only want that and not the whole
umbrae_nodes pack. It is the same node, engine and syntax colours as in `umbrae_nodes`.

## Install

1. Copy this folder (`umbrae_wildcards`) into `ComfyUI/custom_nodes/`.
2. Restart ComfyUI. The node is under *utils* / "wildcard processor [umbrae]".

Needs only what ComfyUI already ships with (numpy, PyYAML). No extra `pip install`.

**Do not install it next to the full `umbrae_nodes` pack.** Both contain this node. If both are present
only one of them serves the routes and queue hook (a warning is logged), so keep one.

## What is in it

```
umbrae_wildcards/
  __init__.py
  modules/                 engine, node, server routes
  web/                     node UI + syntax colours (web/wildcard_highlight/)
  wildcards/               put your own .txt / .yaml wildcard files here
  wildcard_examples/       shipped examples (lowest priority)
  umbrae_wildcard_syntax.md / .txt / .docx   cheat sheet
```

Wildcard sources, in priority order: `wildcards/` here, then Impact Pack's custom wildcards folder (if
installed), then the shipped examples. Press *Refresh Wildcards* on the node after editing files.

The full syntax (`__tag__`, `{a|b}`, `{@var=...}`, switches `{&x}`, replacements `{!find=replace}`,
protected text, `[[aspect]]`, ...) is in the cheat sheet. The syntax colouring in the text box can be set
under Settings > Umbrae > WildcardHighlight.

The wildcard processor is a port of Impact Pack's (GPL-3.0); this folder is GPL-3.0 too, see `LICENSE`
at the root of the repository.

The code files here are generated copies of the ones in `umbrae_nodes/`; report issues against either.
