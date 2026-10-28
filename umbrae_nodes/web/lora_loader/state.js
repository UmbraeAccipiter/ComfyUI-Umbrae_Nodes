// web/lora_loader/state.js — umbrae_nodes v0.9.3
// The node's state: rows + per-node preferences, kept as JSON in the hidden
// `state` widget (so the workflow saves it and Python receives it unchanged).
import { app } from "../../../scripts/app.js";

export const STATE_WIDGET = "state";
export const MAX_LORAS = 64;
export const MIN_STRENGTH = -10, MAX_STRENGTH = 10;
const DEFAULTS_KEY = "umbrae.loraLoader.defaults";

export const DEFAULT_PREFS = {
    sep: ", ",
    step: 0.05,
    defStrength: 1.0,
    linkStrength: true,
    hideExt: true,
    thumbs: true,
    cacheMode: "last",
};

let _idc = 0;
export function newId() {
    try { if (crypto?.randomUUID) return "l" + crypto.randomUUID().slice(0, 8); } catch (_) {}
    return "l" + Date.now().toString(36) + (_idc++).toString(36);
}
function num(v, d) { const f = parseFloat(v); return Number.isFinite(f) ? f : d; }
export function clampStrength(v) { return Math.max(MIN_STRENGTH, Math.min(MAX_STRENGTH, num(v, 0))); }
export function roundStrength(v) { return Math.round(clampStrength(v) * 100) / 100; }

function normRow(e, prefs) {
    if (!e || typeof e !== "object") return null;
    const sm = roundStrength(e.sm ?? e.strength ?? prefs.defStrength);
    return {
        id: typeof e.id === "string" && e.id ? e.id : newId(),
        name: typeof e.name === "string" ? e.name : "",
        on: e.on == null ? true : !!e.on,
        sm,
        sc: roundStrength(e.sc ?? sm),
        triggers: Array.isArray(e.triggers) ? e.triggers.map(String).filter((w) => w.trim()).slice(0, 64) : [],
        at: e.at === true,
    };
}
function normalize(raw) {
    const st = { version: 1, ...DEFAULT_PREFS, ...loadDefaults(), ...(raw && typeof raw === "object" ? raw : {}) };
    if (typeof st.sep !== "string") st.sep = DEFAULT_PREFS.sep;
    st.step = num(st.step, DEFAULT_PREFS.step); if (st.step <= 0) st.step = DEFAULT_PREFS.step;
    st.defStrength = roundStrength(st.defStrength);
    st.linkStrength = st.linkStrength == null ? true : !!st.linkStrength;
    st.hideExt = st.hideExt == null ? true : !!st.hideExt;
    st.thumbs = st.thumbs == null ? true : !!st.thumbs;
    st.cacheMode = ["last", "all", "none"].includes(st.cacheMode) ? st.cacheMode : "last";
    st.loras = (Array.isArray(st.loras) ? st.loras : []).map((e) => normRow(e, st)).filter(Boolean).slice(0, MAX_LORAS);
    if (st.linkStrength) st.loras.forEach((e) => { e.sc = e.sm; });
    const seen = new Set();
    for (const e of st.loras) { if (seen.has(e.id)) e.id = newId(); seen.add(e.id); }
    return st;
}

function widget(node) { return node.widgets?.find((w) => w.name === STATE_WIDGET); }

export function readState(node) {
    const w = widget(node);
    const v = w?.value;
    if (typeof v === "string" && v.trim() && v.trim() !== "{}") {
        try { return normalize(JSON.parse(v)); } catch (_) { /* fall through */ }
    }
    return normalize({});
}
export function writeState(node, state) {
    const st = normalize(state);
    const w = widget(node);
    if (w) w.value = JSON.stringify(st);
    return st;
}
export function update(node, fn) {
    const st = readState(node);
    const r = fn(st);
    if (r === false) return st;
    return writeState(node, st);
}

export function addRow(node, name = "") {
    const st = readState(node);
    if (st.loras.length >= MAX_LORAS) return null;
    const row = { id: newId(), name, on: true, sm: st.defStrength, sc: st.defStrength, triggers: [], at: false };
    st.loras.push(row);
    writeState(node, st);
    return row.id;
}
export function removeRow(node, id) { return update(node, (st) => { const i = st.loras.findIndex((e) => e.id === id); if (i < 0) return false; st.loras.splice(i, 1); }); }
export function duplicateRow(node, id) {
    return update(node, (st) => {
        const i = st.loras.findIndex((e) => e.id === id);
        if (i < 0 || st.loras.length >= MAX_LORAS) return false;
        st.loras.splice(i + 1, 0, { ...st.loras[i], id: newId(), triggers: [...st.loras[i].triggers] });
    });
}
export function moveRow(node, id, dir) {
    return update(node, (st) => {
        const i = st.loras.findIndex((e) => e.id === id), j = i + dir;
        if (i < 0 || j < 0 || j >= st.loras.length) return false;
        const [m] = st.loras.splice(i, 1); st.loras.splice(j, 0, m);
    });
}
export function patchRow(node, id, patch) {
    return update(node, (st) => {
        const e = st.loras.find((x) => x.id === id);
        if (!e) return false;
        const oldName = e.name;
        Object.assign(e, patch, { id: e.id });
        if (patch.sm != null) e.sm = roundStrength(patch.sm);
        if (patch.sc != null) e.sc = roundStrength(patch.sc);
        if (patch.name != null && patch.name !== oldName) { e.triggers = []; e.at = false; }
        if (st.linkStrength && patch.sm != null && patch.sc == null) e.sc = e.sm;
    });
}
export function rowOf(node, id) { return readState(node).loras.find((e) => e.id === id) || null; }
export function setAllOn(node, on) { return update(node, (st) => { st.loras.forEach((e) => { e.on = !!on; }); }); }
export function countOn(st) { return st.loras.reduce((a, e) => a + (e.on ? 1 : 0), 0); }

export function setPrefs(node, prefs) {
    return update(node, (st) => { for (const k of Object.keys(DEFAULT_PREFS)) if (prefs[k] !== undefined) st[k] = prefs[k]; });
}

// defaults for NEW nodes, kept in the browser
export function loadDefaults() {
    try {
        const raw = localStorage.getItem(DEFAULTS_KEY);
        const obj = raw ? JSON.parse(raw) : null;
        return obj && typeof obj === "object" ? obj : {};
    } catch (_) { return {}; }
}
export function saveDefaults(prefs) {
    try {
        const keep = {};
        for (const k of Object.keys(DEFAULT_PREFS)) if (prefs[k] !== undefined) keep[k] = prefs[k];
        localStorage.setItem(DEFAULTS_KEY, JSON.stringify(keep));
        return true;
    } catch (_) { return false; }
}

export function graphDirty() { try { app.graph?.setDirtyCanvas(true, true); } catch (_) {} }
