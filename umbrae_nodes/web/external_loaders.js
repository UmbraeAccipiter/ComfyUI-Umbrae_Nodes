import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// node class name -> { folder type, file-combo widget name }
const NODE_TYPES = {
    "ExternalCheckpointLoaderSimple": { type: "checkpoints",      widget: "ckpt_name" },
    "ExternalUNETLoader":             { type: "diffusion_models", widget: "unet_name" },
    "ExternalVAELoader":              { type: "vae",              widget: "vae_name" },
    "ExternalCLIPLoader":             { type: "text_encoders",    widget: "clip_name" },
    "ExternalCLIPVisionLoader":       { type: "clip_vision",      widget: "clip_name" },
    "ExternalLoraLoader":             { type: "loras",            widget: "lora_name" },
    "ExternalLoraLoaderModelOnly":    { type: "loras",            widget: "lora_name" },
    "ExternalUpscaleModelLoader":     { type: "upscale_models",   widget: "model_name" },
};

function findWidget(node, name) {
    return node.widgets ? node.widgets.find((w) => w.name === name) : undefined;
}

// Best-effort read of a string value out of an upstream node (e.g. a String
// node wired into external_root). Editor-time only; runtime-computed values
// can't be previewed (the dropdown simply stays empty, which is the signal).
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

// Resolve the active root: follow the wire if external_root is connected as an
// input, otherwise read the local widget.
function getRoot(node) {
    const slot = node.findInputSlot ? node.findInputSlot("external_root") : -1;
    if (slot >= 0 && node.inputs && node.inputs[slot] && node.inputs[slot].link != null) {
        const src = node.getInputNode ? node.getInputNode(slot) : null;
        if (src) {
            const v = readNodeString(src);
            if (v != null) return v;
        }
        return ""; // wired but unreadable -> empty list -> visible "no path" signal
    }
    const w = findWidget(node, "external_root");
    return w ? (w.value || "") : "";
}

// Apply a file list to the dropdown.
//   resetIfInvalid=false -> restore from cache; NEVER touch the selected value.
//   resetIfInvalid=true  -> live scan; only then snap to a valid entry.
function applyList(node, cfg, files, status, resetIfInvalid) {
    const fileW = findWidget(node, cfg.widget);
    if (!fileW) return;
    fileW.options = fileW.options || {};
    fileW.options.values = files;

    if (resetIfInvalid) {
        const cur = fileW.value;
        if (!files.includes(cur)) {
            fileW.value = files.length ? files[0] : "";
            if (typeof fileW.callback === "function") {
                try { fileW.callback(fileW.value); } catch (e) { /* noop */ }
            }
        }
    }

    if (node._extStatus) node._extStatus.value = status || "";
    node.setDirtyCanvas(true, true);
}

// Hit the server scan route, cache the result in serialized node properties,
// and apply it. preserveValue=true keeps the current selection untouched
// (used when migrating a legacy node that has no cached list yet).
async function refreshFromDisk(node, cfg, preserveValue) {
    const root = getRoot(node);
    let data;
    try {
        const resp = await api.fetchApi(
            `/external_loaders/scan?root=${encodeURIComponent(root)}&type=${encodeURIComponent(cfg.type)}`
        );
        data = await resp.json();
    } catch (e) {
        if (node._extStatus) node._extStatus.value = "scan error";
        node.setDirtyCanvas(true, true);
        return;
    }

    const files = Array.isArray(data.files) ? data.files : [];
    const status = data.status || "";

    node.properties = node.properties || {};
    node.properties._extFiles = files;
    node.properties._extStatus = status;

    applyList(node, cfg, files, status, !preserveValue);
}

function setupNode(node, cfg) {
    if (node._extSetup) return;
    node._extSetup = true;

    // Read-only status line, appended at the end (not serialized).
    const statusW = node.addWidget("text", "status", "", () => {});
    statusW.disabled = true;
    statusW.serialize = false;
    node._extStatus = statusW;

    // Refresh button, appended at the end (not serialized). No reordering of
    // existing widgets -> saved numeric values stay aligned (no NaN).
    const refreshW = node.addWidget("button", "\uD83D\uDD04 Refresh files", null, () => {
        refreshFromDisk(node, cfg, false);
    });
    refreshW.serialize = false;
}

app.registerExtension({
    name: "umbrae.external_loaders",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const cfg = NODE_TYPES[nodeData.name];
        if (!cfg) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated ? onNodeCreated.apply(this, arguments) : undefined;
            setupNode(this, cfg);
            const node = this;
            // Defer so a saved workflow's properties/values restore first.
            setTimeout(() => {
                if (node.properties && Array.isArray(node.properties._extFiles)) {
                    // Loaded node with cache: restore list, keep selection.
                    applyList(node, cfg, node.properties._extFiles,
                              node.properties._extStatus || "", false);
                } else {
                    // Fresh node, or legacy node with no cache: scan once.
                    const legacy = node.properties && node.properties._extFiles === undefined
                                   && findWidget(node, cfg.widget)
                                   && findWidget(node, cfg.widget).value;
                    refreshFromDisk(node, cfg, !!legacy);
                }
            }, 0);
            return r;
        };

        // Restore cached list synchronously on load (no re-scan, no wipe).
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            const r = onConfigure ? onConfigure.apply(this, arguments) : undefined;
            setupNode(this, cfg);
            if (this.properties && Array.isArray(this.properties._extFiles)) {
                applyList(this, cfg, this.properties._extFiles,
                          this.properties._extStatus || "", false);
            }
            return r;
        };

        // Auto-refresh when external_root is wired or unwired.
        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (type, index, connected, link_info, ioSlot) {
            const r = onConnectionsChange ? onConnectionsChange.apply(this, arguments) : undefined;
            try {
                const LG = window.LiteGraph;
                const isInput = LG ? (type === LG.INPUT) : (type === 1);
                if (isInput && this.inputs && this.inputs[index] &&
                    this.inputs[index].name === "external_root") {
                    refreshFromDisk(this, cfg, false);
                }
            } catch (e) { /* noop */ }
            return r;
        };
    },
});
