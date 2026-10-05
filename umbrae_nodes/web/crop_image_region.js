import { app } from "../../scripts/app.js";
import { buildScaleSection } from "./umbrae_scale.js";
import { measureRootContent, attachAutoHeight, applyAdaptiveCanvasOnly } from "./umbrae_resize.js";
import { injectTheme } from "./umbrae_theme.js";
import { makeNum, makeChips, makeToggle, makeText } from "./umbrae_panel_controls.js";

const NODE_TYPE = "CropImageRegion";
const ACCENT    = "#7aa8d4";


// ── Numeric input factory ─────────────────────────────────────────────────────

// ── Chip row factory ──────────────────────────────────────────────────────────

// ── Toggle factory ─────────────────────────────────────────────────────────

// ── Text input factory ────────────────────────────────────────────────────────

// ── Measure accurate content height ──────────────────────────────────────────
function measureContent(root) {
    let h = 0, count = 0;
    for (const child of root.children) {
        if (child.offsetParent === null) continue;
        h += child.offsetHeight;
        count++;
    }
    const cs = getComputedStyle(root);
    const gap = parseFloat(cs.rowGap || cs.gap) || 0;
    if (count > 1) h += gap * (count - 1);
    h += (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
    return h;
}

// ── Resize floor (prevents spill in Vue/Nodes-2.0 during drag) ───────────────
function installResizeFloor(root) {
    const isVue = () => !!window.LiteGraph?.vueNodesMode;
    let armed = false;
    const clear = () => { if (!armed) return; armed = false; root.style.minHeight = ""; };
    const onDown = e => {
        if (!isVue() || !root.isConnected) return;
        let cur = "";
        try { cur = getComputedStyle(e.target).cursor || ""; } catch (_) {}
        if (!cur.includes("resize")) return;
        const myN  = root.closest(".lg-node");
        const dnN  = e.target?.closest?.(".lg-node");
        if (myN && dnN && myN !== dnN) return;
        const h = measureContent(root);
        if (h > 0) { root.style.minHeight = Math.round(h) + "px"; armed = true; }
    };
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("pointerup",   clear,  true);
    window.addEventListener("pointercancel", clear, true);
    return () => {
        window.removeEventListener("pointerdown", onDown, true);
        window.removeEventListener("pointerup",   clear,  true);
        window.removeEventListener("pointercancel", clear, true);
        clear();
    };
}

// ── Node setup ────────────────────────────────────────────────────────────────
function setupNode(node) {
    injectTheme();
    if (!node.bgcolor) node.bgcolor = "#2a2a2a";
    if (!node.color) node.color = "#1f1f1f";

    function getState() { return node.properties?.cirState ?? {}; }
    function setState(patch) {
        if (!node.properties) node.properties = {};
        node.properties.cirState = { ...getState(), ...patch };
    }

    const st = getState();
    const root = document.createElement("div");
    root.className = "cir-root";

    // ── Scaling (shared module, identical across all three nodes) ──────────────
    const sharedGetState = () => getState();
    const sharedPatchState = (_n, patch) => setState(patch);
    function isBboxOverrideConnected() {
        const idx = node.findInputSlot ? node.findInputSlot("bbox_override") : -1;
        return idx >= 0 && node.inputs?.[idx]?.link != null;
    }

    const { root: scaleRoot, refresh: refreshScale } = buildScaleSection(
        node,
        sharedGetState,
        sharedPatchState,
        { showUniform: false, onChange: () => scheduleResize(), isBboxConnected: isBboxOverrideConnected }
    );
    const mSec = document.createElement("div");
    mSec.append(scaleRoot);

    const _occ = node.onConnectionsChange;
    node.onConnectionsChange = function() {
        refreshScale();
        renderMaskSection();
        return _occ?.apply(this, arguments);
    };

    // ── Padding ────────────────────────────────────────────────────────────────
    const pLabel = document.createElement("div");
    pLabel.className = "cir-label";
    pLabel.textContent = "Padding";

    const pNum = makeNum(st.padding ?? 10, 0, 500, 1,
        v => setState({ padding: v }));
    pNum.wrap.className += " cir-pad-inp";

    const uChips = makeChips([
        { val: "pixels",     label: "px" },
        { val: "percentage", label: "%" },
    ], st.padding_unit ?? "percentage", v => setState({ padding_unit: v }));
    uChips.el.className = "cir-unit";

    const pRow = document.createElement("div");
    pRow.className = "cir-pad-row";
    pRow.append(pNum.wrap, uChips.el);

    const pSec = document.createElement("div");
    pSec.append(pLabel, pRow);

    // ── Save ──────────────────────────────────────────────────────────────────
    const saveLabel = document.createElement("div");
    saveLabel.className = "cir-label";
    saveLabel.textContent = "Save";

    const saveFields = document.createElement("div");
    saveFields.className = "cir-save-fields";

    const folderInp = makeText(st.output_folder ?? "cropped_images", "Output folder",
        v => setState({ output_folder: v }));

    const fmtLabel = document.createElement("div");
    fmtLabel.className = "cir-label";
    fmtLabel.textContent = "Format";
    const fmtChips = makeChips([
        { val: "png",  label: "png"  },
        { val: "jpg",  label: "jpg"  },
        { val: "webp", label: "webp" },
    ], st.format ?? "png", v => { setState({ format: v }); renderMaskSection(); });
    const fmtSec = document.createElement("div");
    fmtSec.append(fmtLabel, fmtChips.el);

    const nameRow = document.createElement("div");
    nameRow.className = "cir-text-row";
    const prefixInp = makeText(st.prefix ?? "", "prefix", v => setState({ prefix: v }));
    const suffixInp = makeText(st.suffix ?? "", "suffix", v => setState({ suffix: v }));
    nameRow.append(prefixInp.el, suffixInp.el);

    const overwriteToggle = makeToggle(st.overwrite !== false, "Overwrite: On", "Overwrite: Off",
        v => setState({ overwrite: v }));

    saveFields.append(folderInp.el, fmtSec, nameRow, overwriteToggle.el);

    const saveToggle = makeToggle(st.save_image !== false, "Save Image: On", "Save Image: Off", v => {
        setState({ save_image: v });
        saveFields.style.display = v ? "" : "none";
        scheduleResize();
    });
    saveFields.style.display = (st.save_image !== false) ? "" : "none";

    const saveSec = document.createElement("div");
    saveSec.append(saveLabel, saveToggle.el, saveFields);

    // ── Mask (only shown when a mask is wired) ────────────────────────────────
    function isMaskConnected() {
        const idx = node.findInputSlot ? node.findInputSlot("mask") : -1;
        return idx >= 0 && node.inputs?.[idx]?.link != null;
    }
    const maskLabel = document.createElement("div");
    maskLabel.className = "cir-label";
    maskLabel.textContent = "Mask";

    const interpChips = makeChips([
        { val: "nearest",  label: "Nearest"  },
        { val: "bilinear", label: "Bilinear" },
    ], st.mask_interpolation ?? "nearest", v => setState({ mask_interpolation: v }));
    [...interpChips.el.children].forEach((b, i) => {
        b.title = i === 0
            ? "Nearest — hard edges, exact binary values. Best for hard-line masks."
            : "Bilinear — smooth interpolation; preserves soft / feathered mask edges.";
    });

    const maskJpgToggle = makeToggle(st.mask_force_jpg === true, "Mask: force JPG", "Mask: PNG (safe)",
        v => setState({ mask_force_jpg: v }));
    maskJpgToggle.el.title = "When the image saves as JPG: keep the mask as lossless PNG (safe default), "
        + "or force JPG to match the image (lossy — can fuzz mask edges/values).";

    const maskSec = document.createElement("div");
    maskSec.append(maskLabel, interpChips.el, maskJpgToggle.el);

    function renderMaskSection() {
        const connected = isMaskConnected();
        maskSec.style.display = connected ? "" : "none";
        const isJpg = (getState().format ?? "png") === "jpg";
        maskJpgToggle.el.style.display = (connected && isJpg) ? "" : "none";
        scheduleResize();
    }

    // ── Iteration ────────────────────────────────────────────────────────────
    // Independent of Save Image — lets a node opt in/out of the multi-instance
    // completion count without that being tied to whether it writes a file.
    const iterLabel = document.createElement("div");
    iterLabel.className = "cir-label";
    iterLabel.textContent = "Iteration";

    const iterToggle = makeToggle(st.iterate !== false, "Counts Toward Completion: On",
        "Counts Toward Completion: Off", v => setState({ iterate: v }));
    iterToggle.el.title = "When on, this node is one of the instances the batch loader "
        + "waits for before advancing to the next image. Turn off for a node that "
        + "shouldn't gate the loop (e.g. a debug-only crop).";

    const iterSec = document.createElement("div");
    iterSec.append(iterLabel, iterToggle.el);

    root.append(mSec, pSec, saveSec, maskSec, iterSec);

    // ── DOM widget (verified mount contract) ──────────────────────────────────
    const measureH = () => measureRootContent(root);
    let auto = null;
    function scheduleResize(){ if (auto) auto.scheduleRelayout(); }

    const _cirWidget = node.addDOMWidget("cir_ui", "custom", root, {
        getValue: () => null, setValue: () => {}, serialize: false,
        getMinHeight: measureH, getMaxHeight: measureH, margin: 4,
    });
    applyAdaptiveCanvasOnly(_cirWidget);
    if (_cirWidget?.element) {
        _cirWidget.element.style.width = "100%";
        _cirWidget.element.style.boxSizing = "border-box";
    }
    const _W = Math.max(node.size?.[0] ?? 0, 340);
    if (typeof node.setSize === "function") node.setSize([_W, node.size?.[1] ?? 120]);
    else if (node.size) node.size[0] = _W;
    auto = attachAutoHeight(node, root, _cirWidget);
    renderMaskSection();

    const _onr = node.onRemoved;
    node.onRemoved = function() { auto.dispose(); return _onr?.apply(this, arguments); };

    // ── Persist settings across reload ────────────────────────────────────────
    // onNodeCreated builds the UI before ComfyUI restores node.properties from a
    // saved workflow, so the controls start at their defaults. Once configure()
    // has run (properties restored), re-apply cirState to every control.
    function syncUI() {
        const s = getState();
        pNum.setValue(s.padding ?? 10);
        uChips.setActive(s.padding_unit ?? "percentage");
        folderInp.setValue(s.output_folder ?? "cropped_images");
        fmtChips.setActive(s.format ?? "png");
        prefixInp.setValue(s.prefix ?? "");
        suffixInp.setValue(s.suffix ?? "");
        overwriteToggle.setValue(s.overwrite !== false);
        saveToggle.setValue(s.save_image !== false);
        saveFields.style.display = (s.save_image !== false) ? "" : "none";
        iterToggle.setValue(s.iterate !== false);
        interpChips.setActive(s.mask_interpolation ?? "nearest");
        maskJpgToggle.setValue(s.mask_force_jpg === true);
        refreshScale();
        renderMaskSection();
        scheduleResize();
    }
    const _ocfg = node.onConfigure;
    node.onConfigure = function() {
        const r = _ocfg?.apply(this, arguments);
        syncUI();
        return r;
    };
}

// ── Extension ─────────────────────────────────────────────────────────────────
app.registerExtension({
    name: "UNP.CropImageRegion",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;

        const _onc = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function() {
            _onc?.apply(this, arguments);
            setupNode(this);
        };

        // Every CropImageRegion instance with "Counts Toward Completion" on
        // reports in here when it executes. Only once all of them have
        // reported in for this run does the batch loader actually advance —
        // so wiring three of these (face/body/feature) to the same loader
        // still advances exactly one step per source image, not three. This
        // is independent of whether the instance actually saved a file.
        const _oe = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function(message) {
            _oe?.apply(this, arguments);

            if (this.properties?.cirState?.iterate === false) return;

            const expected = (app.graph?._nodes ?? []).filter(n =>
                (n.type === NODE_TYPE || n.comfyClass === NODE_TYPE) &&
                n.properties?.cirState?.iterate !== false
            ).length;
            if (expected <= 0) return;

            app._unpCropCompleted = (app._unpCropCompleted ?? 0) + 1;
            if (app._unpCropCompleted < expected) return;
            app._unpCropCompleted = 0;

            const count = app._unpBatchFileCount ?? 0;
            if (count <= 0) return;

            const loader = app.graph?._nodes?.find(n =>
                n.type === "LoadImagesUniformBatch" ||
                n.comfyClass === "LoadImagesUniformBatch" ||
                n.properties?.lbuState !== undefined
            );
            if (!loader) return;

            const idxWidget = loader.widgets?.find(w => w.name === "image_index");
            if (!idxWidget) return;

            const widgetVal = parseInt(idxWidget.value) || 0;
            if (app._unpCurrentIndex === undefined || widgetVal !== app._unpCurrentIndex)
                app._unpCurrentIndex = widgetVal;
            const current = app._unpCurrentIndex;

            if (current >= count - 1) {
                app._unpCurrentIndex = 0;
                idxWidget.value = 0;
                app._unpNextImageIndex = 0;
                app._unpBatchFileCount = 0;
                return;
            }

            app._unpCurrentIndex = current + 1;
            app._unpNextImageIndex = current + 1;
            idxWidget.value = current + 1;
            setTimeout(() => app.queuePrompt(0, 1), 300);
        };
    },
});

// ── graphToPrompt hook ────────────────────────────────────────────────────────
const _orig = app.graphToPrompt.bind(app);
app.graphToPrompt = async function(...args) {
    const result = await _orig(...args);
    const out = result?.output;
    if (!out) return result;
    for (const id in out) {
        const entry = out[id];
        if (!entry || entry.class_type !== NODE_TYPE) continue;
        const node = app.graph?._nodes?.find(n => String(n.id) === String(id));
        if (!node) continue;
        entry.inputs = entry.inputs || {};
        entry.inputs.ui_state = JSON.stringify(node.properties?.cirState ?? {});
    }
    return result;
};
