// umbrae_wildcards.js — umbrae_nodes v0.8.9
//
// Frontend for "wildcard processor [umbrae]" (UmbraeWildcardProcessor).
// Ported in part from Impact Pack's impact-pack.js / common.js (GPL-3.0).
//
//  * populated_text is read-only (still selectable / copyable) while mode = populate
//  * "Select to add Wildcard" picker appends __name__ to wildcard_text
//  * Refresh Wildcards button (reload files from disk)
//  * Reset cycles & counter button (clears this node's ^ bags, -:: cursors,
//    +:: histories and its runs countdown)
//  * runs countdown: when a run finishes SUCCESSFULLY and the node reported
//    runs remaining, queue the next run. Cancel / interrupt / error ends the
//    series. If the active workflow tab changed mid-run, the series stops
//    instead of queueing the wrong workflow.
//  * v0.8.9: "Search wildcards" popup (filter as you type, tick several, line preview),
//    "Preview prompt" button (resolve the prompt without running), and a capped
//    height for the switches box so the prompt boxes keep the room.
//  * v0.8.7: aspect inputs (latent / width / height) are sockets only - no
//    widgets, so saved widgets_values keep their old positions.

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_TYPE = "UmbraeWildcardProcessor";
const LABEL = "Select the Wildcard to add to the text";

let wildcardList = [];            // picker labels (folder-grouped)
const labelToTag = new Map();     // label -> __tag__ inserted into the prompt

function toast(severity, summary, detail, life = 3000) {
    try {
        app.extensionManager.toast.add({ severity, summary, detail, life });
    } catch (e) {
        console.log(`[umbrae wildcards] ${summary}: ${detail}`);
    }
}

async function loadWildcards() {
    try {
        const res = await api.fetchApi("/umbrae/wildcards/list");
        const data = await res.json();
        labelToTag.clear();
        previewCache.clear();
        if (Array.isArray(data?.entries)) {
            wildcardList = data.entries.map((e) => { labelToTag.set(e.label, e.tag); return e.label; });
        } else {
            wildcardList = Array.isArray(data?.data) ? data.data : [];
        }
    } catch (e) {
        console.error("[umbrae wildcards] list failed", e);
    }
}

function getWidget(node, name) {
    return node.widgets?.find((w) => w.name === name);
}

function updatePopulatedState(node) {
    const pop = getWidget(node, "populated_text");
    const mode = getWidget(node, "mode");
    if (pop?.inputEl) {
        // readOnly (not disabled): browsers block selecting/copying disabled text
        pop.inputEl.disabled = false;
        pop.inputEl.readOnly = mode?.value === "populate";
    }
}

function findNode(nodeId) {
    const id = String(nodeId);
    if (id.includes(":")) return null;          // subgraph-internal id: not addressable here
    return app.graph?.getNodeById?.(Number(id)) ?? null;
}

// queue-time populate pushes the populated text / mode back to the widgets
api.addEventListener("umbrae-wildcard-feedback", (event) => {
    const d = event.detail || {};
    const node = findNode(d.node_id);
    if (!node) return;
    const w = getWidget(node, d.widget_name);
    if (w) {
        w.value = d.value;
        if (d.widget_name === "mode") updatePopulatedState(node);
        node.setDirtyCanvas?.(true, true);
    }
});

// ── runs countdown ──────────────────────────────────────────────────────────
const pendingRequeue = new Map();   // prompt_id -> workflow key at time of request

function activeWorkflowKey() {
    try {
        const wf = app.extensionManager?.workflow?.activeWorkflow;
        return wf ? (wf.path ?? wf.key ?? wf.filename ?? null) : null;
    } catch (e) {
        return null;
    }
}

async function endSeries(reason) {
    pendingRequeue.clear();
    try {
        await api.fetchApi("/umbrae/wildcards/series_end", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ node_id: null }),
        });
    } catch (e) { /* server gone - nothing to end */ }
    if (reason) toast("warn", "Wildcard runs stopped", reason, 4000);
}

api.addEventListener("executed", (event) => {
    const d = event.detail || {};
    const info = d.output?.umbrae_runs;
    if (!Array.isArray(info) || !d.prompt_id) return;
    const remaining = Number(info[0]);
    if (remaining > 0) {
        pendingRequeue.set(d.prompt_id, activeWorkflowKey());
    }
});

api.addEventListener("execution_success", async (event) => {
    const id = event.detail?.prompt_id;
    if (!id || !pendingRequeue.has(id)) return;
    const wfKey = pendingRequeue.get(id);
    pendingRequeue.delete(id);
    const nowKey = activeWorkflowKey();
    if (wfKey !== null && nowKey !== null && wfKey !== nowKey) {
        await endSeries("The active workflow tab changed - the series was stopped instead of queueing a different workflow.");
        return;
    }
    try {
        await app.queuePrompt(0, 1);
    } catch (e) {
        console.error("[umbrae wildcards] re-queue failed", e);
        await endSeries("Could not queue the next run.");
    }
});

api.addEventListener("execution_interrupted", () => endSeries(null));
api.addEventListener("execution_error", () => endSeries(null));

// ── search popup / prompt preview (v0.8.9) ──────────────────────────────────
const UWC_CSS = `
.uwc-overlay{position:fixed;inset:0;z-index:100000;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center}
.uwc-panel{width:min(980px,94vw);height:min(640px,88vh);display:flex;flex-direction:column;gap:8px;padding:12px;box-sizing:border-box;
  background:var(--comfy-menu-bg,#242424);color:var(--input-text,#ddd);border:1px solid var(--border-color,#555);border-radius:8px;font:13px system-ui,sans-serif}
.uwc-panel.small{height:auto;max-height:88vh;width:min(720px,94vw)}
.uwc-head{display:flex;align-items:center;gap:10px}
.uwc-head b{font-size:14px}.uwc-head .uwc-count{margin-left:auto;opacity:.7;font-size:12px}
.uwc-input{width:100%;box-sizing:border-box;padding:8px 10px;font-size:14px;background:var(--comfy-input-bg,#1a1a1a);color:var(--input-text,#ddd);
  border:1px solid var(--border-color,#555);border-radius:6px;outline:none}
.uwc-input:focus{border-color:#7a86ff}
.uwc-body{flex:1;min-height:0;display:flex;gap:10px}
.uwc-list{flex:1.15;min-width:0;overflow:auto;border:1px solid var(--border-color,#555);border-radius:6px;background:var(--comfy-input-bg,#1a1a1a)}
.uwc-row{display:flex;align-items:center;gap:8px;padding:3px 8px;cursor:pointer;white-space:nowrap;border-bottom:1px solid rgba(128,128,128,.12)}
.uwc-row.hi{background:rgba(122,134,255,.28)}.uwc-row.sel .uwc-name{font-weight:600}
.uwc-row .uwc-dir{opacity:.55;overflow:hidden;text-overflow:ellipsis}.uwc-row .uwc-name{flex:none}
.uwc-row input{margin:0;flex:none}
.uwc-prev{flex:1;min-width:0;overflow:auto;border:1px solid var(--border-color,#555);border-radius:6px;padding:8px;background:var(--comfy-input-bg,#1a1a1a)}
.uwc-prev h4{margin:0 0 6px;font-size:12px;font-weight:600;word-break:break-all}
.uwc-prev .uwc-meta{opacity:.65;font-size:11px;margin-bottom:6px}
.uwc-prev div.l{padding:2px 0;border-bottom:1px dotted rgba(128,128,128,.25);font-size:12px;line-height:1.35;word-break:break-word}
.uwc-foot{display:flex;align-items:center;gap:8px}
.uwc-foot .uwc-hint{opacity:.6;font-size:11px;flex:1}
.uwc-btn{padding:6px 12px;border-radius:6px;border:1px solid var(--border-color,#555);background:var(--comfy-input-bg,#333);color:var(--input-text,#ddd);cursor:pointer;font-size:13px}
.uwc-btn:hover{filter:brightness(1.25)}.uwc-btn.primary{background:#4a56d8;border-color:#4a56d8;color:#fff}
.uwc-out{width:100%;box-sizing:border-box;min-height:160px;max-height:55vh;resize:vertical;padding:8px;background:var(--comfy-input-bg,#1a1a1a);color:var(--input-text,#ddd);
  border:1px solid var(--border-color,#555);border-radius:6px;font:13px/1.4 system-ui,sans-serif}
`;

function uwcStyle() {
    if (document.getElementById("uwc-style")) return;
    const st = document.createElement("style");
    st.id = "uwc-style";
    st.textContent = UWC_CSS;
    document.head.appendChild(st);
}

function h(tag, props = {}, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
        if (k === "class") e.className = v;
        else if (k === "text") e.textContent = v;
        else e.setAttribute(k, v);
    }
    for (const c of kids) if (c) e.append(c);
    return e;
}

function uwcOverlay(small) {
    uwcStyle();
    const overlay = h("div", { class: "uwc-overlay" });
    const panel = h("div", { class: "uwc-panel" + (small ? " small" : "") });
    overlay.append(panel);
    const close = () => { overlay.remove(); document.removeEventListener("keydown", onKey, true); };
    const onKey = (ev) => { if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); close(); } };
    document.addEventListener("keydown", onKey, true);
    overlay.addEventListener("mousedown", (ev) => { if (ev.target === overlay) close(); });
    document.body.append(overlay);
    return { overlay, panel, close };
}

// every word of the query must appear in the label (any order, any case)
function uwcFilter(labels, query) {
    const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) return labels;
    const hits = [];
    for (const label of labels) {
        const low = label.toLowerCase();
        let ok = true, bonus = 0;
        const base = low.slice(Math.max(low.lastIndexOf("/"), low.lastIndexOf("›")) + 1);
        for (const t of terms) {
            if (!low.includes(t)) { ok = false; break; }
            if (base.includes(t)) bonus++;
        }
        if (ok) hits.push([bonus, label]);
    }
    hits.sort((a, b) => b[0] - a[0]);          // stable: matches in the file name first, folder order kept
    return hits.map((x) => x[1]);
}

const previewCache = new Map();
async function fetchEntryPreview(tag) {
    if (previewCache.has(tag)) return previewCache.get(tag);
    const res = await api.fetchApi(`/umbrae/wildcards/preview_entry?tag=${encodeURIComponent(tag)}&n=60`);
    const data = await res.json();
    previewCache.set(tag, data);
    return data;
}

function openSearchPopup(onInsert) {
    if (document.querySelector(".uwc-overlay")) return;
    const { panel, close, overlay } = uwcOverlay(false);
    const input = h("input", { class: "uwc-input", type: "text", placeholder: "Search wildcards - several words narrow it down (e.g. fabric colors)", spellcheck: "false" });
    const count = h("span", { class: "uwc-count" });
    const list = h("div", { class: "uwc-list" });
    const prev = h("div", { class: "uwc-prev" });
    const hint = h("span", { class: "uwc-hint", text: "Click ticks an entry · Enter inserts the ticked ones (or the highlighted one) · Ctrl+Enter ticks · Esc closes" });
    const bClear = h("button", { class: "uwc-btn", text: "Clear ticks" });
    const bClose = h("button", { class: "uwc-btn", text: "Close" });
    const bInsert = h("button", { class: "uwc-btn primary", text: "Insert" });
    panel.append(h("div", { class: "uwc-head" }, h("b", { text: "Search wildcards" }), count), input,
        h("div", { class: "uwc-body" }, list, prev), h("div", { class: "uwc-foot" }, hint, bClear, bClose, bInsert));

    const MAX_ROWS = 400;
    const selected = new Map();          // label -> true, in tick order
    let filtered = wildcardList, hi = 0, previewToken = 0;

    function render() {
        filtered = uwcFilter(wildcardList, input.value);
        if (hi >= filtered.length) hi = Math.max(0, filtered.length - 1);
        count.textContent = `${filtered.length} of ${wildcardList.length}` + (filtered.length > MAX_ROWS ? ` (showing ${MAX_ROWS})` : "");
        list.textContent = "";
        const frag = document.createDocumentFragment();
        filtered.slice(0, MAX_ROWS).forEach((label, i) => {
            const cut = Math.max(label.lastIndexOf("/"), label.lastIndexOf("›"));
            const cb = h("input", { type: "checkbox" });
            cb.checked = selected.has(label);
            const row = h("div", { class: "uwc-row" + (i === hi ? " hi" : "") + (selected.has(label) ? " sel" : "") },
                cb, h("span", { class: "uwc-dir", text: cut >= 0 ? label.slice(0, cut + 1) : "" }),
                h("span", { class: "uwc-name", text: label.slice(cut + 1) }));
            row.title = labelToTag.get(label) ?? label;
            row.addEventListener("click", () => { hi = i; toggle(label); });
            row.addEventListener("mouseenter", () => { if (hi !== i) { setHi(i); } });
            frag.append(row);
        });
        list.append(frag);
        bInsert.textContent = selected.size ? `Insert ${selected.size}` : "Insert";
        showPreview();
    }

    function setHi(i) {
        const rows = list.children;
        rows[hi]?.classList.remove("hi");
        hi = i;
        rows[hi]?.classList.add("hi");
        showPreview();
    }

    function toggle(label) {
        if (selected.has(label)) selected.delete(label); else selected.set(label, true);
        const rows = list.children, i = filtered.indexOf(label);
        const row = i >= 0 ? rows[i] : null;
        if (row) {
            row.classList.toggle("sel", selected.has(label));
            row.querySelector("input").checked = selected.has(label);
        }
        bInsert.textContent = selected.size ? `Insert ${selected.size}` : "Insert";
    }

    let previewTimer = null;
    function showPreview() {
        clearTimeout(previewTimer);
        previewTimer = setTimeout(async () => {
            const label = filtered[hi];
            prev.textContent = "";
            if (!label) { prev.append(h("div", { class: "uwc-meta", text: "No match." })); return; }
            const tag = labelToTag.get(label) ?? `__${label}__`;
            const token = ++previewToken;
            prev.append(h("div", { class: "uwc-meta", text: "Loading…" }));
            let data;
            try { data = await fetchEntryPreview(tag); } catch (e) { data = null; }
            if (token !== previewToken) return;
            prev.textContent = "";
            if (!data || !data.found) { prev.append(h("div", { class: "uwc-meta", text: "No preview available." })); return; }
            prev.append(h("h4", { text: tag }),
                h("div", { class: "uwc-meta", text: `${data.count} line${data.count === 1 ? "" : "s"}` + (data.source ? ` · from ${data.source}` : "") + (data.count > data.lines.length ? ` · first ${data.lines.length} shown` : "") }));
            for (const l of data.lines) prev.append(h("div", { class: "l", text: l }));
        }, 90);
    }

    function insert() {
        let labels = [...selected.keys()];
        if (!labels.length && filtered[hi]) labels = [filtered[hi]];
        if (!labels.length) return;
        onInsert(labels.map((l) => labelToTag.get(l) ?? l));
        close();
    }

    input.addEventListener("input", () => { hi = 0; render(); list.scrollTop = 0; });
    input.addEventListener("keydown", (ev) => {
        if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
            ev.preventDefault();
            const n = Math.min(filtered.length, MAX_ROWS);
            if (!n) return;
            setHi(Math.max(0, Math.min(n - 1, hi + (ev.key === "ArrowDown" ? 1 : -1))));
            list.children[hi]?.scrollIntoView({ block: "nearest" });
        } else if (ev.key === "Enter") {
            ev.preventDefault();
            if (ev.ctrlKey || ev.metaKey) { if (filtered[hi]) toggle(filtered[hi]); } else insert();
        }
    });
    bClear.addEventListener("click", () => { selected.clear(); render(); input.focus(); });
    bClose.addEventListener("click", close);
    bInsert.addEventListener("click", insert);
    render();
    setTimeout(() => input.focus(), 0);
}

async function openPromptPreview(node, wt) {
    if (document.querySelector(".uwc-overlay")) return;
    const { panel, close } = uwcOverlay(true);
    const out = h("textarea", { class: "uwc-out", readonly: "readonly" });
    const note = h("span", { class: "uwc-hint" });
    const bAgain = h("button", { class: "uwc-btn", text: "Roll again" });
    const bCopy = h("button", { class: "uwc-btn", text: "Copy" });
    const bClose = h("button", { class: "uwc-btn primary", text: "Close" });
    panel.append(h("div", { class: "uwc-head" }, h("b", { text: "Prompt preview" })), out,
        h("div", { class: "uwc-foot" }, note, bAgain, bCopy, bClose));
    const seedW = getWidget(node, "seed"), swW = getWidget(node, "switches");
    let offset = 0;
    async function run() {
        out.value = "…";
        try {
            const res = await api.fetchApi("/umbrae/wildcards/preview_text", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text: wt?.value ?? "", seed: (Number(seedW?.value) || 0) + offset,
                                       switches: swW?.value ?? "", node_id: String(node.id) }),
            });
            const d = await res.json();
            out.value = d.status === "ok" ? d.text : `Error: ${d.error ?? "preview failed"}`;
            note.textContent = d.status === "ok"
                ? (offset ? `seed + ${offset}` : "using the node's seed") + " · cycles (^ -:: +::) are not advanced"
                : "";
        } catch (e) {
            out.value = "Could not reach the server.";
        }
    }
    bAgain.addEventListener("click", () => { offset += 1; run(); });
    bCopy.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(out.value); bCopy.textContent = "Copied"; setTimeout(() => (bCopy.textContent = "Copy"), 1200); }
        catch (e) { out.select(); }
    });
    bClose.addEventListener("click", close);
    run();
}

// cap the switches box so a tall node leaves its room to the prompt boxes
function capSwitchesHeight(node, minH = 38, maxH = 76) {
    const sw = getWidget(node, "switches");
    if (!sw) return;
    try {
        sw.options = sw.options || {};
        sw.options.getMinHeight = () => minH;
        sw.options.getMaxHeight = () => maxH;
        sw.computeLayoutSize = () => ({ minHeight: minH, maxHeight: maxH, minWidth: 0 });
        if (sw.inputEl) sw.inputEl.style.resize = "none";
    } catch (e) { /* older frontend: box keeps its default sizing */ }
}

// ── node UI ─────────────────────────────────────────────────────────────────
app.registerExtension({
    name: "umbrae.WildcardProcessor",

    async setup() {
        await loadWildcards();
    },

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            const node = this;

            const wt = getWidget(node, "wildcard_text");
            const pop = getWidget(node, "populated_text");
            if (wt?.inputEl) wt.inputEl.placeholder = "Wildcard Prompt (User input)";
            if (pop?.inputEl) pop.inputEl.placeholder = "Populated Prompt (Will be generated automatically)";

            // mode -> populated_text read-only
            const mode = getWidget(node, "mode");
            if (mode) {
                const cb = mode.callback;
                mode.callback = function () {
                    const res = cb ? cb.apply(this, arguments) : undefined;
                    updatePopulatedState(node);
                    return res;
                };
            }
            updatePopulatedState(node);

            // wildcard picker: dynamic list, appends to wildcard_text, always shows/serializes the label
            const pick = getWidget(node, "Select to add Wildcard");
            if (pick) {
                try {
                    Object.defineProperty(pick.options, "values", {
                        get: () => [LABEL, ...wildcardList],
                        set: () => {},
                        configurable: true,
                    });
                } catch (e) { /* frontend without configurable options - list stays static */ }
                const pickCb = pick.callback;
                pick.callback = function (value) {
                    const res = pickCb ? pickCb.apply(this, arguments) : undefined;
                    if (value && value !== LABEL && wt) {
                        wt.value = (wt.value ? wt.value + ", " : "") + (labelToTag.get(value) ?? value);
                    }
                    pick.value = LABEL;
                    node.setDirtyCanvas?.(true, true);
                    return res;
                };
                pick.serializeValue = () => LABEL;
            }

            capSwitchesHeight(node);
            node.addWidget("button", "Search wildcards…", null, () => {
                openSearchPopup((tags) => {
                    if (!wt) return;
                    wt.value = (wt.value ? wt.value + ", " : "") + tags.join(", ");
                    node.setDirtyCanvas?.(true, true);
                });
            });
            node.addWidget("button", "Preview prompt", null, () => openPromptPreview(node, wt));

            node.addWidget("button", "Refresh Wildcards", null, async () => {
                try {
                    const res = await api.fetchApi("/umbrae/wildcards/refresh");
                    const info = await res.json();
                    await loadWildcards();
                    toast("info", "Wildcards refreshed",
                        `${info.count} wildcards${info.on_demand_mode ? " (on-demand mode)" : ""}`);
                } catch (e) {
                    console.error("[umbrae wildcards] refresh failed", e);
                    toast("error", "Refresh failed", "Wildcard list could not be refreshed.", 5000);
                }
            });

            node.addWidget("button", "Reset cycles & counter", null, async () => {
                try {
                    const res = await api.fetchApi("/umbrae/wildcards/reset", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ node_id: String(node.id) }),
                    });
                    const info = await res.json();
                    toast("info", "Reset",
                        `Cleared ${info.cycles_cleared} cycle/history state(s) and ${info.series_cleared} countdown(s). Next run starts from the beginning.`);
                } catch (e) {
                    console.error("[umbrae wildcards] reset failed", e);
                    toast("error", "Reset failed", "Could not reach the server.", 5000);
                }
            });

            return r;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const r = onConfigure ? onConfigure.apply(this, arguments) : undefined;
            const pick = getWidget(this, "Select to add Wildcard");
            if (pick) pick.value = LABEL;
            setTimeout(() => updatePopulatedState(this), 0);
            return r;
        };
    },
});
