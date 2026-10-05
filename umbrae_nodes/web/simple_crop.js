import { app } from "../../scripts/app.js";
import { buildScaleSection } from "./umbrae_scale.js";
import { measureRootContent, attachAutoHeight, applyAdaptiveCanvasOnly } from "./umbrae_resize.js";
import { injectTheme } from "./umbrae_theme.js";
import { makeNum, makeChips, makeToggle, subLabel } from "./umbrae_panel_controls.js";

const NODE_TYPE = "UmbraeSimpleCrop";

function setupNode(node) {
    injectTheme();
    if (!node.bgcolor) node.bgcolor = "#2a2a2a";
    if (!node.color) node.color = "#1f1f1f";

    function getState() { return node.properties?.scpState ?? {}; }
    function setState(patch) {
        if (!node.properties) node.properties = {};
        node.properties.scpState = { ...getState(), ...patch };
    }

    const st = getState();
    const root = document.createElement("div");
    root.className = "cir-root";

    // ── Scale (shared module; SMALLEST_EDGE lives here) ───────────────────────
    const sharedGetState = () => getState();
    const sharedPatchState = (_n, patch) => setState(patch);
    const { root: scaleRoot, refresh: refreshScale } = buildScaleSection(
        node, sharedGetState, sharedPatchState,
        { showUniform: false, onChange: () => scheduleResize(), isBboxConnected: () => false }
    );
    const mSec = document.createElement("div"); mSec.append(scaleRoot);

    const _occ = node.onConnectionsChange;
    node.onConnectionsChange = function() { refreshScale(); return _occ?.apply(this, arguments); };

    // ── Region (shaping) ──────────────────────────────────────────────────────
    const rLabel = document.createElement("div"); rLabel.className = "cir-label"; rLabel.textContent = "Region";

    const shapeChips = makeChips(
        [{ val: "exact", label: "Exact bbox" }, { val: "aspect", label: "Shape to aspect" }],
        st.shape_mode ?? "exact", v => { setState({ shape_mode: v }); renderRegion(); });

    const aspSrcChips = makeChips(
        [{ val: "bbox", label: "Bbox" }, { val: "image", label: "Image" }, { val: "user", label: "User" }],
        st.aspect_source ?? "bbox", v => { setState({ aspect_source: v }); renderRegion(); });
    const aspSrcWrap = document.createElement("div"); aspSrcWrap.append(subLabel("Aspect source"), aspSrcChips.el);

    const ratioRow = document.createElement("div"); ratioRow.className = "cir-pad-row";
    const ratioW = makeNum(st.shape_ratio_w ?? 1, 0.01, 100, 0.1, v => setState({ shape_ratio_w: v }));
    const ratioH = makeNum(st.shape_ratio_h ?? 1, 0.01, 100, 0.1, v => setState({ shape_ratio_h: v }));
    ratioRow.append(ratioW.wrap, ratioH.wrap);
    const ratioWrap = document.createElement("div"); ratioWrap.append(subLabel("Aspect ratio (w : h)"), ratioRow);

    const minToggle = makeToggle(st.min_crop_on === true, "Minimum crop size: On", "Minimum crop size: Off",
        v => { setState({ min_crop_on: v }); renderRegion(); });
    minToggle.el.title = "Grow the crop window from the bbox center (preserving aspect, pulling in source) "
        + "until its short edge reaches the minimum, before resizing. SMALLEST_EDGE feeds its size here.";
    const minNum = makeNum(st.min_crop_size ?? (st.target_size ?? 1024), 8, 16384, 8, v => setState({ min_crop_size: v }));
    const minWrap = document.createElement("div"); minWrap.append(subLabel("Minimum short edge (px)"), minNum.wrap);

    const padRow = document.createElement("div"); padRow.className = "cir-pad-row";
    const padNum = makeNum(st.padding ?? 10, 0, 100000, 1, v => setState({ padding: v }));
    padNum.wrap.className += " cir-pad-inp";
    const padUnit = document.createElement("div"); padUnit.className = "cir-unit";
    const unitChips = makeChips(
        [{ val: "percentage", label: "%" }, { val: "pixels", label: "px" }],
        st.padding_unit ?? "percentage", v => setState({ padding_unit: v }));
    padUnit.append(unitChips.el);
    padRow.append(padNum.wrap, padUnit);
    const padWrap = document.createElement("div"); padWrap.append(subLabel("Padding"), padRow);

    const rSec = document.createElement("div");
    rSec.append(rLabel, shapeChips.el, aspSrcWrap, ratioWrap, minToggle.el, minWrap, padWrap);

    function renderRegion() {
        const s = getState();
        const isAspect = (s.shape_mode ?? "exact") === "aspect";
        aspSrcWrap.style.display = isAspect ? "" : "none";
        ratioWrap.style.display = (isAspect && (s.aspect_source ?? "bbox") === "user") ? "" : "none";
        minWrap.style.display = (s.min_crop_on === true) ? "" : "none";
        scheduleResize();
    }

    // ── Mask ──────────────────────────────────────────────────────────────────
    const maskLabel = document.createElement("div"); maskLabel.className = "cir-label"; maskLabel.textContent = "Mask";
    const interpChips = makeChips(
        [{ val: "nearest", label: "Nearest" }, { val: "bilinear", label: "Bilinear" }],
        st.mask_interpolation ?? "nearest", v => setState({ mask_interpolation: v }));
    [...interpChips.el.children].forEach((b, i) => {
        b.title = i === 0
            ? "Nearest — hard edges, exact binary values. Best for hard-line masks."
            : "Bilinear — smooth interpolation; preserves soft / feathered mask edges.";
    });
    const maskSec = document.createElement("div"); maskSec.append(maskLabel, interpChips.el);

    // ── Advanced (flatten / extract / merge) ──────────────────────────────────
    const advHead = document.createElement("div"); advHead.className = "cir-adv-head";
    const advTitle = document.createElement("div"); advTitle.className = "cir-label"; advTitle.style.marginBottom = "0"; advTitle.textContent = "Advanced";
    const advArrow = document.createElement("div"); advArrow.className = "cir-arrow"; advArrow.textContent = "▶";
    advHead.append(advTitle, advArrow);
    const advBody = document.createElement("div"); advBody.className = "cir-adv-body"; advBody.style.display = "none";

    const flatRegion = makeToggle(st.flatten_region !== false, "Region: merge detections", "Region: keep separate",
        v => setState({ flatten_region: v }));
    const flatAlt = makeToggle(st.flatten_alt !== false, "Region alt: merge", "Region alt: keep separate",
        v => setState({ flatten_alt: v }));
    const exItems = [{ val: "both", label: "Both" }, { val: "bbox", label: "Bbox" }, { val: "mask", label: "Mask" }];
    const exRegion = makeChips(exItems, st.extract_region ?? "both", v => setState({ extract_region: v }));
    const exAlt = makeChips(exItems, st.extract_alt ?? "both", v => setState({ extract_alt: v }));
    const mergeChips = makeChips(
        [{ val: "union", label: "Union (cover all)" }, { val: "largest", label: "Largest only" }],
        st.merge_method ?? "union", v => setState({ merge_method: v }));

    const exRWrap = document.createElement("div"); exRWrap.append(subLabel("Extract — Region"), exRegion.el);
    const exAWrap = document.createElement("div"); exAWrap.append(subLabel("Extract — Region alternate"), exAlt.el);
    const mergeWrap = document.createElement("div"); mergeWrap.append(subLabel("Merge method (boxes)"), mergeChips.el);
    advBody.append(flatRegion.el, flatAlt.el, exRWrap, exAWrap, mergeWrap);

    advHead.onclick = () => {
        const open = advBody.style.display === "none";
        advBody.style.display = open ? "" : "none";
        advHead.classList.toggle("open", open);
        scheduleResize();
    };
    const advSec = document.createElement("div"); advSec.append(advHead, advBody);

    root.append(mSec, rSec, maskSec, advSec);

    // ── DOM widget (verified mount contract) ──────────────────────────────────
    const measureH = () => measureRootContent(root);
    let auto = null;
    function scheduleResize() { if (auto) auto.scheduleRelayout(); }

    const _w = node.addDOMWidget("scp_ui", "custom", root, {
        getValue: () => null, setValue: () => {}, serialize: false,
        getMinHeight: measureH, getMaxHeight: measureH, margin: 4,
    });
    applyAdaptiveCanvasOnly(_w);
    if (_w?.element) { _w.element.style.width = "100%"; _w.element.style.boxSizing = "border-box"; }
    const _W = Math.max(node.size?.[0] ?? 0, 340);
    if (typeof node.setSize === "function") node.setSize([_W, node.size?.[1] ?? 120]);
    else if (node.size) node.size[0] = _W;
    auto = attachAutoHeight(node, root, _w);
    renderRegion();

    const _onr = node.onRemoved;
    node.onRemoved = function() { auto.dispose(); return _onr?.apply(this, arguments); };

    function syncUI() {
        const s = getState();
        shapeChips.setActive(s.shape_mode ?? "exact");
        aspSrcChips.setActive(s.aspect_source ?? "bbox");
        ratioW.setValue(s.shape_ratio_w ?? 1);
        ratioH.setValue(s.shape_ratio_h ?? 1);
        minToggle.setValue(s.min_crop_on === true);
        minNum.setValue(s.min_crop_size ?? (s.target_size ?? 1024));
        padNum.setValue(s.padding ?? 10);
        unitChips.setActive(s.padding_unit ?? "percentage");
        interpChips.setActive(s.mask_interpolation ?? "nearest");
        flatRegion.setValue(s.flatten_region !== false);
        flatAlt.setValue(s.flatten_alt !== false);
        exRegion.setActive(s.extract_region ?? "both");
        exAlt.setActive(s.extract_alt ?? "both");
        mergeChips.setActive(s.merge_method ?? "union");
        refreshScale();
        renderRegion();
        scheduleResize();
    }
    const _ocfg = node.onConfigure;
    node.onConfigure = function() { const r = _ocfg?.apply(this, arguments); syncUI(); return r; };
}

app.registerExtension({
    name: "UNP.UmbraeSimpleCrop",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;
        const _onc = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function() { _onc?.apply(this, arguments); setupNode(this); };
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
        entry.inputs.ui_state = JSON.stringify(node.properties?.scpState ?? {});
    }
    return result;
};
