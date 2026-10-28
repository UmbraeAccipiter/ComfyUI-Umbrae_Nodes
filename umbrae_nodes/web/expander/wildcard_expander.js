// web/expander/wildcard_expander.js — umbrae_nodes v0.9.0
// Panel for "wildcard expander [umbrae]" (UmbraeWildcardExpander).
//
// One prompt -> N prompts over a seed plan. The Draws panel shows every line the
// engine drew for the selected prompt (nested as the wildcards nested) and each
// draw can be rerolled, pinned, picked from its list, skipped or replaced by
// your text. Edits are keyed by wildcard key + occurrence, stored in the hidden
// `edits` widget (JSON), so they apply to every prompt and to the real run.
// Collection, Pins, Switches and Seed plan / Output sit behind collapsed panels.
//
// Native widgets are hidden and mirrored here; their values are what the
// workflow saves and what the Python node receives.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { injectTheme, applyNodeColors } from "../umbrae_theme.js";
import { createSection } from "../umbrae_components.js";

const NODE_TYPE = "UmbraeWildcardExpander";
const FEEDBACK_EVENT = "umbrae-expander-feedback";
const DEFAULT_SIZE = [980, 720];
const MIN_SIZE = [720, 480];
const DEBOUNCE_MS = 350;
const STYLE_ID = "umbrae-expander-styles";
const PAGE = 40;
const HIDDEN = ["text", "seed", "count", "mode", "fixed_text", "switches", "edits", "settings"];
const DEFAULT_SETTINGS = { seed_mode: "sequential", seed_step: 1, dedupe: false, tidy: true, joiner: "\n" };

// ── styles (ud tokens + panel specifics) ─────────────────────────────────────
function ensureStyles() {
    injectTheme();
    if (document.getElementById(STYLE_ID)) return;
    const s = document.createElement("style");
    s.id = STYLE_ID;
    s.textContent = `
.uwx-root { display:flex; flex-direction:column; gap:8px; height:100%; min-height:0; overflow:hidden; padding:6px 8px; font-size:11px; }
.uwx-root * { box-sizing:border-box; }
.uwx-bar { display:flex; align-items:center; gap:6px; flex-wrap:wrap; flex:none; }
.uwx-bar .ud-label { white-space:nowrap; }
.uwx-btn { background:var(--ud-inset); border:1px solid var(--ud-border); color:var(--ud-text); border-radius:4px; padding:3px 8px; font-size:11px; cursor:pointer; line-height:1.3; white-space:nowrap; }
.uwx-btn:hover { background:var(--ud-inset-hover); border-color:var(--ud-accent); }
.uwx-btn.primary { background:var(--ud-accent); border-color:var(--ud-accent); color:#fff; font-weight:600; }
.uwx-btn.primary:hover { background:var(--ud-accent-hover); }
.uwx-btn:disabled { opacity:.5; cursor:default; }
.uwx-btn.tiny { padding:1px 5px; font-size:10px; }
.uwx-in { background:var(--ud-inset); border:1px solid var(--ud-border); color:var(--ud-text); border-radius:4px; padding:3px 6px; font-size:11px; outline:none; }
.uwx-in:focus { border-color:var(--ud-accent); }
.uwx-in.seed { width:150px; color:var(--ud-accent); font-weight:600; }
.uwx-in.count { width:52px; text-align:center; color:var(--ud-accent); font-weight:600; }
.uwx-sel { background:var(--ud-inset); border:1px solid var(--ud-border); color:var(--ud-text); border-radius:4px; padding:2px 4px; font-size:11px; outline:none; }
.uwx-status { color:var(--ud-text-dim); font-size:10px; margin-left:auto; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:40%; }
.uwx-status.err { color:#e08080; }
.uwx-cols { display:flex; gap:10px; flex:1; min-height:0; }
.uwx-col { display:flex; flex-direction:column; gap:8px; flex:1; min-width:0; min-height:0; }
.uwx-col > .ud-section { flex:none; min-height:0; }
.uwx-col > .ud-section.grow { flex:1; display:flex; flex-direction:column; }
.uwx-col > .ud-section.grow > .ud-section-body { flex:1; min-height:0; display:flex; flex-direction:column; }
.uwx-col > .ud-section.grow.collapsed { flex:none; }
.uwx-head { display:flex; align-items:center; gap:6px; flex:none; }
.uwx-head .spacer { flex:1; }
.uwx-scroll { flex:1; min-height:0; overflow:auto; border:1px solid var(--ud-border); border-radius:4px; background:var(--ud-inset); padding:3px; }
.uwx-scroll.short { flex:none; max-height:180px; }
textarea.uwx-ta { width:100%; background:var(--ud-inset); border:1px solid var(--ud-border); color:var(--ud-text); border-radius:4px; padding:5px 7px; font-size:11.5px; font-family:var(--ud-font); line-height:1.4; outline:none; resize:vertical; min-height:60px; }
textarea.uwx-ta:focus { border-color:var(--ud-accent); }
textarea.uwx-ta.prompt { height:110px; }
textarea.uwx-ta.fixed { flex:1; min-height:120px; resize:none; }
textarea.uwx-ta.sw { height:56px; min-height:40px; }
.uwx-row { display:flex; align-items:center; gap:4px; padding:2px 4px; border-radius:3px; min-width:0; }
.uwx-row:hover { background:var(--ud-inset-hover); }
.uwx-row.pinned { box-shadow:inset 2px 0 0 var(--ud-accent); }
.uwx-row.skipped .uwx-txt { text-decoration:line-through; opacity:.55; }
.uwx-row.custom { box-shadow:inset 2px 0 0 #c9a44a; }
.uwx-row.detached { opacity:.6; }
.uwx-tog { width:12px; flex:none; color:var(--ud-text-dim); cursor:pointer; user-select:none; font-size:9px; text-align:center; }
.uwx-key { color:var(--ud-accent); flex:none; max-width:34%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; cursor:default; }
.uwx-n { color:var(--ud-text-dim); font-size:9px; flex:none; }
.uwx-txt { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:var(--ud-text); }
.uwx-acts { display:flex; gap:2px; flex:none; opacity:0; }
.uwx-row:hover .uwx-acts, .uwx-row.pinned .uwx-acts, .uwx-row.skipped .uwx-acts, .uwx-row.custom .uwx-acts { opacity:1; }
.uwx-acts button { background:transparent; border:1px solid transparent; color:var(--ud-text-dim); border-radius:3px; width:20px; height:18px; font-size:11px; cursor:pointer; padding:0; line-height:1; }
.uwx-acts button:hover { border-color:var(--ud-border); color:var(--ud-text); background:var(--ud-inset); }
.uwx-acts button.on { color:var(--ud-accent); }
.uwx-kids { margin-left:14px; border-left:1px dashed var(--ud-divider); padding-left:2px; }
.uwx-prompt { padding:4px 6px; border-radius:3px; cursor:pointer; display:flex; gap:6px; align-items:flex-start; }
.uwx-prompt:hover { background:var(--ud-inset-hover); }
.uwx-prompt.focus { background:#2d3744; box-shadow:inset 2px 0 0 var(--ud-accent); }
.uwx-prompt .idx { color:var(--ud-accent); font-weight:600; flex:none; width:26px; font-size:10px; padding-top:1px; }
.uwx-prompt .seed { color:var(--ud-text-dim); font-size:9px; flex:none; width:120px; overflow:hidden; text-overflow:ellipsis; padding-top:2px; }
.uwx-prompt .body { flex:1; min-width:0; white-space:pre-wrap; word-break:break-word; line-height:1.35; display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden; }
.uwx-prompt.focus .body { -webkit-line-clamp:unset; }
.uwx-prompt .cp { flex:none; }
.uwx-tree .uwx-row { cursor:default; }
.uwx-tree .uwx-key { color:var(--ud-text); max-width:none; flex:1; cursor:pointer; }
.uwx-tree .folder > .uwx-key { color:var(--ud-accent); }
.uwx-tree .cnt { color:var(--ud-text-dim); font-size:9px; flex:none; }
.uwx-entries { margin:2px 0 4px 14px; border:1px solid var(--ud-divider); border-radius:3px; padding:3px; background:#1b1b1b; }
.uwx-entries .uwx-row { padding:1px 3px; }
.uwx-entries .w { color:var(--ud-text-dim); font-size:9px; flex:none; width:22px; text-align:right; }
.uwx-note { color:#c9a44a; font-size:10px; }
.uwx-hint { color:var(--ud-text-dim); font-size:10px; padding:4px; line-height:1.4; }
.uwx-pin { display:flex; gap:6px; align-items:center; padding:2px 4px; }
.uwx-pin .k { color:var(--ud-accent); flex:none; max-width:40%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.uwx-pin .v { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.uwx-pin.unused { opacity:.5; }
.uwx-grid { display:grid; grid-template-columns:auto 1fr; gap:5px 10px; align-items:center; }
.uwx-grid > .uwx-btn, .uwx-grid > .uwx-in { justify-self:start; min-width:64px; }
.uwx-grid > .uwx-sel { justify-self:start; min-width:120px; }
.uwx-pills { display:flex; gap:3px; }
.uwx-pills .uwx-btn.on { background:var(--ud-accent); border-color:var(--ud-accent); color:#fff; }
.uwx-overlay { position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:10000; display:flex; align-items:center; justify-content:center; }
.uwx-pop { width:min(720px, 92vw); max-height:84vh; display:flex; flex-direction:column; gap:6px; background:#262626; border:1px solid var(--ud-border); border-radius:6px; padding:10px; color:var(--ud-text); font-family:var(--ud-font); font-size:11px; box-shadow:0 8px 30px #000a; }
.uwx-pop .uwx-scroll { min-height:200px; max-height:50vh; }
.uwx-pop h3 { margin:0; font-size:11px; color:var(--ud-accent); text-transform:uppercase; letter-spacing:.07em; display:flex; gap:8px; align-items:center; }
.uwx-pop h3 .sub { color:var(--ud-text-dim); text-transform:none; letter-spacing:0; font-weight:400; }
.uwx-pop .uwx-row { cursor:pointer; }
.uwx-pop .uwx-row.cur { background:#2d3744; }
.uwx-chk { display:flex; align-items:center; gap:4px; color:var(--ud-text-dim); cursor:pointer; user-select:none; }
`;
    document.head.appendChild(s);
}

// ── small helpers ────────────────────────────────────────────────────────────
function h(tag, props = {}, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
        if (k === "class") el.className = v;
        else if (k === "text") el.textContent = v;
        else if (k === "title") el.title = v;
        else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
        else if (v !== undefined && v !== null) el.setAttribute(k, v);
    }
    for (const kid of kids) if (kid != null) el.append(kid);
    return el;
}
function btn(label, title, onClick, cls = "") {
    const b = h("button", { class: `uwx-btn ${cls}`.trim(), text: label, title, type: "button" });
    b.addEventListener("click", (e) => { e.stopPropagation(); onClick(e); });
    return b;
}
// keep LiteGraph's canvas from eating keys / drags inside the panel
function shield(el) {
    for (const ev of ["mousedown", "pointerdown", "keydown", "keyup", "wheel", "dblclick", "contextmenu"]) {
        el.addEventListener(ev, (e) => e.stopPropagation());
    }
    return el;
}
function widget(node, name) { return node.widgets?.find((w) => w.name === name); }
function hideWidget(w) {
    if (!w) return;
    w.origComputeSize = w.origComputeSize ?? w.computeSize;
    w.computeSize = () => [0, -4];
    w.hidden = true;
    if (w.element) w.element.style.display = "none";
    if (w.inputEl) w.inputEl.style.display = "none";
    for (const l of w.linkedWidgets || []) hideWidget(l);
}
function seedControl(node) {
    const s = widget(node, "seed");
    return s?.linkedWidgets?.find((w) => String(w.name).startsWith("control_after_generate"))
        || node.widgets?.find((w) => String(w.name).startsWith("control_after_generate"));
}
function shortKey(key) {
    const parts = String(key).replace(/\/$/, "").split("/");
    const tail = parts.slice(-2).join("/");
    return (parts.length > 2 ? "…/" : "") + tail + (key.endsWith("/") ? "/" : "");
}
function parseJSON(str, fallback) { try { const v = JSON.parse(str); return v ?? fallback; } catch (_) { return fallback; } }
function sameEdit(a, key, n) { return a.key === key && ((a.n ?? null) === (n ?? null)); }
function toast(severity, summary, detail) {
    try { app.extensionManager?.toast?.add({ severity, summary, detail, life: 3000 }); } catch (_) {}
}
async function copyText(text, el) {
    try { await navigator.clipboard.writeText(text); if (el) { const t = el.textContent; el.textContent = "✓"; setTimeout(() => (el.textContent = t), 900); } }
    catch (_) { toast("warn", "Copy failed", "Clipboard not available."); }
}
async function fetchJSON(url, body) {
    const opts = body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : undefined;
    const res = await api.fetchApi(url, opts);
    return res.json();
}

// ── collection cache (shared by all expander nodes) ──────────────────────────
let treeCache = null, treePromise = null;
async function loadTree(force = false) {
    if (force) { treeCache = null; treePromise = null; }
    if (treeCache) return treeCache;
    if (!treePromise) {
        treePromise = fetchJSON("/umbrae/expander/tree").then((d) => (treeCache = d?.roots ? d : { roots: [], keys: 0 }))
            .catch(() => (treeCache = { roots: [], keys: 0 }));
    }
    return treePromise;
}

// ── line picker popup ────────────────────────────────────────────────────────
// onPick({mode, idx, text, every})
function openPicker({ key, current, every, onPick, onClear }) {
    if (document.querySelector(".uwx-overlay")) return;
    const overlay = h("div", { class: "uwx-overlay" });
    const pop = shield(h("div", { class: "uwx-pop" }));
    const close = () => overlay.remove();
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
    const title = h("h3", { text: `__${key}__` }, h("span", { class: "sub" }));
    const search = h("input", { class: "uwx-in", placeholder: "filter lines… (every word must match)", style: "flex:1" });
    const custom = h("input", { class: "uwx-in", placeholder: "or type your own text for this draw", style: "flex:1" });
    const everyChk = h("input", { type: "checkbox" }); everyChk.checked = !!every;
    const everyLbl = h("label", { class: "uwx-chk", title: "Apply to every occurrence of this wildcard in the prompt, not just this one" }, everyChk, "every occurrence");
    const list = h("div", { class: "uwx-scroll" });
    const more = btn("Load more", "", () => load(false));
    const foot = h("div", { class: "uwx-head" },
        everyLbl, h("span", { class: "spacer" }),
        btn("Skip", "Remove this draw from the prompt", () => { onPick({ mode: "skip", every: everyChk.checked }); close(); }),
        btn("Clear", "Back to the random draw", () => { onClear?.(); close(); }),
        btn("Close", "", close));
    const useCustom = btn("Use text", "Insert this text instead of a line", () => {
        if (!custom.value.trim()) return;
        onPick({ mode: "text", text: custom.value, every: everyChk.checked }); close();
    }, "primary");
    custom.addEventListener("keydown", (e) => { if (e.key === "Enter") useCustom.click(); });
    pop.append(title, h("div", { class: "uwx-head" }, search), h("div", { class: "uwx-head" }, custom, useCustom), list, foot);
    overlay.append(pop);
    document.body.append(overlay);

    let offset = 0, total = 0, count = 0, timer = null;
    async function load(reset) {
        if (reset) { offset = 0; list.replaceChildren(); }
        const q = search.value.trim();
        const d = await fetchJSON(`/umbrae/expander/entries?tag=${encodeURIComponent(key)}&offset=${offset}&limit=${PAGE}&q=${encodeURIComponent(q)}`);
        if (!d?.found) { list.replaceChildren(h("div", { class: "uwx-hint", text: "no lines found for this tag" })); return; }
        total = d.total; count = d.count;
        title.querySelector(".sub").textContent = `${d.kind} · ${count} lines${q ? ` · ${total} match` : ""}`;
        for (const ln of d.lines) {
            const row = h("div", { class: "uwx-row" + (ln.i === current ? " cur" : "") },
                h("span", { class: "uwx-n", text: String(ln.i + 1) }),
                h("span", { class: "uwx-txt", text: ln.text, title: ln.text }),
                ln.w !== 1 ? h("span", { class: "uwx-n", text: `×${ln.w}` }) : null);
            row.addEventListener("click", () => { onPick({ mode: "line", idx: ln.i, text: ln.text, every: everyChk.checked }); close(); });
            list.append(row);
        }
        offset += d.lines.length;
        more.remove();
        if (offset < total) list.append(more);
        if (!d.lines.length && reset) list.append(h("div", { class: "uwx-hint", text: "nothing matches" }));
    }
    search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => load(true), 200); });
    pop.addEventListener("keydown", (e) => { if (e.key === "Escape") close(); });
    load(true);
    search.focus();
}

// ── the node panel ───────────────────────────────────────────────────────────
function setupNode(node) {
    ensureStyles();
    applyNodeColors(node);
    for (const name of HIDDEN) hideWidget(widget(node, name));
    hideWidget(seedControl(node));

    const W = (name) => widget(node, name);
    const getW = (name, dflt) => { const w = W(name); return w ? (w.value ?? dflt) : dflt; };
    const setW = (name, v) => { const w = W(name); if (w && w.value !== v) { w.value = v; } };

    // UI-only state (persisted with the workflow in node.properties)
    const prop = () => (node.properties ??= {}, node.properties.uwxState ??= { collapsed: { collection: true, pins: true, switches: true, settings: true }, focus: 0 });
    const ui = prop();

    let result = null;            // last /expand answer
    let edits = parseJSON(getW("edits", ""), {}).pins ?? parseJSON(getW("edits", ""), []);
    if (!Array.isArray(edits)) edits = [];
    let settings = { ...DEFAULT_SETTINGS, ...parseJSON(getW("settings", ""), {}) };
    let timer = null, inflight = false, queued = false, lastRunPrompts = null;

    const saveEdits = () => { setW("edits", edits.length ? JSON.stringify({ pins: edits }) : ""); };
    const saveSettings = () => { setW("settings", JSON.stringify(settings)); };

    const root = shield(h("div", { class: "ud-root uwx-root" }));

    // ── toolbar ──
    const expandBtn = btn("Expand", "Expand now (also happens automatically while you edit)", () => expand(true), "primary");
    const seedIn = h("input", { class: "uwx-in seed", title: "First seed of the batch", inputmode: "numeric" });
    const diceBtn = btn("🎲", "Random seed", () => { const v = Math.floor(Math.random() * 2 ** 48); seedIn.value = String(v); commitSeed(); });
    const stepBtn = btn("+1", "Next seed", () => { seedIn.value = String((Number(seedIn.value) || 0) + 1); commitSeed(); });
    const afterSel = h("select", { class: "uwx-sel", title: "What happens to the seed after each run (ComfyUI's control_after_generate)" });
    for (const v of ["fixed", "increment", "decrement", "randomize"]) afterSel.append(h("option", { value: v, text: v }));
    const countIn = h("input", { class: "uwx-in count", title: "How many prompts", inputmode: "numeric" });
    const modePills = h("div", { class: "uwx-pills" });
    const modeBtns = {};
    for (const m of ["populate", "fixed"]) {
        modeBtns[m] = btn(m, m === "populate" ? "Expand the prompt on every run" : "Use the prompts in the Prompts box exactly as written (separate them with a --- line)",
            () => { setW("mode", m); W("mode")?.callback?.(m); syncMode(); });
        modePills.append(modeBtns[m]);
    }
    const refreshBtn = btn("↻", "Reload wildcard files from disk", async () => {
        refreshBtn.disabled = true;
        try { await api.fetchApi("/umbrae/wildcards/refresh"); await loadTree(true); renderTree(); expand(true); toast("success", "Wildcards reloaded"); }
        catch (_) { toast("error", "Reload failed"); }
        refreshBtn.disabled = false;
    });
    const status = h("span", { class: "uwx-status" });
    root.append(h("div", { class: "uwx-bar" },
        expandBtn, h("span", { class: "ud-label", text: "seed" }), seedIn, diceBtn, stepBtn, afterSel,
        h("span", { class: "ud-label", text: "count" }), countIn, modePills, refreshBtn, status));

    function commitSeed() {
        const v = Math.max(0, Math.floor(Number(seedIn.value) || 0));
        seedIn.value = String(v); setW("seed", v); W("seed")?.callback?.(v); schedule();
    }
    seedIn.addEventListener("change", commitSeed);
    seedIn.addEventListener("keydown", (e) => { if (e.key === "Enter") seedIn.blur(); });
    countIn.addEventListener("change", () => {
        const v = Math.max(1, Math.min(100, Math.floor(Number(countIn.value) || 1)));
        countIn.value = String(v); setW("count", v); W("count")?.callback?.(v); schedule();
    });
    afterSel.addEventListener("change", () => { const c = seedControl(node); if (c) { c.value = afterSel.value; c.callback?.(afterSel.value); } });

    // ── columns ──
    const left = h("div", { class: "uwx-col" }), right = h("div", { class: "uwx-col" });
    root.append(h("div", { class: "uwx-cols" }, left, right));

    function section(title, key, opts = {}) {
        const sec = createSection(title, {
            collapsible: true, collapsed: !!ui.collapsed?.[key], tooltip: opts.tooltip,
            onToggle: (open) => { (ui.collapsed ??= {})[key] = !open; opts.onToggle?.(open); },
        });
        if (opts.grow) sec.el.classList.add("grow");
        return sec;
    }

    // Prompt
    const promptSec = section("Prompt", "prompt", { tooltip: "Wildcard prompt: __tags__, {a|b}, switches, variables …" });
    const promptTA = h("textarea", { class: "uwx-ta prompt", placeholder: "Wildcard prompt…  e.g.  __example/portrait/portrait__, colors __example/colors__", spellcheck: "false" });
    promptTA.addEventListener("input", () => { setW("text", promptTA.value); schedule(); });
    promptSec.body.append(promptTA);
    left.append(promptSec.el);

    // Draws
    const drawsSec = section("Draws", "draws", { grow: true, tooltip: "What every wildcard became for the selected prompt. Hover a row for its tools." });
    const drawsHead = h("div", { class: "uwx-head" });
    const drawsTitle = h("span", { class: "ud-label" });
    const expandAll = btn("⊞", "Expand all", () => setAllOpen(true), "tiny");
    const collapseAll = btn("⊟", "Collapse all", () => setAllOpen(false), "tiny");
    drawsHead.append(drawsTitle, h("span", { class: "spacer" }),
        h("span", { class: "uwx-hint", text: "⟲ reroll · 📌 pin · ☰ pick / text · ⏭ skip · ✕ clear" }), expandAll, collapseAll);
    const drawsList = h("div", { class: "uwx-scroll" });
    drawsSec.body.append(drawsHead, drawsList);
    left.append(drawsSec.el);

    // Pins
    const pinsSec = section("Pins & edits", "pins", { tooltip: "Every pinned, skipped or replaced draw. They apply to all prompts and to the run." });
    const pinsList = h("div", { class: "uwx-scroll short" });
    const pinsHead = h("div", { class: "uwx-head" },
        h("span", { class: "spacer" }),
        btn("Copy JSON", "Copy the edits as JSON", (e) => copyText(JSON.stringify({ pins: edits }, null, 1), e.currentTarget), "tiny"),
        btn("Paste JSON", "Replace the edits with JSON from the clipboard", async () => {
            try { const t = await navigator.clipboard.readText(); const d = parseJSON(t, null); const arr = Array.isArray(d) ? d : d?.pins;
                if (!Array.isArray(arr)) throw 0; edits = arr; saveEdits(); renderPins(); schedule(); }
            catch (_) { toast("warn", "Paste failed", "Clipboard does not hold an edits JSON."); }
        }, "tiny"),
        btn("Clear all", "Remove every edit", () => { if (!edits.length) return; edits = []; saveEdits(); renderPins(); schedule(); }, "tiny"));
    pinsSec.body.append(pinsHead, pinsList);
    left.append(pinsSec.el);

    // Switches
    const swSec = section("Switches", "switches", { tooltip: "Switch values, e.g.  gend=2, hair=4  — override {&name=...} definitions" });
    const swTA = h("textarea", { class: "uwx-ta sw", placeholder: "gend=2, hair=4", spellcheck: "false" });
    swTA.addEventListener("input", () => { setW("switches", swTA.value); schedule(); });
    swSec.body.append(swTA);
    left.append(swSec.el);

    // Prompts
    const promptsSec = section("Prompts", "prompts", { grow: true, tooltip: "The batch. Click a prompt to see its draws." });
    const promptsHead = h("div", { class: "uwx-head" });
    const promptsTitle = h("span", { class: "ud-label" });
    const copyAllBtn = btn("Copy all", "Copy every prompt (joined with the Output separator)", (e) => {
        const ps = currentPrompts(); if (ps.length) copyText(ps.join(settings.joiner), e.currentTarget);
    }, "tiny");
    const toFixedBtn = btn("→ fixed", "Keep these exact prompts: copy them into the fixed box and switch to fixed mode", () => {
        const ps = currentPrompts(); if (!ps.length) return;
        fixedTA.value = ps.join("\n---\n"); setW("fixed_text", fixedTA.value);
        setW("mode", "fixed"); W("mode")?.callback?.("fixed"); syncMode();
    }, "tiny");
    promptsHead.append(promptsTitle, h("span", { class: "spacer" }), copyAllBtn, toFixedBtn);
    const promptsList = h("div", { class: "uwx-scroll" });
    const fixedTA = h("textarea", { class: "uwx-ta fixed", placeholder: "fixed mode: one prompt per block, separated by a line that is only ---", spellcheck: "false" });
    fixedTA.style.display = "none";
    fixedTA.addEventListener("input", () => { setW("fixed_text", fixedTA.value); renderPromptsTitle(); });
    promptsSec.body.append(promptsHead, promptsList, fixedTA);
    right.append(promptsSec.el);

    // Collection
    const colSec = section("Collection", "collection", { grow: true, tooltip: "Your whole wildcard collection. Click a file to see its lines; insert tags or pin a line from here.", onToggle: (open) => { if (open) loadTree().then(renderTree); } });
    const colSearch = h("input", { class: "uwx-in", placeholder: "search wildcards… (every word must match the path)", style: "flex:1" });
    colSearch.addEventListener("input", () => { clearTimeout(colSearch._t); colSearch._t = setTimeout(renderTree, 150); });
    const colInfo = h("span", { class: "uwx-hint" });
    const treeEl = h("div", { class: "uwx-scroll uwx-tree" });
    colSec.body.append(h("div", { class: "uwx-head" }, colSearch, colInfo), treeEl);
    right.append(colSec.el);

    // Seed plan & output
    const setSec = section("Seed plan & output", "settings", { tooltip: "How the seeds of the batch are made, and how the outputs are cleaned and joined." });
    const grid = h("div", { class: "uwx-grid" });
    const modeRow = h("div", { class: "uwx-pills" });
    const seedModeBtns = {};
    for (const [v, label, tip] of [["sequential", "sequential", "seed, seed+step, seed+2·step …"], ["random", "derived", "seed, then seeds derived from it (same seed → same batch)"]]) {
        seedModeBtns[v] = btn(label, tip, () => { settings.seed_mode = v; saveSettings(); renderSettings(); schedule(); });
        modeRow.append(seedModeBtns[v]);
    }
    const stepIn = h("input", { class: "uwx-in count", title: "Seed step (sequential plan)" });
    stepIn.addEventListener("change", () => { settings.seed_step = Math.floor(Number(stepIn.value)) || 1; saveSettings(); renderSettings(); schedule(); });
    const dedupeBtn = btn("", "Drop prompts identical to an earlier one and try more seeds", () => { settings.dedupe = !settings.dedupe; saveSettings(); renderSettings(); schedule(); });
    const tidyBtn = btn("", "Collapse ', ,' and stray spaces left by skipped draws", () => { settings.tidy = !settings.tidy; saveSettings(); renderSettings(); schedule(); });
    const joinSel = h("select", { class: "uwx-sel", title: "Separator for the `joined` output and Copy all" });
    for (const [v, label] of [["\n", "new line"], ["\n\n", "blank line"], [", ", "comma"], [" | ", "pipe"], ["\n---\n", "--- line"]]) joinSel.append(h("option", { value: v, text: label }));
    joinSel.addEventListener("change", () => { settings.joiner = joinSel.value; saveSettings(); });
    grid.append(h("span", { class: "ud-label", text: "seeds" }), modeRow,
        h("span", { class: "ud-label", text: "step" }), stepIn,
        h("span", { class: "ud-label", text: "dedupe" }), dedupeBtn,
        h("span", { class: "ud-label", text: "tidy" }), tidyBtn,
        h("span", { class: "ud-label", text: "join with" }), joinSel);
    setSec.body.append(grid);
    right.append(setSec.el);

    function renderSettings() {
        for (const [v, b] of Object.entries(seedModeBtns)) b.classList.toggle("on", settings.seed_mode === v);
        stepIn.value = String(settings.seed_step ?? 1);
        stepIn.disabled = settings.seed_mode !== "sequential";
        dedupeBtn.textContent = settings.dedupe ? "on" : "off"; dedupeBtn.classList.toggle("on", !!settings.dedupe);
        tidyBtn.textContent = settings.tidy ? "on" : "off"; tidyBtn.classList.toggle("on", !!settings.tidy);
        if ([...joinSel.options].some((o) => o.value === settings.joiner)) joinSel.value = settings.joiner;
    }

    // ── data flow ──
    function currentPrompts() {
        if (getW("mode", "populate") === "fixed") return fixedTA.value.split(/^\s*---\s*$/m).map((s) => s.trim()).filter(Boolean);
        return (result?.prompts || []).map((p) => p.text);
    }
    function schedule() {
        clearTimeout(timer);
        timer = setTimeout(() => expand(false), DEBOUNCE_MS);
    }
    async function expand(manual) {
        if (getW("mode", "populate") === "fixed" && !manual) { renderAll(); return; }
        if (inflight) { queued = true; return; }
        inflight = true;
        status.textContent = "expanding…"; status.classList.remove("err");
        try {
            const d = await fetchJSON("/umbrae/expander/expand", {
                text: getW("text", ""), seed: getW("seed", 0), count: getW("count", 1),
                switches: getW("switches", ""), edits: { pins: edits }, settings, node_id: String(node.id),
            });
            if (d?.status === "ok") {
                result = d; lastRunPrompts = null;
                healEdits();
                const n = d.prompts.length;
                status.textContent = `${n} prompt${n === 1 ? "" : "s"}` + (d.notes?.length ? ` · ${d.notes.length} note${d.notes.length === 1 ? "" : "s"}` : "");
                status.title = (d.notes || []).join("\n");
            } else {
                status.textContent = d?.error || "expand failed"; status.classList.add("err"); status.title = "";
            }
        } catch (e) {
            status.textContent = "server unreachable"; status.classList.add("err");
        }
        inflight = false;
        renderAll();
        if (queued) { queued = false; expand(false); }
    }
    // pins made by reroll know only an index: remember the line text so they survive file edits
    function healEdits() {
        let changed = false;
        const visit = (nodes) => { for (const d of nodes) { const e = findEdit(d.key, d.n); if (e && e.mode === "line" && e.idx === d.idx && !e.text && d.line) { e.text = d.line; changed = true; } visit(d.children || []); } };
        for (const p of result?.prompts || []) visit(p.draws || []);
        if (changed) saveEdits();
    }
    function findEdit(key, n) { return edits.find((e) => sameEdit(e, key, n)) || edits.find((e) => e.key === key && (e.n ?? null) === null); }
    function setEdit(key, n, patch) {
        const i = edits.findIndex((e) => sameEdit(e, key, n));
        if (patch == null) { if (i >= 0) edits.splice(i, 1); }
        else if (i >= 0) edits[i] = { key, n, ...patch };
        else edits.push({ key, n, ...patch });
        saveEdits(); renderPins(); schedule();
    }
    function applyPick(key, n, pick) {
        const target = pick.every ? null : n;
        if (pick.every) edits = edits.filter((e) => e.key !== key);           // the "every" edit replaces per-occurrence ones
        else edits = edits.filter((e) => !(e.key === key && (e.n ?? null) === null)); // a per-occurrence edit replaces an "every" one
        if (pick.mode === "skip") setEdit(key, target, { mode: "skip" });
        else if (pick.mode === "text") setEdit(key, target, { mode: "text", text: pick.text });
        else setEdit(key, target, { mode: "line", idx: pick.idx, text: pick.text ?? null });
    }

    // ── render: draws ──
    const openState = () => (ui.open ??= {});
    function setAllOpen(open) { ui.allOpen = open; ui.open = {}; renderDraws(); }
    function renderDraws() {
        drawsList.replaceChildren();
        const mode = getW("mode", "populate");
        if (mode === "fixed") { drawsTitle.textContent = "fixed mode"; drawsList.append(h("div", { class: "uwx-hint", text: "Fixed mode uses the prompts exactly as written, so there are no draws to edit. Switch to populate to work with wildcards." })); return; }
        const ps = result?.prompts || [];
        if (!ps.length) { drawsTitle.textContent = ""; drawsList.append(h("div", { class: "uwx-hint", text: result ? "No wildcards drawn: the prompt has no __tags__ the engine could resolve." : "Type a prompt (or insert tags from the Collection) and the draws appear here." })); return; }
        const f = Math.min(ui.focus ?? 0, ps.length - 1); ui.focus = f;
        const p = ps[f];
        drawsTitle.textContent = `prompt #${f + 1} · seed ${p.seed}`;
        if (p.notes?.length) drawsList.append(h("div", { class: "uwx-note", text: p.notes.join(" · ") }));
        if (!p.draws?.length) { drawsList.append(h("div", { class: "uwx-hint", text: "no wildcard draws in this prompt" })); return; }
        // how often each key occurs (to show #n only when it matters)
        const freq = {};
        const cnt = (nodes) => { for (const d of nodes) { freq[d.key] = (freq[d.key] || 0) + 1; cnt(d.children || []); } };
        cnt(p.draws);
        const renderNodes = (nodes, container, depth) => {
            for (const d of nodes) {
                const e = findEdit(d.key, d.n);
                const kids = d.children || [];
                const id = `${d.key}#${d.n}@${depth}`;
                const open = openState()[id] ?? (ui.allOpen ?? true);
                const row = h("div", { class: "uwx-row" + (e ? (e.mode === "skip" ? " skipped" : e.mode === "text" ? " custom" : " pinned") : "") + (d.detached ? " detached" : "") });
                const tog = h("span", { class: "uwx-tog", text: kids.length ? (open ? "▾" : "▸") : "" });
                tog.addEventListener("click", () => { openState()[id] = !open; renderDraws(); });
                const keyEl = h("span", { class: "uwx-key", text: shortKey(d.key), title: `__${d.tag || d.key}__\nkey: ${d.key}\nline ${d.idx == null ? "?" : d.idx + 1} of ${d.count ?? "?"}` + (e?.n == null && e ? "\n(edit applies to every occurrence)" : "") });
                const nEl = h("span", { class: "uwx-n", text: freq[d.key] > 1 ? `#${d.n + 1}` : "" });
                const shown = e?.mode === "skip" ? (d.line || "(skipped)") : d.text || d.line || "";
                const txt = h("span", { class: "uwx-txt", text: shown, title: (d.line && d.line !== d.text) ? `drawn line: ${d.line}\n\nbecame: ${d.text}` : shown });
                const acts = h("div", { class: "uwx-acts" });
                const every = e ? (e.n ?? null) === null : false;
                const mk = (label, title, fn, on = false) => { const b = h("button", { text: label, title, type: "button" }); if (on) b.classList.add("on"); b.addEventListener("click", (ev) => { ev.stopPropagation(); fn(); }); return b; };
                acts.append(
                    mk("⟲", "Reroll: pin another random line of this wildcard", () => {
                        if (!d.count || d.count < 2) return;
                        let idx = d.idx; for (let t = 0; t < 8 && idx === d.idx; t++) idx = Math.floor(Math.random() * d.count);
                        applyPick(d.key, d.n, { mode: "line", idx, every });
                    }),
                    mk("📌", e?.mode === "line" ? "Unpin" : "Pin this line (keeps it in every prompt of the batch)", () => {
                        if (e?.mode === "line") setEdit(d.key, e.n ?? null, null);
                        else applyPick(d.key, d.n, { mode: "line", idx: d.idx, text: d.line, every });
                    }, e?.mode === "line"),
                    mk("☰", "Pick a line from the list, or type your own text", () => openPicker({
                        key: d.key, current: d.idx, every,
                        onPick: (pick) => applyPick(d.key, d.n, pick),
                        onClear: () => setEdit(d.key, e ? (e.n ?? null) : d.n, null),
                    }), e?.mode === "text"),
                    mk("⏭", e?.mode === "skip" ? "Unskip" : "Skip: remove this draw from the prompt", () => {
                        if (e?.mode === "skip") setEdit(d.key, e.n ?? null, null);
                        else applyPick(d.key, d.n, { mode: "skip", every });
                    }, e?.mode === "skip"),
                    mk("✕", "Clear the edit on this draw", () => { if (e) setEdit(d.key, e.n ?? null, null); }),
                );
                row.append(tog, keyEl, nEl, txt, acts);
                container.append(row);
                if (kids.length && open) {
                    const kc = h("div", { class: "uwx-kids" });
                    renderNodes(kids, kc, depth + 1);
                    container.append(kc);
                }
            }
        };
        renderNodes(p.draws, drawsList, 0);
    }

    // ── render: prompts ──
    function renderPromptsTitle() {
        const mode = getW("mode", "populate");
        if (mode === "fixed") { const n = currentPrompts().length; promptsTitle.textContent = `fixed · ${n} prompt${n === 1 ? "" : "s"}`; return; }
        const ps = result?.prompts || [];
        promptsTitle.textContent = lastRunPrompts ? `last run · ${lastRunPrompts.length}` : ps.length ? `${ps.length} prompt${ps.length === 1 ? "" : "s"}` : "";
    }
    function renderPrompts() {
        renderPromptsTitle();
        const mode = getW("mode", "populate");
        fixedTA.style.display = mode === "fixed" ? "" : "none";
        promptsList.style.display = mode === "fixed" ? "none" : "";
        if (mode === "fixed") return;
        promptsList.replaceChildren();
        const ps = lastRunPrompts || (result?.prompts || []);
        if (!ps.length) { promptsList.append(h("div", { class: "uwx-hint", text: "prompts appear here as you type" })); return; }
        ps.forEach((p, i) => {
            const row = h("div", { class: "uwx-prompt" + (i === (ui.focus ?? 0) ? " focus" : "") },
                h("span", { class: "idx", text: `#${i + 1}` }),
                h("span", { class: "seed", text: String(p.seed), title: `seed ${p.seed}` }),
                h("div", { class: "body", text: p.text || "(empty)" }));
            const cp = h("button", { class: "uwx-btn tiny cp", text: "copy", title: "Copy this prompt", type: "button" });
            cp.addEventListener("click", (e) => { e.stopPropagation(); copyText(p.text, cp); });
            row.append(cp);
            row.addEventListener("click", () => { ui.focus = i; renderPrompts(); renderDraws(); });
            promptsList.append(row);
        });
    }

    // ── render: pins ──
    function renderPins() {
        pinsList.replaceChildren();
        if (!edits.length) { pinsList.append(h("div", { class: "uwx-hint", text: "no edits — use the tools on a draw, or pin a line from the Collection" })); return; }
        const used = new Set();
        for (const p of result?.prompts || []) for (const [k, n] of p.hits || []) used.add(`${k}#${n}`);
        for (const e of edits) {
            const n = e.n ?? null;
            const isUsed = !result || used.has(`${e.key}#${n == null ? -1 : n}`);
            const val = e.mode === "skip" ? "skipped" : e.mode === "text" ? `“${e.text}”` : (e.text ? e.text : `line ${(e.idx ?? 0) + 1}`);
            const row = h("div", { class: "uwx-pin" + (isUsed ? "" : " unused"), title: isUsed ? "" : "this edit did not match any draw in the current batch" },
                h("span", { class: "k", text: shortKey(e.key) + (n == null ? " (every)" : ` #${n + 1}`), title: e.key }),
                h("span", { class: "v", text: val, title: val }),
                btn("✕", "Remove this edit", () => { edits = edits.filter((x) => x !== e); saveEdits(); renderPins(); schedule(); }, "tiny"));
            pinsList.append(row);
        }
    }

    // ── render: collection tree ──
    function insertAtCursor(text) {
        const ta = promptTA;
        const s = ta.selectionStart ?? ta.value.length, e = ta.selectionEnd ?? s;
        const before = ta.value.slice(0, s), after = ta.value.slice(e);
        const pad = before && !/\s$/.test(before) ? " " : "";
        ta.value = before + pad + text + after;
        const pos = (before + pad + text).length;
        ta.focus(); ta.setSelectionRange(pos, pos);
        setW("text", ta.value); schedule();
    }
    function renderTree() {
        if (!treeCache) { treeEl.replaceChildren(h("div", { class: "uwx-hint", text: "loading collection…" })); return; }
        treeEl.replaceChildren();
        const q = colSearch.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
        colInfo.textContent = `${treeCache.keys} wildcards`;
        const openF = (ui.treeOpen ??= {});
        const fileRow = (n, depth, showPath) => {
            const row = h("div", { class: "uwx-row file" });
            row.style.paddingLeft = `${4 + depth * 12}px`;
            const name = h("span", { class: "uwx-key", text: showPath ? n.key : n.name, title: `__${n.key}__` + (n.count != null ? `\n${n.count} lines` : "") });
            const acts = h("div", { class: "uwx-acts" });
            const mk = (label, title, fn) => { const b = h("button", { text: label, title, type: "button" }); b.addEventListener("click", (ev) => { ev.stopPropagation(); fn(); }); return b; };
            acts.append(
                mk("＋", `Insert __${n.key}__ into the prompt`, () => insertAtCursor(`__${n.key}__`)),
                mk("☰", "Browse the lines; click one to pin it for every draw of this wildcard, or insert it", () => openPicker({
                    key: n.key, current: null, every: true,
                    onPick: (pick) => { if (pick.mode === "line" && !pick.every) { insertAtCursor(pick.text); return; } applyPick(n.key, null, { ...pick, every: true }); },
                })),
            );
            row.append(h("span", { class: "uwx-tog" }), name, n.count != null ? h("span", { class: "cnt", text: String(n.count) }) : null, acts);
            name.addEventListener("click", () => toggleEntries(row, n, depth));
            return row;
        };
        const folderRow = (n, depth) => {
            const open = q.length ? true : !!openF[n.path];
            const row = h("div", { class: "uwx-row folder" });
            row.style.paddingLeft = `${4 + depth * 12}px`;
            const tog = h("span", { class: "uwx-tog", text: open ? "▾" : "▸" });
            const name = h("span", { class: "uwx-key", text: n.name + (n.kind === "yaml" ? "" : "/"), title: n.kind === "yaml" ? `YAML file: keys come from its content` : `folder ${n.path}/` });
            const acts = h("div", { class: "uwx-acts" });
            if (n.callable) {
                const b = h("button", { text: "＋", title: `Insert a folder call __${n.path}/__ (one line from every file under it)`, type: "button" });
                b.addEventListener("click", (ev) => { ev.stopPropagation(); insertAtCursor(`__${n.path}/__`); });
                acts.append(b);
            }
            row.append(tog, name, h("span", { class: "cnt", text: String(n.files) }), acts);
            row.addEventListener("click", () => { openF[n.path] = !open; renderTree(); });
            return [row, open];
        };
        const matches = (n, path) => !q.length || q.every((w) => path.includes(w));
        let shown = 0;
        const walk = (nodes, depth, container, pathPrefix) => {
            for (const n of nodes) {
                if (n.children) {
                    const path = (pathPrefix + n.name + "/").toLowerCase();
                    if (q.length) {
                        // searching: flatten - show matching files with their path
                        walk(n.children, depth, container, pathPrefix + n.name + "/");
                        continue;
                    }
                    const [row, open] = folderRow(n, depth);
                    container.append(row);
                    if (open) walk(n.children, depth + 1, container, pathPrefix + n.name + "/");
                } else {
                    const path = (pathPrefix + n.name + " " + n.key).toLowerCase();
                    if (!matches(n, path)) continue;
                    if (q.length && shown >= 400) continue;
                    shown++;
                    container.append(fileRow(n, q.length ? 0 : depth, !!q.length));
                }
            }
        };
        walk(treeCache.roots, 0, treeEl, "");
        if (q.length) colInfo.textContent = `${shown}${shown >= 400 ? "+" : ""} match`;
        if (!treeEl.children.length) treeEl.append(h("div", { class: "uwx-hint", text: q.length ? "nothing matches" : "no wildcards found — add files under umbrae_nodes/wildcards and press ↻" }));
    }
    async function toggleEntries(row, n, depth) {
        const next = row.nextElementSibling;
        if (next?.classList.contains("uwx-entries")) { next.remove(); return; }
        const box = h("div", { class: "uwx-entries" }, h("div", { class: "uwx-hint", text: "loading…" }));
        box.style.marginLeft = `${18 + depth * 12}px`;
        row.after(box);
        let offset = 0;
        const load = async () => {
            const d = await fetchJSON(`/umbrae/expander/entries?tag=${encodeURIComponent(n.key)}&offset=${offset}&limit=30`);
            if (offset === 0) box.replaceChildren();
            if (!d?.found) { box.append(h("div", { class: "uwx-hint", text: "no lines" })); return; }
            for (const ln of d.lines) {
                const r = h("div", { class: "uwx-row" }, h("span", { class: "w", text: String(ln.i + 1) }), h("span", { class: "uwx-txt", text: ln.text, title: ln.text }));
                const acts = h("div", { class: "uwx-acts" });
                const mk = (label, title, fn) => { const b = h("button", { text: label, title, type: "button" }); b.addEventListener("click", (ev) => { ev.stopPropagation(); fn(); }); return b; };
                acts.append(
                    mk("📌", `Pin: every __${n.key}__ draws this line`, () => applyPick(n.key, null, { mode: "line", idx: ln.i, text: ln.text, every: true })),
                    mk("＋", "Insert this text into the prompt", () => insertAtCursor(ln.text)),
                );
                r.append(acts); box.append(r);
            }
            offset += d.lines.length;
            box.querySelector(".more")?.remove();
            if (offset < d.count) box.append(btn(`more (${d.count - offset} left)`, "", load, "tiny more"));
        };
        load();
    }

    function syncMode() {
        const mode = getW("mode", "populate");
        for (const [m, b] of Object.entries(modeBtns)) b.classList.toggle("on", m === mode);
        renderAll();
    }
    function renderAll() { renderDraws(); renderPrompts(); renderPins(); renderSettings(); }

    // ── mirror hidden widgets -> panel (workflow load, seed control after a run) ──
    function syncFromWidgets() {
        promptTA.value = String(getW("text", "") ?? "");
        fixedTA.value = String(getW("fixed_text", "") ?? "");
        swTA.value = String(getW("switches", "") ?? "");
        seedIn.value = String(getW("seed", 0) ?? 0);
        countIn.value = String(getW("count", 1) ?? 1);
        const c = seedControl(node); if (c && c.value) afterSel.value = String(c.value);
        const raw = parseJSON(getW("edits", ""), null);
        edits = Array.isArray(raw) ? raw : Array.isArray(raw?.pins) ? raw.pins : [];
        settings = { ...DEFAULT_SETTINGS, ...parseJSON(getW("settings", ""), {}) };
        syncMode();
    }
    const poll = setInterval(() => {
        if (!root.isConnected) return;
        const sv = String(getW("seed", 0) ?? 0);
        if (document.activeElement !== seedIn && seedIn.value !== sv) { seedIn.value = sv; schedule(); }
        const c = seedControl(node); if (c && c.value && afterSel.value !== String(c.value)) afterSel.value = String(c.value);
    }, 600);

    // ── mount ──
    const chrome = () => {
        const SH = window.LiteGraph?.NODE_SLOT_HEIGHT || 20;
        const slots = Math.max(node.inputs?.length ?? 0, node.outputs?.length ?? 0);
        return slots * SH + 14;
    };
    const dom = node.addDOMWidget("uwx_ui", "div", root, {
        serialize: false, getValue: () => null, setValue: () => {},
        computeSize(width) {
            const w = width ?? node.size?.[0] ?? DEFAULT_SIZE[0];
            const hgt = Math.max(node.size?.[1] ?? DEFAULT_SIZE[1], MIN_SIZE[1]) - chrome();
            return [w, hgt];
        },
    });
    if (dom?.element) { dom.element.style.width = "100%"; dom.element.style.boxSizing = "border-box"; }
    function layout() {
        let [w, hgt] = node.size || DEFAULT_SIZE;
        if (w < MIN_SIZE[0] || hgt < MIN_SIZE[1]) {
            w = Math.max(w, MIN_SIZE[0]); hgt = Math.max(hgt, MIN_SIZE[1]);
            if (typeof node.setSize === "function") node.setSize([w, hgt]); else node.size = [w, hgt];
        }
        root.style.height = `${Math.max(300, hgt - chrome() - 30)}px`;
    }
    if (!node.size || node.size[0] < MIN_SIZE[0] || node.size[1] < MIN_SIZE[1]) {
        if (typeof node.setSize === "function") node.setSize([...DEFAULT_SIZE]); else node.size = [...DEFAULT_SIZE];
    }
    const _onResize = node.onResize;
    node.onResize = function () { const r = _onResize?.apply(this, arguments); layout(); return r; };
    const _onConfigure = node.onConfigure;
    node.onConfigure = function () { const r = _onConfigure?.apply(this, arguments); Object.assign(ui, prop()); syncFromWidgets(); layout(); schedule(); return r; };
    const _onRemoved = node.onRemoved;
    node.onRemoved = function () { clearInterval(poll); return _onRemoved?.apply(this, arguments); };

    node._uwx = {
        onRun(payload) {
            lastRunPrompts = (payload.prompts || []).map((t, i) => ({ text: t, seed: payload.seeds?.[i] }));
            renderPrompts();
            if (payload.notes?.length) toast("warn", "wildcard expander", payload.notes.join("\n"));
        },
    };

    layout();
    syncFromWidgets();
    if (!ui.collapsed?.collection) loadTree().then(renderTree);
    requestAnimationFrame(() => { layout(); if (getW("text", "")) expand(false); });
}

// ── registration ─────────────────────────────────────────────────────────────
app.registerExtension({
    name: "umbrae.WildcardExpander",
    async setup() {
        api.addEventListener(FEEDBACK_EVENT, (ev) => {
            const d = ev.detail || {};
            const node = app.graph?.getNodeById?.(Number(d.node_id)) || app.graph?._nodes?.find((n) => String(n.id) === String(d.node_id));
            node?._uwx?.onRun(d);
        });
    },
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;
        const _onc = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () { const r = _onc?.apply(this, arguments); setupNode(this); return r; };
    },
});
