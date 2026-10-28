// index.js — wildcard processor [umbrae]: syntax highlighting in the wildcard_text box.
//
// Registers the Settings section "Umbrae > WildcardHighlight" (on/off, feature
// toggles, option-colour mode, one colour picker per category, dark / light
// reset) and hooks the highlighter onto the wildcard_text box of every
// UmbraeWildcardProcessor node. Defaults = dark palette, alternate options.
// The colours only change how text is drawn; the prompt text is never touched.

import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { attachHighlight, setAllEnabled, setConfig } from "./attach.js";

const NODE_TYPE = "UmbraeWildcardProcessor";
const ID = "Umbrae.WildcardHighlight";

// key, label, dark, light (same hues; light tones for dark mode, dark tones for light mode)
const COLORS = [
    ["tag",     "Tag name  __hair__",                     "#5fb3ff", "#0b5cad"],
    ["tagd",    "Tag underscores  __",                    "#3d7fb8", "#6a9fd0"],
    ["var",     "Variable  {@x}  @x",                     "#ffa94d", "#b85c00"],
    ["varo",    "Variable override  {@!x}",               "#ffd43b", "#8a6d00"],
    ["sw",      "Switch  {&x}",                           "#b794f6", "#6b3fc4"],
    ["swo",     "Switch override  {&!x}",                 "#e879f9", "#a21caf"],
    ["pin",     "Pin  {&=2:x}",                           "#8c9eff", "#3949ab"],
    ["repl",    "Replacement  {!find=replace}",           "#a3e635", "#4d7c0f"],
    ["prot",    "Protected text  {-= =-}",                "#2dd4bf", "#0f766e"],
    ["aspect",  "Aspect  [[aspect]]  [ratio]",            "#4ade80", "#15803d"],
    ["weight",  "Weights, counts, prefixes  2::  2$$  -::", "#22d3ee", "#0e7490"],
    ["sep",     "Separators  |  ^",                       "#9aa0ad", "#5b6270"],
    ["esc",     "Escapes  \\{  \\n",                      "#c9b8a0", "#7a6650"],
    ["comment", "Comment lines  #",                       "#7d8f78", "#6b7d66"],
    ["br0",     "Plain group braces, level 1",            "#f2c14e", "#a16207"],
    ["br1",     "Plain group braces, level 2",            "#67e8f9", "#0e7490"],
    ["br2",     "Plain group braces, level 3",            "#c4b5fd", "#6d28d9"],
    ["br3",     "Plain group braces, level 4",            "#86efac", "#15803d"],
    ["opt1",    "Options: second colour (alternate / cycle / tint)", "#9fb4d9", "#3b5a99"],
    ["opt2",    "Options: third colour (cycle / tint)",   "#d9c89f", "#8a6d1f"],
    ["opt3",    "Options: fourth colour (cycle)",         "#a8d9a0", "#2f7a2a"],
    ["bad",     "Warnings (unmatched bracket, unknown tag)", "#ff5c5c", "#d32f2f"],
];

const settings = () => app.ui?.settings;
function getSetting(id, fallback) {
    try {
        const v = settings()?.getSettingValue(id);
        return v === undefined || v === null ? fallback : v;
    } catch (e) {
        return fallback;
    }
}

// ── colours -> CSS variables ───────────────────────────────────────────────
function applyColors() {
    let el = document.getElementById("uwh-vars");
    if (!el) {
        el = document.createElement("style");
        el.id = "uwh-vars";
        document.head.appendChild(el);
    }
    const lines = COLORS.map(([key, , dark]) => `--uwh-${key}:${getSetting(`${ID}.Color.${key}`, dark)};`);
    el.textContent = `:root{${lines.join("")}}`;
    setConfig({});
}

// ── unknown-tag check: ask the server how the engine resolves each tag ──────
const tagCache = new Map();      // name -> { state: bool|undefined, t }
const tagQueue = new Set();
let tagTimer = 0;
const TAG_TTL = 20000;

function tagState(name) {
    if (!getSetting(`${ID}.WarnUnknownTag`, true)) return undefined;
    const e = tagCache.get(name);
    const now = Date.now();
    if (e && now - e.t < TAG_TTL) return e.state;
    if (!tagQueue.has(name) && !(e && e.pending)) {
        tagQueue.add(name);
        if (!tagTimer) tagTimer = setTimeout(flushTags, 350);
    }
    return e ? e.state : undefined;       // stale answer until the new one arrives
}

async function flushTags() {
    tagTimer = 0;
    const names = [...tagQueue].slice(0, 12);
    for (const n of names) tagQueue.delete(n);
    await Promise.all(names.map(async (name) => {
        const prev = tagCache.get(name);
        tagCache.set(name, { state: prev?.state, t: Date.now(), pending: true });
        try {
            const res = await api.fetchApi(`/umbrae/wildcards/preview_entry?tag=${encodeURIComponent(name)}&n=1`);
            const data = await res.json();
            tagCache.set(name, { state: typeof data?.found === "boolean" ? data.found : undefined, t: Date.now() });
        } catch (e) {
            tagCache.set(name, { state: undefined, t: Date.now() });
        }
    }));
    setConfig({});
    if (tagQueue.size) tagTimer = setTimeout(flushTags, 350);
}

// ── settings ───────────────────────────────────────────────────────────────
function readConfig() {
    setConfig({
        optMode: getSetting(`${ID}.OptionMode`, "alternate"),
        closeColor: getSetting(`${ID}.CloseColor`, true),
        pair: getSetting(`${ID}.PairOnCaret`, true),
        same: getSetting(`${ID}.SameName`, true),
        tagState,
    });
}

let resetting = false;
async function applyPreset(which) {
    resetting = true;
    try {
        const idx = which === "light" ? 3 : 2;
        for (const c of COLORS) await settings().setSettingValue(`${ID}.Color.${c[0]}`, c[idx]);
    } finally {
        resetting = false;
    }
    applyColors();
}

function registerSettings() {
    const s = settings();
    if (!s?.addSetting) return;
    const add = (def) => { try { s.addSetting(def); } catch (e) { console.warn("[umbrae wildcard highlight] setting failed", def.id, e); } };

    add({ id: `${ID}.Enabled`, name: "Wildcard processor: colour the wildcard text", type: "boolean", defaultValue: true,
          tooltip: "Syntax colours in the wildcard_text box of the wildcard processor. Off = plain text box.",
          onChange: (v) => setAllEnabled(v !== false) });
    add({ id: `${ID}.CloseColor`, name: "Colour closing brackets like their opener", type: "boolean", defaultValue: true,
          tooltip: "Off = only the opening bracket is coloured; a closer lights up when the caret touches it.",
          onChange: readConfig });
    add({ id: `${ID}.PairOnCaret`, name: "Highlight the partner bracket when the caret touches one", type: "boolean", defaultValue: true,
          onChange: readConfig });
    add({ id: `${ID}.SameName`, name: "Highlight every use of the tag / variable / switch under the caret", type: "boolean", defaultValue: true,
          onChange: readConfig });
    add({ id: `${ID}.WarnUnknownTag`, name: "Flag __tags__ that match no wildcard", type: "boolean", defaultValue: true,
          tooltip: "Asks the server how each tag resolves (same rules as the engine). Press Refresh Wildcards after adding files; the check follows within a few seconds.",
          onChange: readConfig });
    add({ id: `${ID}.OptionMode`, name: "Colour of the options inside a group", type: "combo", defaultValue: "alternate",
          options: ["alternate", "none", "cycle", "tint"],
          tooltip: "alternate: every second option; cycle: four colours in turn; tint: background washes; none.",
          onChange: readConfig });
    add({ id: `${ID}.ResetTo`, name: "Reset all colours to…", type: "combo", defaultValue: "-", options: ["-", "dark", "light"],
          tooltip: "Pick dark or light to put every colour below back to that preset.",
          onChange: async (v) => {
              if (resetting || !v || v === "-") return;
              await applyPreset(v);
              try { await settings().setSettingValue(`${ID}.ResetTo`, "-"); } catch (e) { /* ignore */ }
          } });
    for (const [key, label, dark] of COLORS) {
        add({ id: `${ID}.Color.${key}`, name: label, type: "color", defaultValue: dark,
              onChange: () => { if (!resetting) applyColors(); } });
    }
}

// ── nodes ──────────────────────────────────────────────────────────────────
if (!window.__umbraeWildcardHighlightUI) {
window.__umbraeWildcardHighlightUI = true;
app.registerExtension({
    name: "umbrae.wildcard_highlight",

    async setup() {
        registerSettings();
        applyColors();
        readConfig();
    },

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            try {
                const wt = this.widgets?.find((w) => w.name === "wildcard_text");
                const ta = wt?.inputEl;
                if (ta) attachHighlight(ta, { enabled: getSetting(`${ID}.Enabled`, true) !== false });
            } catch (e) {
                console.warn("[umbrae wildcard highlight] could not attach", e);
            }
            return r;
        };
        const onRemoved = nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved = function () {
            try {
                const wt = this.widgets?.find((w) => w.name === "wildcard_text");
                wt?.inputEl?._uwh?.destroy();
            } catch (e) { /* ignore */ }
            return onRemoved ? onRemoved.apply(this, arguments) : undefined;
        };
    },
});
}
