import { app } from "../../scripts/app.js";
import { requestAdvance } from "./umbrae_loop.js";
import { buildScaleSection } from "./umbrae_scale.js";
import { measureRootContent, attachAutoHeight, applyAdaptiveCanvasOnly } from "./umbrae_resize.js";
import { injectTheme, applyNodeColors } from "./umbrae_theme.js";
import { createNumber, createPillRow, createToggle, createText, createLabel as sub } from "./umbrae_components.js";

const NODE_TYPE = "UmbraeTrainingPrep";
const TOKENS_TIP = "Tokens: {stem} (source name) · {segs} (segment label) · {index} (per-image counter) "
    + "· {ext} · {w} · {h} · {folder}. A token with no data resolves to NODATA.";


function setupNode(node) {
    injectTheme();
    applyNodeColors(node);

    function getState() { return node.properties?.tpState ?? {}; }
    function setState(patch) { if (!node.properties) node.properties = {}; node.properties.tpState = { ...getState(), ...patch }; }

    const st = getState();
    const root = document.createElement("div"); root.className = "ud-root ud-ruled";

    // ── Scale ──────────────────────────────────────────────────────────────────
    const { root: scaleRoot, refresh: refreshScale } = buildScaleSection(
        node, () => getState(), (_n, p) => setState(p),
        { showUniform: false, onChange: () => scheduleResize(), isBboxConnected: () => false, hideModes: ["BBOX"],
          modeTitle: "Output size (after crop) — Off = crop only" });
    const mSec = document.createElement("div"); mSec.append(scaleRoot);
    // The Region (crop) controls only matter once a box / mask is wired in;
    // unwired, this node is a plain saver and shows no crop controls.
    function regionWired() {
        return ["region", "region_alternate"].some(n => {
            const i = node.findInputSlot ? node.findInputSlot(n) : -1;
            return i >= 0 && node.inputs?.[i]?.link != null;
        });
    }
    const _occ = node.onConnectionsChange;
    node.onConnectionsChange = function() { refreshScale(); renderRegion(); return _occ?.apply(this, arguments); };

    // ── Region shaping ─────────────────────────────────────────────────────────
    const rLabel = document.createElement("div"); rLabel.className = "ud-title"; rLabel.textContent = "Region";
    const shapeChips = createPillRow([{ val: "exact", label: "Exact bbox" }, { val: "aspect", label: "Shape to aspect" }],
        st.shape_mode ?? "exact", v => { setState({ shape_mode: v }); renderRegion(); });
    const aspSrc = createPillRow([{ val: "bbox", label: "Bbox" }, { val: "image", label: "Image" }, { val: "user", label: "User" }],
        st.aspect_source ?? "bbox", v => { setState({ aspect_source: v }); renderRegion(); });
    const aspWrap = document.createElement("div"); aspWrap.append(sub("Aspect source"), aspSrc.el);
    const ratioRow = document.createElement("div"); ratioRow.className = "ud-padrow";
    const ratioW = createNumber(st.shape_ratio_w ?? 1, 0.01, 100, 0.1, v => setState({ shape_ratio_w: v }));
    const ratioH = createNumber(st.shape_ratio_h ?? 1, 0.01, 100, 0.1, v => setState({ shape_ratio_h: v }));
    ratioRow.append(ratioW.el, ratioH.el);
    const ratioWrap = document.createElement("div"); ratioWrap.append(sub("Aspect ratio (w : h)"), ratioRow);
    const minToggle = createToggle(st.min_crop_on === true, "Minimum crop size: On", "Minimum crop size: Off",
        v => { setState({ min_crop_on: v }); renderRegion(); });
    const minNum = createNumber(st.min_crop_size ?? (st.target_size ?? 1024), 8, 16384, 8, v => setState({ min_crop_size: v }));
    const minWrap = document.createElement("div"); minWrap.append(sub("Minimum short edge (px)"), minNum.el);
    const maxToggle = createToggle(st.max_crop_on === true, "Maximum crop size: On", "Maximum crop size: Off",
        v => { setState({ max_crop_on: v }); renderRegion(); });
    maxToggle.el.title = "After cropping and resizing, downscale the crop so its long edge is at most this. "
        + "Never enlarges. Same as the Bbox mode's Max on the save node.";
    const maxNum = createNumber(st.max_crop_size ?? 2048, 8, 16384, 8, v => setState({ max_crop_size: v }));
    const maxWrap = document.createElement("div"); maxWrap.append(sub("Maximum long edge (px)"), maxNum.el);
    const padRow = document.createElement("div"); padRow.className = "ud-padrow";
    const padNum = createNumber(st.padding ?? 10, 0, 100000, 1, v => setState({ padding: v })); padNum.el.className += " ud-grow";
    const unitChips = createPillRow([{ val: "percentage", label: "%" }, { val: "pixels", label: "px" }],
        st.padding_unit ?? "percentage", v => setState({ padding_unit: v }));
    const padUnit = document.createElement("div"); padUnit.className = "ud-unit"; padUnit.append(unitChips.el);
    padRow.append(padNum.el, padUnit);
    const padWrap = document.createElement("div"); padWrap.append(sub("Padding"), padRow);
    const rSec = document.createElement("div");
    rSec.append(rLabel, shapeChips.el, aspWrap, ratioWrap, minToggle.el, minWrap, maxToggle.el, maxWrap, padWrap);
    function renderRegion() {
        const s = getState();
        rSec.style.display = regionWired() ? "" : "none";
        const isA = (s.shape_mode ?? "exact") === "aspect";
        aspWrap.style.display = isA ? "" : "none";
        ratioWrap.style.display = (isA && (s.aspect_source ?? "bbox") === "user") ? "" : "none";
        minWrap.style.display = (s.min_crop_on === true) ? "" : "none";
        maxWrap.style.display = (s.max_crop_on === true) ? "" : "none";
        scheduleResize();
    }

    // ── Save ───────────────────────────────────────────────────────────────────
    const saveLabel = document.createElement("div"); saveLabel.className = "ud-title"; saveLabel.textContent = "Save";
    const saveImageToggle = createToggle(st.save_image !== false, "Save Image: On", "Save Image: Off",
        v => { setState({ save_image: v }); renderSave(); });
    const saveMaskToggle = createToggle(st.save_mask !== false, "Save Mask: On", "Save Mask: Off",
        v => { setState({ save_mask: v }); renderSave(); });
    saveMaskToggle.el.title = "Writes the cropped mask to a masks/ subfolder, sharing the image's filename. Only acts when a mask is present.";
    const saveTextToggle = createToggle(st.save_text !== false, "Save Text: On", "Save Text: Off",
        v => { setState({ save_text: v }); renderSave(); });
    saveTextToggle.el.title = "Writes the wired caption to <stem>.txt next to the image. Only acts when a caption is connected.";
    const folderInp = createText(st.output_folder ?? "training_data", "training_data", v => setState({ output_folder: v }));
    const fmtChips = createPillRow([{ val: "png", label: "PNG" }, { val: "jpg", label: "JPG" }, { val: "webp", label: "WebP" }],
        st.format ?? "png", v => { setState({ format: v }); renderSave(); });
    const prefixInp = createText(st.prefix ?? "", "prefix", v => setState({ prefix: v }));
    const fnameInp  = createText(st.filename ?? "{filename}", "{filename}", v => setState({ filename: v }));
    const suffixInp = createText(st.suffix ?? "_{segs}", "_{segs}", v => setState({ suffix: v }));
    [prefixInp, fnameInp, suffixInp].forEach(t => { t.el.title = TOKENS_TIP; });
    const digitsNum = createNumber(st.index_digits ?? 4, 1, 12, 1, v => setState({ index_digits: v }));
    const overwriteToggle = createToggle(st.overwrite !== false, "Overwrite: On (replace)", "Overwrite: Off",
        v => { setState({ overwrite: v }); renderSave(); });
    const renameChips = createPillRow([{ val: "append", label: "Append number" }, { val: "skip", label: "Skip existing" }],
        st.rename_mode ?? "append", v => setState({ rename_mode: v }));
    const maskJpg = createToggle(st.mask_force_jpg === true, "Mask: force JPG", "Mask: PNG (safe)",
        v => setState({ mask_force_jpg: v }));

    const fields = document.createElement("div"); fields.className = "ud-stack";
    const folderWrap = document.createElement("div"); folderWrap.append(sub("Output folder"), folderInp.el);
    const qualityNum = createNumber(st.quality ?? 95, 1, 100, 1, v => setState({ quality: v }),
        { tooltip: "JPG / WebP quality (1-100). Higher = larger file, fewer artifacts. Ignored for PNG." });
    const qualityWrap = document.createElement("div"); qualityWrap.append(sub("Quality (JPG / WebP)"), qualityNum.el);
    const fmtWrap = document.createElement("div"); fmtWrap.append(sub("Format"), fmtChips.el, qualityWrap);
    const nameWrap = document.createElement("div");
    nameWrap.append(sub("Name: prefix · filename · suffix (tokens)"), prefixInp.el, fnameInp.el, suffixInp.el);
    const digitsWrap = document.createElement("div"); digitsWrap.append(sub("Index digits"), digitsNum.el);
    const renameWrap = document.createElement("div"); renameWrap.append(sub("If file exists"), renameChips.el);
    fields.append(folderWrap, fmtWrap, nameWrap, digitsWrap, overwriteToggle.el, renameWrap, maskJpg.el);
    const saveSec = document.createElement("div"); saveSec.append(saveLabel, saveImageToggle.el, saveMaskToggle.el, saveTextToggle.el, fields);
    function renderSave() {
        const s = getState();
        const anyOn = (s.save_image !== false) || (s.save_mask !== false) || (s.save_text !== false);
        fields.style.display = anyOn ? "" : "none";
        renameWrap.style.display = (anyOn && s.overwrite === false) ? "" : "none";
        qualityWrap.style.display = (s.format ?? "png") === "png" ? "none" : "";
        maskJpg.el.style.display = (anyOn && (s.format ?? "png") === "jpg") ? "" : "none";
        scheduleResize();
    }

    // ── Mask interpolation ─────────────────────────────────────────────────────
    const maskLabel = document.createElement("div"); maskLabel.className = "ud-title"; maskLabel.textContent = "Mask";
    const interpChips = createPillRow([{ val: "nearest", label: "Nearest" }, { val: "bilinear", label: "Bilinear" }],
        st.mask_interpolation ?? "nearest", v => setState({ mask_interpolation: v }));
    const maskSec = document.createElement("div"); maskSec.append(maskLabel, interpChips.el);

    // ── Advanced (flatten / extract / merge) ───────────────────────────────────
    const advHead = document.createElement("div"); advHead.className = "ud-adv-head";
    const advTitle = document.createElement("div"); advTitle.className = "ud-title"; advTitle.style.marginBottom = "0"; advTitle.textContent = "Advanced";
    const advArrow = document.createElement("div"); advArrow.className = "ud-adv-arrow"; advArrow.textContent = "▶";
    advHead.append(advTitle, advArrow);
    const advBody = document.createElement("div"); advBody.className = "ud-stack"; advBody.style.display = "none";
    const flatR = createToggle(st.flatten_region !== false, "Region: merge detections", "Region: keep separate", v => setState({ flatten_region: v }));
    const flatA = createToggle(st.flatten_alt !== false, "Region alt: merge", "Region alt: keep separate", v => setState({ flatten_alt: v }));
    const exItems = [{ val: "both", label: "Both" }, { val: "bbox", label: "Bbox" }, { val: "mask", label: "Mask" }];
    const exR = createPillRow(exItems, st.extract_region ?? "both", v => setState({ extract_region: v }));
    const exA = createPillRow(exItems, st.extract_alt ?? "both", v => setState({ extract_alt: v }));
    const mergeChips = createPillRow([{ val: "union", label: "Union (cover all)" }, { val: "largest", label: "Largest only" }],
        st.merge_method ?? "union", v => setState({ merge_method: v }));
    const exRWrap = document.createElement("div"); exRWrap.append(sub("Extract — Region"), exR.el);
    const exAWrap = document.createElement("div"); exAWrap.append(sub("Extract — Region alternate"), exA.el);
    const mergeWrap = document.createElement("div"); mergeWrap.append(sub("Merge method (boxes)"), mergeChips.el);
    advBody.append(flatR.el, flatA.el, exRWrap, exAWrap, mergeWrap);
    advHead.onclick = () => { const open = advBody.style.display === "none"; advBody.style.display = open ? "" : "none"; advHead.classList.toggle("open", open); scheduleResize(); };
    const advSec = document.createElement("div"); advSec.append(advHead, advBody);

    // ── Iteration ──────────────────────────────────────────────────────────────
    const iterLabel = document.createElement("div"); iterLabel.className = "ud-title"; iterLabel.textContent = "Iteration";
    const iterToggle = createToggle(st.iterate !== false, "Counts Toward Completion: On", "Counts Toward Completion: Off",
        v => setState({ iterate: v }));
    iterToggle.el.title = "When wired to the batch loader, instances with this on must all finish before the "
        + "loop advances one source image. Disabled (muted/bypassed) instances are not counted.";
    const iterSec = document.createElement("div"); iterSec.append(iterLabel, iterToggle.el);

    root.append(rSec, mSec, saveSec, maskSec, advSec, iterSec);

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
        maxToggle.setValue(s.max_crop_on === true); maxNum.setValue(s.max_crop_size ?? 2048);
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
        nodeType.prototype.onNodeCreated = function() {
            _onc?.apply(this, arguments);
            if (!this.properties) this.properties = {};
            if (!this.properties.tpState) this.properties.tpState = { resize_mode: "OFF" };
            setupNode(this);
        };

        // ── completion loop: umbrae_loop.js steps the loader once per finished
        // run, however many iteration nodes the graph has. A disabled instance
        // never executes, so it never asks; the controller waits for the whole
        // prompt, so every enabled instance has run by the time it steps.
        const _oe = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function(message) {
            _oe?.apply(this, arguments);
            if (this.properties?.tpState?.iterate === false) return;
            requestAdvance();
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
