# wildcard processor [umbrae] — syntax cheat sheet (v0.8.6)

Sources: `umbrae_nodes/wildcards/` (wins on duplicate names) + Impact Pack's custom wildcards folder. Press **Refresh Wildcards** after editing files.

## Basics (Impact-compatible)
| Syntax | Result |
|---|---|
| `__name__` | random line from `name.txt` (subfolders: `__folder/name__`; YAML keys: `__file/key__`) |
| `__col*__`, `__*/name__` | pattern match across files / any depth |
| `{a\|b\|c}` | random pick each run |
| `{2::a\|b\|0.5::c}` | weighted pick (`N::` weight) |
| `{2$$a\|b\|c}` / `{1-3$$...}` / `{-3$$...}` | pick 2 / 1–3 / up to 3, joined by space |
| `{2$$, $$a\|b\|c}` | custom join (", ") |
| `{3$$$, $ and $$__x__}` | oxford join: "x, y and z" |
| `{2$$__file__}` | pick from a file's lines |
| `{2$$3#__name__}` | `3#__name__` becomes three `__name__` options inside the group, so picks can repeat (e.g. "red red"). Outside a group it leaves literal `\|` between the picks. |
| `# line` | comment (line removed) |
| `\{ \}` | literal braces |
| `\n` | line break in the output (also inside wildcard file lines); `\\n` = literal `\n` |
| `\&` | literal `&` |
| `\!` | literal `!` |

## Switches
A switch stores a number; every `{&name:...}` group picks that option (counting from 1), so separate groups stay consistent.

| Syntax | Result |
|---|---|
| `{&gend=2}` | define switch `gend` = 2 (removed from the output; can sit anywhere in the text) |
| `{&gend={1\|2}}` | random value, picked once per run, the same in every group |
| `{&gend={-::1^2}}` | alternates 1, 2, 1, ... across runs |
| `{&gend:him\|her}` | option 2 -> "her" |
| `{&gend:{his\|their}\|her}` | nested groups inside an option still work |

- **switches box** on the node: `gend=2, hair=4`, `{&gend=2}{&hair=4}`, or any mix (commas or new lines). It overrides same-named definitions in the prompt. Connect one text node to several processors to keep them all in agreement.
- Out of range (including 0) -> last option + warning.
- Undefined name or non-number value -> one random option is picked for that name (using the first group's `N::` weights) and every group with that name uses it, so they stay consistent. A warning is logged when you press Run, so you can cancel before generating.
- No count (`2$$`) or `-::` / `+::` prefix inside a switch group; `N::` weights are ignored when the switch is defined.
- Box typed, or connected from a Primitive / plain text node: resolved when you press Run. Connected from a node that computes text: switch groups are resolved when the node executes (populated_text still shows them; the undefined-name fallback and its warning also happen then).
- Example: box `{&gend=2}{&hair=4}` + prompt `{&gend=1}1{&gend:boy|girl}, {&hair:black|blond|brown|red} hair` -> `1girl, red hair`

## Overrides
An override beats every ordinary definition of the same name — in the prompt or inside any wildcard file — wherever it sits.

| Syntax | Result |
|---|---|
| `{@!fcolor1=@fcolor2}` | variable override: `fcolor1` takes `fcolor2`'s value, even when a wildcard file defines both (the value is resolved when `fcolor1` is used, so it can point at variables defined in files) |
| `{@!fcolor1={teal\|olive}}` | any variable value works: text, `{a\|b}`, `__file__`, `#a` |
| `{&!gend=2}` | switch override: beats `{&gend=...}` in the prompt or in files |

- Priority for switches: switches box > `{&!...}` > `{&...}`.
- The same override defined twice: the later one wins (+ warning). A reference to a variable that is never defined is left as-is.
- Example: file `{@fcolor1={blue|navy}}{@fcolor2={red|crimson|scarlet}}a {@fcolor1} shirt with {@fcolor2} trim` + prompt `{@!fcolor1=@fcolor2} __outfit__` -> "a red shirt with red trim"

## Text replacement
Runs LAST, after all wildcards, variables, switches and cycles. Whole words / phrases only ("there" is never touched by `her`). All replacements happen in one pass, so swaps work and nothing is replaced twice.

| Syntax | Result |
|---|---|
| `{!she=he}` | any case matches; the case follows the replaced text: she -> he, She -> He, SHE -> HE |
| `{!!She=Mary}` | exact case only: replaces "She", leaves "she" / "SHE"; inserted exactly as written |
| `{!her=him}{!him=her}` | swap |
| `{!long red hair=short black hair}` | phrases work (Long Red Hair -> Short Black Hair) |
| `{!cat={dog\|fox}}` | the replacement may contain syntax, resolved once per run |

- Case rules for `!`: all lowercase -> lowercase · first letter capitalised -> first letter capitalised · ALL CAPS -> ALL CAPS · a phrase with Every Word Capitalised -> Every Word Capitalised · anything mixed ("sHe") -> as written.
- Note: a lowercase match makes the replacement lowercase, so `{!she=Mary}` turns "she" into "mary" — use `{!!she=Mary}` to keep a name's capital.
- If a `!` and a `!!` rule match the same word, `!!` wins; a longer phrase wins over a shorter one.
- Can be defined in the prompt or in a wildcard file. The same find defined twice: the later one wins (+ warning). Removed from the output.

## Variables
| Syntax | Result |
|---|---|
| `{@hero=__emotions__}` | define once; text resolved once per run |
| `{@hero}` or `@hero` | reuse the same value |
| `{@b=#a}` / `{@c=#a,#b}` | draw from a's original pool, excluding a (and b) |

## Persistent selection (remembered between runs; cleared by **Reset cycles & counter** or a ComfyUI restart)
| Syntax | Result |
|---|---|
| `{a^b^c}` | shuffled bag — every item once before any repeats |
| `{-::a^b^c}` | written order a, b, c, a, … |
| `{-::__file__}` | written order through a file's lines |
| `{+::a\|b\|c}` | random, never the same item twice in a row |
| `{3+::a\|b\|...}` | random, none of the last 3 items used |
| `{3$$3+::a\|b\|...}` | 3 per run, none of the previous run's 3 |
| `{2+::a^b^c^d}` | shuffled bag; a new bag never opens with the last 2 items |
| `{2+::__file__}` | no-repeat draw from a file |

Non-persistent order: `{-::a|b|c}` = first item; `{2$$-::a|b|c}` = "a b" (written order, this run only).

Rules:
- Prefix goes right after `{` or after the count header (`N$$`, `N$$sep$$`, `N$$$s1$s2$$`).
- One prefix per group.
- `\+::` / `\-::` are literal text.
- `N::` weights apply under `+::`, are ignored under `-::`.
- If the history would leave too few options it shrinks to the most recent items (never errors, never empty).
- Draws happen when a run is queued.
- A prefixed group containing a nested random group, e.g. `{2+::a|{b|c}}`, starts a new history whenever the inner pick changes.

## Node controls
- **mode**: populate (fill populated_text when you press Run; read-only but copyable) · fixed (use populated_text exactly as written) · reproduce (pick by hand: use populated_text once, then back to populate).
- **Loading an image**: the node comes back in populate mode, so it regenerates from wildcard_text. The image's exact prompt is shown in populated_text — copy it before running, or switch to **fixed** to re-create it exactly.
- **seed** connected to a node that computes it: the prompt is resolved when the node runs (populated_text updates then; a warning is logged).
- **runs**: queue X runs; the next run is queued only after the previous finishes; cancel / interrupt / error stops the series (a workflow-tab switch mid-run also stops it). Outputs `run_index` (1..X) and `runs_remaining`. Don't also set ComfyUI's batch count (they multiply).
- **Reset cycles & counter**: restart this node's bags, orders, histories and countdown from the beginning. Stopping a series does NOT reset cycles.
- **switches**: switch values (see Switches).
- **Refresh Wildcards**: reload wildcard files from disk.

## Example — 28 expressions, one each, in list order, then stop
- `emotions.txt` in `umbrae_nodes/wildcards/`, one expression per line
- `wildcard_text = {-::__emotions__}`
- `runs = 28`
- Press **Reset cycles & counter**, then Run once.
