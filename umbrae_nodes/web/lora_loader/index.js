// web/lora_loader/index.js — umbrae_nodes v0.9.3
// "lora loader [umbrae]" (UmbraeLoraLoader): the node face. Rows of
// [switch] [name ▾] [strength] ([clip strength]) [i], a band with Add LoRA,
// all on/off and the gear. State lives in the hidden `state` widget (state.js);
// the picker, info panel and settings are overlays (picker.js, info.js,
// settings.js); the server side is modules/lora_loader/.
import { app } from "../../../scripts/app.js";
import { applyNodeColors } from "../umbrae_theme.js";
import { h, shield, ensureStyles, closeAllOverlays, displayName, folderOf, copyText } from "./ui.js";
import { STATE_WIDGET, MIN_STRENGTH, MAX_STRENGTH, readState, writeState, addRow, removeRow, duplicateRow, moveRow, patchRow,
         rowOf, setAllOn, countOn, roundStrength, graphDirty } from "./state.js";
import { listLoras, hasLora, loraInfo } from "./api.js";
import { openPicker } from "./picker.js";
import { openInfo, autoTick } from "./info.js";
import { openSettings } from "./settings.js";

const NODE_TYPE = "UmbraeLoraLoader";
const MIN_W = 320, DEFAULT_W = 360;
const PAD = 8, BAND_H = 28, ROW_H = 26, ROW_GAP = 4, EMPTY_H = 30;

function widget(node, name) { return node.widgets?.find((w) => w.name === name); }
function hideWidget(w) {
    if (!w) return;
    w.origComputeSize = w.origComputeSize ?? w.computeSize;
    w.computeSize = () => [0, -4];
    w.hidden = true;
    if (w.element) w.element.style.display = "none";
    if (w.inputEl) w.inputEl.style.display = "none";
}

function contentHeight(st) {
    const n = st.loras.length;
    return PAD + BAND_H + (n ? n * ROW_H + (n - 1) * ROW_GAP : EMPTY_H) + PAD;
}

// ── row menu ─────────────────────────────────────────────────────────────────
let _menu = null;
function closeMenu() { if (_menu) { _menu.remove(); _menu = null; } }
function openMenu(x, y, items) {
    closeMenu();
    const m = shield(h("div", { class: "ud-root ull-menu" }));
    for (const it of items) {
        if (it === "-") { m.append(h("hr")); continue; }
        m.append(h("div", { class: it.disabled ? "dis" : "", text: it.label, onclick: () => { closeMenu(); it.action(); } }));
    }
    m.style.left = x + "px"; m.style.top = y + "px";
    document.body.append(m);
    _menu = m;
    const r = m.getBoundingClientRect();
    if (r.right > innerWidth) m.style.left = Math.max(0, innerWidth - r.width - 4) + "px";
    if (r.bottom > innerHeight) m.style.top = Math.max(0, innerHeight - r.height - 4) + "px";
    setTimeout(() => document.addEventListener("mousedown", onDoc, { capture: true, once: true }), 0);
    function onDoc(e) { if (!m.contains(e.target)) closeMenu(); }
}

// ── render ───────────────────────────────────────────────────────────────────
function strengthBox(node, row, which, step) {
    const val = row[which];
    const input = h("input", { type: "text", value: Number(val).toFixed(2), title: which === "sc" ? "Clip strength" : "Strength — type a value or use the arrows / wheel" });
    const commit = () => { const v = parseFloat(input.value); patchRow(node, row.id, { [which]: Number.isFinite(v) ? v : val }); refreshAll(node, false); };
    input.addEventListener("change", commit);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { commit(); input.blur(); } if (e.key === "ArrowUp") { e.preventDefault(); nudge(step); } if (e.key === "ArrowDown") { e.preventDefault(); nudge(-step); } });
    input.addEventListener("wheel", (e) => { if (document.activeElement !== input) return; e.preventDefault(); nudge(e.deltaY < 0 ? step : -step); }, { passive: false });
    const nudge = (d) => { const cur = rowOf(node, row.id)?.[which] ?? val; patchRow(node, row.id, { [which]: Math.max(MIN_STRENGTH, Math.min(MAX_STRENGTH, roundStrength(cur + d))) }); refreshAll(node, false); };
    return h("div", { class: "ull-w" + (which === "sc" ? " clip" : "") }, input,
        h("div", { class: "ull-wspin" }, h("button", { text: "▲", tabindex: "-1", onclick: () => nudge(step) }), h("button", { text: "▼", tabindex: "-1", onclick: () => nudge(-step) })));
}

function render(node) {
    const root = node._ull?.root;
    if (!root) return;
    const st = readState(node);
    root.replaceChildren();

    const add = h("button", { class: "ull-add", text: "＋ Add LoRA", disabled: st.loras.length >= 64, onclick: () => {
        const id = addRow(node);
        refreshAll(node, true);
        if (id) pickFor(node, id);
    } });
    const on = countOn(st), total = st.loras.length;
    const all = h("div", { class: "ull-all", title: "Turn every LoRA on or off", onclick: () => { setAllOn(node, !(total && on === total)); refreshAll(node, false); } },
        h("span", { class: "ull-sw" + (total && on === total ? " on" : "") }), h("span", { text: total ? `${on} / ${total} on` : "no LoRAs" }));
    const gear = h("div", { class: "ull-gear", text: "⚙", title: "Settings (strength defaults, trigger separator, Civitai / Hugging Face keys)", onclick: () => openSettings(node, (s) => refreshAll(node, s)) });
    root.append(h("div", { class: "ull-band" }, add, all, gear));

    if (!st.loras.length) { root.append(h("div", { class: "ull-empty", text: "no LoRAs yet — click ＋ Add LoRA" })); return; }
    const rows = h("div", { class: "ull-rows" });
    for (const row of st.loras) {
        const missing = row.name ? hasLora(row.name) === false : false;
        const sw = h("span", { class: "ull-sw" + (row.on ? " on" : ""), title: row.on ? "On — click to turn off" : "Off — click to turn on", onclick: () => { patchRow(node, row.id, { on: !row.on }); refreshAll(node, false); } });
        const name = h("div", { class: "ull-name" + (row.name ? "" : " empty") + (missing ? " missing" : ""),
            title: missing ? row.name + " — file not found (moved or renamed?). This row is skipped; pick it again." : (row.name || "Pick a LoRA"),
            onclick: () => pickFor(node, row.id) },
            folderOf(row.name) ? h("span", { class: "fld", text: folderOf(row.name) + "/" }) : null,
            h("span", { class: "nm", text: row.name ? displayName(row.name, st.hideExt) : "pick a LoRA…" }),
            h("span", { class: "car", text: "▾" }));
        const info = h("button", { class: "ull-i" + (row.triggers.length ? " has" : ""), text: "i", title: row.triggers.length ? "Info · ticked: " + row.triggers.join(", ") : "Info, pictures and trigger words", disabled: !row.name,
            onclick: () => openInfo(node, row.id, (s) => refreshAll(node, s)) });
        const el = h("div", { class: "ull-row" + (row.on ? "" : " off") }, sw, name, strengthBox(node, row, "sm", st.step));
        if (!st.linkStrength) el.append(strengthBox(node, row, "sc", st.step));
        el.append(info);
        el.addEventListener("contextmenu", (e) => {
            e.preventDefault(); e.stopPropagation();
            const i = st.loras.findIndex((r) => r.id === row.id);
            openMenu(e.clientX, e.clientY, [
                { label: "Move up", disabled: i === 0, action: () => { moveRow(node, row.id, -1); refreshAll(node, false); } },
                { label: "Move down", disabled: i === st.loras.length - 1, action: () => { moveRow(node, row.id, 1); refreshAll(node, false); } },
                { label: "Duplicate", action: () => { duplicateRow(node, row.id); refreshAll(node, true); } },
                "-",
                { label: "Copy file name", disabled: !row.name, action: () => copyText(row.name) },
                { label: "Copy ticked trigger words", disabled: !row.triggers.length, action: () => copyText(row.triggers.join(st.sep)) },
                "-",
                { label: "Remove", action: () => { removeRow(node, row.id); refreshAll(node, true); } },
            ]);
        });
        rows.append(el);
    }
    root.append(rows);
}

function pickFor(node, id) {
    const row = rowOf(node, id);
    if (!row) return;
    openPicker({
        current: row.name,
        onPick: async (name) => {
            if (name === rowOf(node, id)?.name) return;
            patchRow(node, id, { name });
            refreshAll(node, false);
            const r = await loraInfo(name);
            if (r.ok && autoTick(node, id, r.info)) refreshAll(node, false);
        },
    });
}

function fit(node) {
    const st = readState(node);
    const ch = contentHeight(st);
    if (node._ull?.widget) node._ull.widget._ullH = ch;
    const w = Math.max(node.size?.[0] || DEFAULT_W, MIN_W);
    let hgt;
    try { hgt = node.computeSize?.()?.[1]; } catch (_) { hgt = null; }
    if (!hgt || hgt < ch) hgt = ch + 70;
    if (typeof node.setSize === "function") node.setSize([w, hgt]); else node.size = [w, hgt];
    graphDirty();
}

function refreshAll(node, structural) {
    render(node);
    if (structural) fit(node);
    graphDirty();
}

// ── node setup ───────────────────────────────────────────────────────────────
function setupNode(node) {
    ensureStyles();
    applyNodeColors(node);
    hideWidget(widget(node, STATE_WIDGET));
    const root = shield(h("div", { class: "ud-root ull-root" }));
    const w = node.addDOMWidget("lora_ui", "custom", root, {
        getValue: () => "", setValue: () => {},
        getMinHeight: () => w?._ullH ?? contentHeight(readState(node)),
        serialize: false,
    });
    w._ullH = contentHeight(readState(node));
    w.computeSize = (width) => [width ?? node.size?.[0] ?? DEFAULT_W, w._ullH];
    w.computeLayoutSize = () => ({ minHeight: w._ullH, minWidth: MIN_W });
    if (w.element) { w.element.style.width = "100%"; w.element.style.boxSizing = "border-box"; }
    node._ull = { root, widget: w };
    if (!Array.isArray(node.size)) node.size = [DEFAULT_W, 0];
    node.size[0] = Math.max(node.size[0] || 0, DEFAULT_W);
    queueMicrotask(() => { writeState(node, readState(node)); refreshAll(node, true); });
    listLoras().then(() => { if (node._ull) render(node); });
}

app.registerExtension({
    name: "umbrae.loraLoader",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;
        const proto = nodeType.prototype;
        if (proto._ullPatched) return;
        proto._ullPatched = true;

        const origCreated = proto.onNodeCreated;
        proto.onNodeCreated = function () {
            origCreated?.apply(this, arguments);
            setupNode(this);
        };
        const origConfigure = proto.onConfigure;
        proto.onConfigure = function (info) {
            const r = origConfigure?.apply(this, arguments);
            if (this._ull) refreshAll(this, true);
            return r;
        };
        const origResize = proto.onResize;
        proto.onResize = function (size) {
            if (size[0] < MIN_W) size[0] = MIN_W;
            if (this._ull) {
                let hgt = null;
                try { hgt = this.computeSize?.()?.[1]; } catch (_) {}
                if (hgt) size[1] = hgt;
            }
            return origResize?.apply(this, arguments);
        };
        const origRemoved = proto.onRemoved;
        proto.onRemoved = function () {
            closeAllOverlays(); closeMenu();
            this._ull = null;
            return origRemoved?.apply(this, arguments);
        };
        const origMenu = proto.getExtraMenuOptions;
        proto.getExtraMenuOptions = function (_, options) {
            const r = origMenu?.apply(this, arguments);
            options.push(
                { content: "⚙ lora loader settings", callback: () => openSettings(this, (s) => refreshAll(this, s)) },
                { content: "Copy all ticked trigger words", callback: () => { const st = readState(this); copyText(st.loras.filter((e) => e.on).flatMap((e) => e.triggers).join(st.sep)); } },
            );
            return r;
        };
    },
});
