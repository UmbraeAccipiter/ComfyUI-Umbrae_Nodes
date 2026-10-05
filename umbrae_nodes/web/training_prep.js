import { app } from "../../scripts/app.js";
import { buildScaleSection } from "./umbrae_scale.js";
import { measureRootContent, attachAutoHeight, applyAdaptiveCanvasOnly } from "./umbrae_resize.js";
import { injectTheme } from "./umbrae_theme.js";
import { makeNum, makeChips, makeToggle, makeText, subLabel as sub } from "./umbrae_panel_controls.js";

const NODE_TYPE = "UmbraeTrainingPrep";
const TOKENS_TIP = "Tokens: {stem} (source name) · {segs} (segment label) · {index} (per-image counter) "
    + "· {ext} · {w} · {h} · {folder}. A token with no data resolves to NODATA.";


function setupNode(node) {
    injectTheme();
    if (!node.bgcolor) node.bgcolor = "#2a2a2a";
    if (!node.color) node.color = "#1f1f1f";

    function getState() { return node.properties?.tpState ?? {}; }
    function setState(patch) { if (!node.properties) node.properties = {}; node.properties.tpState = { ...getState(), ...patch }; }

    const st = getState();
    const root = document.createElement("div"); root.className = "cir-root";

    // ── Scale ──────────────────────────────────────────────────────────────────
    const { root: scaleRoot, refresh: refreshScale } = buildScaleSection(
        node, () => getState(), (_n, p) => setState(p),
        { showUniform: false, onChange: () => scheduleResize(), isBboxConnected: () => false });
    const mSec = document.createElement("div"); mSec.append(scaleRoot);
    const _occ = node.onConnectionsChange;
    node.onConnectionsChange = function() { refreshScale(); return _occ?.apply(this, arguments); };

    // ── Region shaping ─────────────────────────────────────────────────────────
    const rLabel = document.createElement("div"); rLabel.className = "cir-label"; rLabel.textContent = "Region";
    const shapeChips = makeChips([{ val: "exact", label: "Exact bbox" }, { val: "aspect", label: "Shape to aspect" }],
        st.shape_mode ?? "exact", v => { setState({ shape_mode: v }); renderRegion(); });
    const aspSrc = makeChips([{ val: "bbox", label: "Bbox" }, { val: "image", label: "Image" }, { val: "user", label: "User" }],
        st.aspect_source ?? "bbox", v => { setState({ aspect_source: v }); renderRegion(); });
    const aspWrap = document.createElement("div"); aspWrap.append(sub("Aspect source"), aspSrc.el);
    const ratioRow = document.createElement("div"); ratioRow.className = "cir-pad-row";
    const ratioW = makeNum(st.shape_ratio_w ?? 1, 0.01, 100, 0.1, v => setState({ shape_ratio_w: v }));
    const ratioH = makeNum(st.shape_ratio_h ?? 1, 0.01, 100, 0.1, v => setState({ shape_ratio_h: v }));
    ratioRow.append(ratioW.wrap, ratioH.wrap);
    const ratioWrap = document.createElement("div"); ratioWrap.append(sub("Aspect ratio (w : h)"), ratioRow);
    const minToggle = makeToggle(st.min_crop_on === true, "Minimum crop size: On", "Minimum crop size: Off",
        v => { setState({ min_crop_on: v }); renderRegion(); });
    const minNum = makeNum(st.min_crop_size ?? (st.target_size ?? 1024), 8, 16384, 8, v => setState({ min_crop_size: v }));
    const minWrap = document.createElement("div"); minWrap.append(sub("Minimum short edge (px)"), minNum.wrap);
    const padRow = document.createElement("div"); padRow.className = "cir-pad-row";
    const padNum = makeNum(st.padding ?? 10, 0, 100000, 1, v => setState({ padding: v })); padNum.wrap.className += " cir-pad-inp";
    const unitChips = makeChips([{ val: "percentage", label: "%" }, { val: "pixels", label: "px" }],
        st.padding_unit ?? "percentage", v => setState({ padding_unit: v }));
    const padUnit = document.createElement("div"); padUnit.className = "cir-unit"; padUnit.append(unitChips.el);
    padRow.append(padNum.wrap, padUnit);
    const padWrap = document.createElement("div"); padWrap.append(sub("Padding"), padRow);
    const rSec = document.createElement("div");
    rSec.append(rLabel, shapeChips.el, aspWrap, ratioWrap, minToggle.el, minWrap, padWrap);
    function renderRegion() {
        const s = getState();
        const isA = (s.shape_mode ?? "exact") === "aspect";
        aspWrap.style.display = isA ? "" : "none";
        ratioWrap.style.display = (isA && (s.aspect_source ?? "bbox") === "user") ? "" : "none";
        minWrap.style.display = (s.min_crop_on === true) ? "" : "none";
        scheduleResize();
    }

    // ── Save ───────────────────────────────────────────────────────────────────
    const saveLabel = document.createElement("div"); saveLabel.className = "cir-label"; saveLabel.textContent = "Save";
    const saveImageToggle = makeToggle(st.save_image !== false, "Save Image: On", "Save Image: Off",
        v => { setState({ save_image: v }); renderSave(); });
    const saveMaskToggle = makeToggle(st.save_mask !== false, "Save Mask: On", "Save Mask: Off",
        v => { setState({ save_mask: v }); renderSave(); });
    saveMaskToggle.el.title = "Writes the cropped mask to a masks/ subfolder, sharing the image's filename. Only acts when a mask is present.";
    const saveTextToggle = makeToggle(st.save_text !== false, "Save Text: On", "Save Text: Off",
        v => { setState({ save_text: v }); renderSave(); });
    saveTextToggle.el.title = "Writes the wired caption to <stem>.txt next to the image. Only acts when a caption is connected.";
    const folderInp = makeText(st.output_folder ?? "training_data", "training_data", v => setState({ output_folder: v }));
    const fmtChips = makeChips([{ val: "png", label: "PNG" }, { val: "jpg", label: "JPG" }, { val: "webp", label: "WebP" }],
        st.format ?? "png", v => { setState({ format: v }); renderSave(); });
    const prefixInp = makeText(st.prefix ?? "", "prefix", v => setState({ prefix: v }));
    const fnameInp  = makeText(st.filename ?? "{filename}", "{filename}", v => setState({ filename: v }));
    const suffixInp = makeText(st.suffix ?? "_{segs}", "_{segs}", v => setState({ suffix: v }));
    [prefixInp, fnameInp, suffixInp].forEach(t => { t.el.title = TOKENS_TIP; });
    const digitsNum = makeNum(st.index_digits ?? 4, 1, 12, 1, v => setState({ index_digits: v }));
    const overwriteToggle = makeToggle(st.overwrite !== false, "Overwrite: On (replace)", "Overwrite: Off",
        v => { setState({ overwrite: v }); renderSave(); });
    const renameChips = makeChips([{ val: "append", label: "Append number" }, { val: "skip", label: "Skip existing" }],
        st.rename_mode ?? "append", v => setState({ rename_mode: v }));
    const maskJpg = makeToggle(st.mask_force_jpg === true, "Mask: force JPG", "Mask: PNG (safe)",
        v => setState({ mask_force_jpg: v }));

    const fields = document.createElement("div"); fields.className = "cir-fields";
    const folderWrap = document.createElement("div"); folderWrap.append(sub("Output folder"), folderInp.el);
    const fmtWrap = document.createElement("div"); fmtWrap.append(sub("Format"), fmtChips.el);
    const nameWrap = document.createElement("div");
    nameWrap.append(sub("Name: prefix · filename · suffix (tokens)"), prefixInp.el, fnameInp.el, suffixInp.el);
    const digitsWrap = document.createElement("div"); digitsWrap.append(sub("Index digits"), digitsNum.wrap);
    const renameWrap = document.createElement("div"); renameWrap.append(sub("If file exists"), renameChips.el);
    fields.append(folderWrap, fmtWrap, nameWrap, digitsWrap, overwriteToggle.el, renameWrap, maskJpg.el);
    const saveSec = document.createElement("div"); saveSec.append(saveLabel, saveImageToggle.el, saveMaskToggle.el, saveTextToggle.el, fields);
    function renderSave() {
        const s = getState();
        const anyOn = (s.save_image !== false) || (s.save_mask !== false) || (s.save_text !== false);
        fields.style.display = anyOn ? "" : "none";
        renameWrap.style.display = (anyOn && s.overwrite === false) ? "" : "none";
        maskJpg.el.style.display = (anyOn && (s.format ?? "png") === "jpg") ? "" : "none";
        scheduleResize();
    }

    // ── Mask interpolation ─────────────────────────────────────────────────────
    const maskLabel = document.createElement("div"); maskLabel.className = "cir-label"; maskLabel.textContent = "Mask";
    const interpChips = makeChips([{ val: "nearest", label: "Nearest" }, { val: "bilinear", label: "Bilinear" }],
        st.mask_interpolation ?? "nearest", v => setState({ mask_interpolation: v }));
    const maskSec = document.createElement("div"); maskSec.append(maskLabel, interpChips.el);

    // ── Advanced (flatten / extract / merge) ───────────────────────────────────
    const advHead = document.createElement("div"); advHead.className = "cir-adv-head";
    const advTitle = document.createElement("div"); advTitle.className = "cir-label"; advTitle.style.marginBottom = "0"; advTitle.textContent = "Advanced";
    const advArrow = document.createElement("div"); advArrow.className = "cir-arrow"; advArrow.textContent = "▶";
    advHead.append(advTitle, advArrow);
    const advBody = document.createElement("div"); advBody.className = "cir-adv-body"; advBody.style.display = "none";
    const flatR = makeToggle(st.flatten_region !== false, "Region: merge detections", "Region: keep separate", v => setState({ flatten_region: v }));
    const flatA = makeToggle(st.flatten_alt !== false, "Region alt: merge", "Region alt: keep separate", v => setState({ flatten_alt: v }));
    const exItems = [{ val: "both", label: "Both" }, { val: "bbox", label: "Bbox" }, { val: "mask", label: "Mask" }];
    const exR = makeChips(exItems, st.extract_region ?? "both", v => setState({ extract_region: v }));
    const exA = makeChips(exItems, st.extract_alt ?? "both", v => setState({ extract_alt: v }));
    const mergeChips = makeChips([{ val: "union", label: "Union (cover all)" }, { val: "largest", label: "Largest only" }],
        st.merge_method ?? "union", v => setState({ merge_method: v }));
    const exRWrap = document.createElement("div"); exRWrap.append(sub("Extract — Region"), exR.el);
    const exAWrap = document.createElement("div"); exAWrap.append(sub("Extract — Region alternate"), exA.el);
    const mergeWrap = document.createElement("div"); mergeWrap.append(sub("Merge method (boxes)"), mergeChips.el);
    advBody.append(flatR.el, flatA.el, exRWrap, exAWrap, mergeWrap);
    advHead.onclick = () => { const open = advBody.style.display === "none"; advBody.style.display = open ? "" : "none"; advHead.classList.toggle("open", open); scheduleResize(); };
    const advSec = document.createElement("div"); advSec.append(advHead, advBody);

    // ── Iteration ──────────────────────────────────────────────────────────────
    const iterLabel = document.createElement("div"); iterLabel.className = "cir-label"; iterLabel.textContent = "Iteration";
    const iterToggle = makeToggle(st.iterate !== false, "Counts Toward Completion: On", "Counts Toward Completion: Off",
        v => setState({ iterate: v }));
    iterToggle.el.title = "When wired to the batch loader, instances with this on must all finish before the "
        + "loop advances one source image. Disabled (muted/bypassed) instances are not counted.";
    const iterSec = document.createElement("div"); iterSec.append(iterLabel, iterToggle.el);

    root.append(mSec, rSec, saveSec, maskSec, advSec, iterSec);

    // ── mount ──────────────────────────────────────────────────────────────────
    const measureH = () => measureRootContent(root);
    let auto = null;
    function scheduleResize() { if (auto) auto.scheduleRelayout(); }
    const _w = node.addDOMWidget("tp_ui", "custom", root, {
        getValue: () => null, setValue: () => {}, serialize: false,
        getMinHeight: measureH, getMaxHeight: measureH, margin: 4,
    });
    applyAdaptiveCanvasOnly(_w);
    if (_w?.element) { _w.element.style.width = "100%"; _w.element.style.boxSizing = "border-box"; }
    const _W = Math.max(node.size?.[0] ?? 0, 340);
    if (typeof node.setSize === "function") node.setSize([_W, node.size?.[1] ?? 120]);
    else if (node.size) node.size[0] = _W;
    auto = attachAutoHeight(node, root, _w);
    renderRegion(); renderSave();
    const _onr = node.onRemoved;
    node.onRemoved = function() { auto.dispose(); return _onr?.apply(this, arguments); };

    function syncUI() {
        const s = getState();
        shapeChips.setActive(s.shape_mode ?? "exact");
        aspSrc.setActive(s.aspect_source ?? "bbox");
        ratioW.setValue(s.shape_ratio_w ?? 1); ratioH.setValue(s.shape_ratio_h ?? 1);
        minToggle.setValue(s.min_crop_on === true); minNum.setValue(s.min_crop_size ?? (s.target_size ?? 1024));
        padNum.setValue(s.padding ?? 10); unitChips.setActive(s.padding_unit ?? "percentage");
        saveImageToggle.setValue(s.save_image !== false);
        saveMaskToggle.setValue(s.save_mask !== false);
        saveTextToggle.setValue(s.save_text !== false);
        folderInp.setValue(s.output_folder ?? "training_data");
        fmtChips.setActive(s.format ?? "png");
        prefixInp.setValue(s.prefix ?? ""); fnameInp.setValue(s.filename ?? "{filename}"); suffixInp.setValue(s.suffix ?? "_{segs}");
        digitsNum.setValue(s.index_digits ?? 4);
        overwriteToggle.setValue(s.overwrite !== false); renameChips.setActive(s.rename_mode ?? "append");
        maskJpg.setValue(s.mask_force_jpg === true);
        interpChips.setActive(s.mask_interpolation ?? "nearest");
        flatR.setValue(s.flatten_region !== false); flatA.setValue(s.flatten_alt !== false);
        exR.setActive(s.extract_region ?? "both"); exA.setActive(s.extract_alt ?? "both");
        mergeChips.setActive(s.merge_method ?? "union");
        iterToggle.setValue(s.iterate !== false);
        refreshScale(); renderRegion(); renderSave(); scheduleResize();
    }
    const _ocfg = node.onConfigure;
    node.onConfigure = function() { const r = _ocfg?.apply(this, arguments); syncUI(); return r; };
}

app.registerExtension({
    name: "UNP.UmbraeTrainingPrep",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;
        const _onc = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function() { _onc?.apply(this, arguments); setupNode(this); };

        // ── completion loop (disabled-node fix) ────────────────────────────────
        const _oe = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function(message) {
            _oe?.apply(this, arguments);
            if (this.properties?.tpState?.iterate === false) return;
            if (this.mode !== 0 && this.mode != null) return;   // a disabled instance doesn't report

            // Only ENABLED (active) instances count — muted/bypassed nodes don't
            // execute, so counting them would stall/desync the loop.
            const expected = (app.graph?._nodes ?? []).filter(n =>
                (n.type === NODE_TYPE || n.comfyClass === NODE_TYPE) &&
                (n.mode === 0 || n.mode == null) &&
                n.properties?.tpState?.iterate !== false
            ).length;
            if (expected <= 0) return;

            app._unpTPCompleted = (app._unpTPCompleted ?? 0) + 1;
            if (app._unpTPCompleted < expected) return;
            app._unpTPCompleted = 0;

            const count = app._unpBatchFileCount ?? 0;
            if (count <= 0) return;
            const loader = app.graph?._nodes?.find(n =>
                n.type === "LoadImagesUniformBatch" || n.comfyClass === "LoadImagesUniformBatch" ||
                n.properties?.lbuState !== undefined);
            if (!loader) return;
            const idxWidget = loader.widgets?.find(w => w.name === "image_index");
            if (!idxWidget) return;

            const widgetVal = parseInt(idxWidget.value) || 0;
            if (app._unpCurrentIndex === undefined || widgetVal !== app._unpCurrentIndex)
                app._unpCurrentIndex = widgetVal;
            const current = app._unpCurrentIndex;

            if (current >= count - 1) {
                app._unpCurrentIndex = 0; idxWidget.value = 0;
                app._unpNextImageIndex = 0; app._unpBatchFileCount = 0;
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
        entry.inputs.ui_state = JSON.stringify(node.properties?.tpState ?? {});
    }
    return result;
};
