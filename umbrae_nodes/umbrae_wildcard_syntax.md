# wildcard processor [umbrae] — syntax cheat sheet (v0.9.4)

Sources, in priority order: `umbrae_nodes/wildcards/` (your files) → Impact Pack's custom wildcards folder → `umbrae_nodes/wildcard_examples/` (shipped with the pack: aspect defaults + syntax examples, replaced on update). A file in a higher source wins, so copy an example into `wildcards/` under the same path to edit it. Press **Refresh Wildcards** after editing files.

## Basics (Impact-compatible)
| Syntax | Result |
|---|---|
| `__name__` | random line from `name.txt` (subfolders: `__folder/name__`; YAML keys: `__key/subkey__`) |
| `__name.txt__` | same as `__name__` (a trailing `.txt` / `.yaml` is ignored) |
| `__folder/__` | one line from **every** file under `folder/` (also what `__folder__` does when no `folder.txt` exists) — see Relative tags & folders |
| `__./name__`, `__../name__` | inside a wildcard file: `name` next to this file / one folder up — see Relative tags & folders |
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

## Relative tags & folders (v0.8.8)
Wildcard files can refer to each other without spelling out the full path from the wildcard root, so a pack keeps working when its folder is renamed or moved.

| Syntax (inside a wildcard file) | Result |
|---|---|
| `__./face__` | `face.txt` (or `face/`) in the **same folder** as the file containing the line |
| `__../scene__` | `scene.txt` one folder **up**; `__../../x__` two up, and so on |
| `__./outfit/__` | every file under the `outfit/` folder next to this file |
| `__./person/jim.txt__` | extensions are allowed and ignored |

- Relative tags are resolved when the file is **loaded** (press **Refresh Wildcards** after moving files). `wildcards/CivitBobWildcrd/templates/main.txt` containing `__../person/jim__` reaches `wildcards/CivitBobWildcrd/person/jim.txt` whatever the pack folder is called.
- In a YAML file they count from the folder the `.yaml` file sits in.
- Typed directly into the prompt box (no file to count from) `./` means the wildcard root, so `__./x__` is just `__x__`.

**Folder calls.** `__person/outfit__` with no `outfit.txt` pools every line of every file under `person/outfit/` and picks one (a 50-line file gets 50 chances, a 2-line file gets 2). `__person/outfit/__` (trailing slash) forces the folder even when `outfit.txt` also exists; without the slash the file wins.

**Recursion.** A file may call itself or its own folder. A line that is already in use further up the same branch is never picked again, so recursion ends by itself instead of repeating one line until the 100-pass limit. If every line of a tag is already in use, that tag is removed and a warning is logged. Example `story.txt`:
```
hero, __./story__
villain, __./story__
the end.
```
`__story__` → `hero, villain, the end.` / `villain, the end.` / `the end.` ... (each line at most once per branch).

**Example layout** (shipped in `wildcard_examples/example/portrait/`, call it with `__example/portrait/portrait__`):
```
example/scene.txt
example/portrait/portrait.txt   a portrait of someone with __./face__, __./outfit/__, __../scene__
example/portrait/face.txt
example/portrait/outfit/casual.txt
example/portrait/outfit/formal.txt
```

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

### Protected options and `=r=` (v0.8.9)
Mark options in a file's definition with `-=...=-` and an `@!` override only touches the others. One marker pair may wrap several options.

| Syntax | Result |
|---|---|
| `{@shade=-=light=-\|dark\|-=bright=-\|dull}` | `light` and `bright` are protected; `dark` and `dull` are not |
| `{@shade=-=light\|dark\|deep=-\|rich\|bright}` | one pair protects `light`, `dark` and `deep` |
| `{@!shade=shining}` | **per draw:** every unprotected option becomes `shining` (its own weight kept), so `shining` appears only when an unprotected option is drawn. Protected options and all other odds are unchanged. |
| `{@!shade=r=shining}` | **replace first:** all unprotected options collapse into ONE `shining` entry before the draw. It inherits the highest weight among the options it replaced, so it competes evenly with the protected ones. |

- Example, 7 options with 3 protected: `{@!shade=shining}` shows `shining` 4 times in 7; `{@!shade=r=shining}` shows it 1 time in 4.
- Without any protected option both forms replace the whole value, as before.
- The file's definition must be a plain `a|b|c` list. Protected text is also shielded from `{!...}` replacements.

## Pins (v0.8.9)
A pin forces a choice without editing any file. Format: `{&=CHOICE:TARGET}`.

| Syntax | Result |
|---|---|
| `{&=2:@gend}` | the variable `gend` takes its 2nd option wherever it is defined |
| `{&=red:__fabric_colors__}` | every draw from `fabric_colors` takes the first line containing "red"; everything else stays random |
| `{&=1:him\|her}` | every group whose options are exactly `him\|her` (any case) takes option 1 |

- CHOICE: a number = the Nth option / line; text = the first option / line containing that word (case ignored). Text survives edits better than numbers.
- No match: a warning is logged and the ordinary random draw is used.
- Short tag names match like ordinary tags (`__fabric_colors__` reaches `basic/fabric_colors`).
- Pins beat random picks; `@!` and `&!` overrides still win. Groups and tags inside `{-=...=-}` are left alone.
- Work in the prompt and in wildcard files; removed from the output. Not read from the switches box.

## Text replacement
Runs LAST, after all wildcards, variables, switches and cycles. Whole words / phrases only ("there" is never touched by `her`). All replacements happen in one pass, so swaps work and nothing is replaced twice.

| Syntax | Result |
|---|---|
| `{!she=he}` | any case matches; the case follows the replaced text: she -> he, She -> He, SHE -> HE |
| `{!!She=Mary}` | exact case only: replaces "She", leaves "she" / "SHE"; inserted exactly as written |
| `{!!!mod=LoRa}` | any case matches (mod, Mod, MOD, mOd), but the replacement is always inserted exactly as written: `LoRa` |
| `{!!!!mod=LoRa}` | exact case only and inserted as written — same as `{!!mod=LoRa}` (alias, so the four flags read as a set) |
| `{!her=him}{!him=her}` | swap |
| `{!long red hair=short black hair}` | phrases work (Long Red Hair -> Short Black Hair) |
| `{!cat={dog\|fox}}` | the replacement may contain syntax, resolved once per run |

- Case rules for `!`: all lowercase -> lowercase · first letter capitalised -> first letter capitalised · ALL CAPS -> ALL CAPS · a phrase with Every Word Capitalised -> Every Word Capitalised · anything mixed ("sHe") -> as written.
- Note: a lowercase match makes the replacement lowercase, so `{!she=Mary}` turns "she" into "mary" — use `{!!she=Mary}` to keep a name's capital.
- Flags at a glance: `!` any case in, case follows out · `!!` / `!!!!` exact case in, as written out · `!!!` any case in, as written out.
- If rules match the same word, `!!` wins, then a longer phrase, then `!!!` before `!`.
- Can be defined in the prompt or in a wildcard file. The same find defined twice: the later one wins (+ warning). Removed from the output.

### Protected text (v0.8.9)
| Syntax | Result |
|---|---|
| `{-=man=-}` | the text between the markers is written to the output as-is and **no `{!...}` / `{!!...}` / `{!!!...}` replacement touches it**; the `{-=` `=-}` wrapper is removed |

- The contents still resolve normally first (`{-=a {red|blue} man=-}`, `{-=__./who__=-}`); only the replacement step skips them.
- Use it where a replacement rule would be wrong: with `{!man=woman}` in the prompt, "the man" becomes "the woman" but `{-=man=-}` stays "man" (a mannequin, a character's fixed title, a quoted word).
- Works in the prompt and inside wildcard file lines. Text outside the markers is replaced as usual.

### Gendered wildcard text
Write gendered words once as switches, then set the gender in one place:
```
{&gend:he|she} wears {&gend:his|her} {&gend:brown|red} jacket        (in a wildcard file)
{&gend=2}                                                             (prompt or switches box)
{&!gend=1}                                                            (override: beats any {&gend=...})
```
Keep the option order the same everywhere (1 = male, 2 = female). A single-gender line can skip the switch and still be flipped with `{!she=he}`; wrap words that must never flip in `{-=...=-}`.

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

## Aspect ratio (v0.8.7)
The node reads the image size from the workflow and adapts the text to it. Connect the **latent** the image is made from (or **width** + **height** ints) to the node's inputs; nothing needs typing.

| Syntax | Result |
|---|---|
| `[[aspect]]` | inserts a description of the connected image's orientation on its own line: one random line from `__aspect/[orientation]__`, i.e. `aspect/horizontal`, `aspect/vertical` or `aspect/square`. Defaults ship in `wildcard_examples/aspect/`; copy one into `wildcards/aspect/` to edit it. |
| `[orientation]` | token → `horizontal`, `vertical` or `square` (W = H) |
| `[ratio]` | token → nearest common ratio of the connected size, e.g. 1328×752 → `16:9` (exact fraction when none is within 3 %) |
| `[width]` / `[height]` | token → the connected pixel size |
| `[3:4]` | typed override, used only when nothing is connected; removed from the output. `[[3:4]]` = request + override in one. |

- Tokens are filled last, anywhere in the text: in the prompt and in wildcard file lines. Unknown `[words]` are left as typed.
- Orientation: W > H horizontal, W < H vertical, W = H square.
- Requests work wherever they appear (a switch option, a variable, a wildcard file line).
- Inside the lines of `aspect/*.txt` themselves, write `[orientation]` for the word ("The crop is [orientation]"). A `[[aspect]]` there is read as `[orientation]` too, so it can never nest another line (v0.8.9).
- The size is often only known when the node runs (a latent, or a width/height computed by another node). Then `[[aspect]]` and the tokens stay as typed in populated_text at queue time and are resolved during the run; populated_text is updated afterwards.
- Nothing connected and no typed override: `[[aspect]]` inserts nothing and the tokens use 1:1 (warning logged).
- Missing aspect wildcard: nothing inserted (warning logged).

## Syntax colours (v0.9.4)
The wildcard_text box colours its syntax as you type, so wildcards, variables and brackets stand out. It only changes how the text is drawn - the prompt itself is never touched. populated_text is not coloured.

| Text | Coloured as |
|---|---|
| `__name__` | tag: the name and its __ ends are two blues; a tag that matches no wildcard turns red |
| `{@x}  @x` | variable; an override {@!x} has its own colour |
| `{&x}` | switch; an override {&!x} and a pin {&=2:x} each have their own colour |
| `{!a=b}` | replacement (also {!!a=b}, {!!!a=b}, {!!!!a=b}) |
| `{-=x=-}` | protected text |
| `[[aspect]]  [ratio]` | aspect request and tokens |
| `2::  2$$  -::  +::` | weights, counts and persistent prefixes |
| `|  ^` | option separators |
| `\{  \n` | escapes (literal text) |
| `# line` | comment line |

- A brace takes the colour of its group's kind ({@x} orange, {&x} violet ...). Plain {a|b} groups cycle four colours by nesting depth. Closing braces are coloured like their opener (setting).
- Options inside a group: every second option gets another colour (default). Setting: alternate / none / cycle (4 colours) / tint (background).
- Caret touching a { } brace: its partner lights up. Caret inside a tag, variable or switch: every other use of that name lights up.
- Red is used only for warnings: an unmatched { or }, an unmatched [[ or ]], and a __tag__ that matches no wildcard.
- The unknown-tag check asks the server how the engine would resolve the tag (relative and folder tags included; patterns with * are not checked) and follows Refresh Wildcards within a few seconds.
- Settings -> Umbrae -> WildcardHighlight: on / off, colour closers, partner on caret, same-name highlight, unknown-tag warning, option mode, "Reset all colours to" dark or light, and one colour picker per category.
- Default: dark palette (light tones for dark mode). Choose light to reset every picker to the dark-tone palette for a light theme. Colours are shared by every wildcard processor.
- If the colours ever fail to line up with the text box they switch themselves off for that box (a warning appears in the browser console) and the plain box is restored.

## Node controls
- **mode**: populate (fill populated_text when you press Run; read-only but copyable) · fixed (use populated_text exactly as written) · reproduce (pick by hand: use populated_text once, then back to populate).
- **Loading an image**: the node comes back in populate mode, so it regenerates from wildcard_text. The image's exact prompt is shown in populated_text — copy it before running, or switch to **fixed** to re-create it exactly.
- **seed** connected to a node that computes it: the prompt is resolved when the node runs (populated_text updates then; a warning is logged).
- **runs**: queue X runs; the next run is queued only after the previous finishes; cancel / interrupt / error stops the series (a workflow-tab switch mid-run also stops it). Outputs `run_index` (1..X) and `runs_remaining`. Don't also set ComfyUI's batch count (they multiply).
- **Reset cycles & counter**: restart this node's bags, orders, histories and countdown from the beginning. Stopping a series does NOT reset cycles.
- **switches**: switch values (see Switches).
- **Refresh Wildcards**: reload wildcard files from disk.
- **Search wildcards…** (v0.8.9): a popup that filters the whole wildcard list as you type (every word must match somewhere in the name or folder). Click to tick several entries, Enter inserts the ticked ones (or the highlighted one) into wildcard_text; ticks stay while you change the search. The right side previews the first lines of the highlighted wildcard. YAML wildcards are listed under their file's folder.
- **Preview prompt** (v0.8.9): resolves the current wildcard_text with the node's seed and switches without running the workflow. **Roll again** uses the next seed. It never advances the node's `^` / `-::` / `+::` cycles.
- The **switches** box keeps a small fixed height, so making the node taller gives the room to the prompt boxes.
- **latent / width / height** inputs: see Aspect ratio.

## Example — 28 expressions, one each, in list order, then stop
- `emotions.txt`, one expression per line (a short one ships in `wildcard_examples/`; put your own in `umbrae_nodes/wildcards/` to replace it)
- `wildcard_text = {-::__emotions__}`
- `runs = 28`
- Press **Reset cycles & counter**, then Run once.
