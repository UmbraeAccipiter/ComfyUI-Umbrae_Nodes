// umbrae_wildcards.js — umbrae_nodes v0.8.5
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

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const NODE_TYPE = "UmbraeWildcardProcessor";
const LABEL = "Select the Wildcard to add to the text";

let wildcardList = [];

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
        wildcardList = Array.isArray(data?.data) ? data.data : [];
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
                        wt.value = (wt.value ? wt.value + ", " : "") + value;
                    }
                    pick.value = LABEL;
                    node.setDirtyCanvas?.(true, true);
                    return res;
                };
                pick.serializeValue = () => LABEL;
            }

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
