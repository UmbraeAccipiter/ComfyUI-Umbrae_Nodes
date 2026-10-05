// ui_lab.js -- DEV ONLY: mounts the ui_lab_panels variants on three do-nothing nodes
// (see ui_lab_node.py). Delete together with ui_lab_panels.js to remove the lab.

import { app } from "../../scripts/app.js";
import { measureRootContent, attachAutoHeight, applyAdaptiveCanvasOnly } from "./umbrae_resize.js";
import { buildCurrent, buildUnified, buildSkinned } from "./ui_lab_panels.js";

const NODES = {
    UmbraeUILabCurrent: { build: buildCurrent },
    UmbraeUILabUnified: { build: buildUnified },
    // Pixaroma-style node colors (title #1d1d1d, body #2a2a2a), applied only if unset.
    UmbraeUILabSkinned: { build: buildSkinned, color: "#1d1d1d", bgcolor: "#2a2a2a" },
};

function setupNode(node, cfg) {
    let auto = null;
    const scheduleResize = () => { if (auto) auto.scheduleRelayout(); };
    const root = cfg.build(scheduleResize);

    const measureH = () => measureRootContent(root);
    const w = node.addDOMWidget("ui_lab", "custom", root, {
        getValue: () => null, setValue: () => {}, serialize: false,
        getMinHeight: measureH, getMaxHeight: measureH, margin: 4,
    });
    applyAdaptiveCanvasOnly(w);
    if (w?.element) { w.element.style.width = "100%"; w.element.style.boxSizing = "border-box"; }

    const W = Math.max(node.size?.[0] ?? 0, 300);
    if (typeof node.setSize === "function") node.setSize([W, node.size?.[1] ?? 120]);
    auto = attachAutoHeight(node, root, w);

    if (cfg.color && !node.color) node.color = cfg.color;
    if (cfg.bgcolor && !node.bgcolor) node.bgcolor = cfg.bgcolor;

    const onRemoved = node.onRemoved;
    node.onRemoved = function () { auto.dispose(); return onRemoved?.apply(this, arguments); };
}

app.registerExtension({
    name: "umbrae.UILab",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const cfg = NODES[nodeData.name];
        if (!cfg) return;
        const onCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onCreated?.apply(this, arguments);
            setupNode(this, cfg);
        };
    },
});
