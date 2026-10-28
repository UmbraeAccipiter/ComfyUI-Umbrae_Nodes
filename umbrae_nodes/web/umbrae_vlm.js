import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// load vlm / llm (hf) [umbrae]: refresh the `model` dropdown from `external_root`
// through /umbrae/vlm/scan. Same mechanics as external_loaders.js: the list is
// cached in node.properties so a saved workflow restores without a rescan, and
// the extra widgets (status, refresh button) are appended and not serialized.
const NODE_NAME = "UmbraeVLMLoader";
const ROOT_WIDGET = "external_root";
const MODEL_WIDGET = "model";

function findWidget(node, name) {
    return node.widgets ? node.widgets.find((w) => w.name === name) : undefined;
}

function readNodeString(src) {
    if (src.widgets && src.widgets.length) {
        const named = src.widgets.find(
            (w) => typeof w.value === "string" &&
                   ["value", "string", "text", "STRING", "string_value"].includes(w.name)
        );
        if (named) return named.value;
        const anyStr = src.widgets.find((w) => typeof w.value === "string");
        if (anyStr) return anyStr.value;
    }
    if (Array.isArray(src.widgets_values)) {
        const s = src.widgets_values.find((v) => typeof v === "string");
        if (s !== undefined) return s;
    }
    return null;
}

function getRoot(node) {
    const slot = node.findInputSlot ? node.findInputSlot(ROOT_WIDGET) : -1;
    if (slot >= 0 && node.inputs && node.inputs[slot] && node.inputs[slot].link != null) {
        const src = node.getInputNode ? node.getInputNode(slot) : null;
        if (src) {
            const v = readNodeString(src);
            if (v != null) return v;
        }
        return "";
    }
    const w = findWidget(node, ROOT_WIDGET);
    return w ? (w.value || "") : "";
}

function applyList(node, models, status, resetIfInvalid) {
    const modelW = findWidget(node, MODEL_WIDGET);
    if (!modelW) return;
    modelW.options = modelW.options || {};
    modelW.options.values = models;
    if (resetIfInvalid) {
        const cur = modelW.value;
        if (!models.includes(cur)) {
            modelW.value = models.length ? models[0] : "";
            if (typeof modelW.callback === "function") {
                try { modelW.callback(modelW.value); } catch (e) { /* noop */ }
            }
        }
    }
    if (node._vlmStatus) node._vlmStatus.value = status || "";
    node.setDirtyCanvas(true, true);
}

async function refreshFromDisk(node, preserveValue) {
    const root = getRoot(node);
    let data;
    try {
        const resp = await api.fetchApi(`/umbrae/vlm/scan?root=${encodeURIComponent(root)}`);
        data = await resp.json();
    } catch (e) {
        if (node._vlmStatus) node._vlmStatus.value = "scan error";
        node.setDirtyCanvas(true, true);
        return;
    }
    const models = Array.isArray(data.models) ? data.models : [];
    const status = data.status || "";
    node.properties = node.properties || {};
    node.properties._vlmModels = models;
    node.properties._vlmStatus = status;
    applyList(node, models, status, !preserveValue);
}

function setupNode(node) {
    if (node._vlmSetup) return;
    node._vlmSetup = true;

    const statusW = node.addWidget("text", "status", "", () => {});
    statusW.disabled = true;
    statusW.serialize = false;
    node._vlmStatus = statusW;

    const refreshW = node.addWidget("button", "🔄 Refresh models", null, () => {
        refreshFromDisk(node, false);
    });
    refreshW.serialize = false;

    // Rescan when the root text is committed (not per keystroke).
    const rootW = findWidget(node, ROOT_WIDGET);
    if (rootW) {
        const prev = rootW.callback;
        rootW.callback = function (v) {
            const r = prev ? prev.apply(this, arguments) : undefined;
            refreshFromDisk(node, false);
            return r;
        };
    }
}

app.registerExtension({
    name: "umbrae.vlm_loader",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_NAME) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            setupNode(this);
            const node = this;
            setTimeout(() => {
                if (node.properties && Array.isArray(node.properties._vlmModels)) {
                    applyList(node, node.properties._vlmModels, node.properties._vlmStatus || "", false);
                } else {
                    const legacy = node.properties && node.properties._vlmModels === undefined
                                   && findWidget(node, MODEL_WIDGET) && findWidget(node, MODEL_WIDGET).value;
                    refreshFromDisk(node, !!legacy);
                }
            }, 0);
            return r;
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            const r = onConfigure ? onConfigure.apply(this, arguments) : undefined;
            setupNode(this);
            if (this.properties && Array.isArray(this.properties._vlmModels)) {
                applyList(this, this.properties._vlmModels, this.properties._vlmStatus || "", false);
            }
            return r;
        };

        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (type, index, connected, link_info, ioSlot) {
            const r = onConnectionsChange ? onConnectionsChange.apply(this, arguments) : undefined;
            try {
                const LG = window.LiteGraph;
                const isInput = LG ? (type === LG.INPUT) : (type === 1);
                if (isInput && this.inputs && this.inputs[index] && this.inputs[index].name === ROOT_WIDGET) {
                    refreshFromDisk(this, false);
                }
            } catch (e) { /* noop */ }
            return r;
        };
    },
});
