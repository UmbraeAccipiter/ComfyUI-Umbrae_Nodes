// umbrae_scale.js
// Shared "Resize Mode / Size / Crop Behavior / Anchor / Scale & Batch /
// Advanced" section, used identically by LoadImagesUniformBatch,
// CropImageRegion and SaveImageSmart. Rebuilt on the umbrae framework
// (flat single surface, one blue accent). Same API and the same ui_state
// keys as the original buildScaleSection — only the look changed.

import { injectTheme } from "./umbrae_theme.js";

const SCALE_STYLE_ID = "umbrae-scale-v1";

const MODES = [
    { id: "OFF",          lbl: "Off",          tip: "Pass through unchanged — no resize at all." },
    { id: "LARGEST_EDGE", lbl: "Largest Edge", tip: "Resize so max(W,H) = size, keeping aspect ratio. No padding." },
    { id: "SMALLEST_EDGE", lbl: "Smallest Edge", tip: "Resize so min(W,H) = size, keeping aspect ratio. With direction Up this floors the short edge at the size (training minimum). No padding." },
    { id: "MAX_MP",       lbl: "Max MP",       tip: "Scale so total pixels stay under a megapixel cap, keeping aspect ratio." },
    { id: "FIT_AND_PAD",  lbl: "Fit & Pad",    tip: "Fit within W×H preserving aspect, pad with black bars." },
    { id: "CROP",         lbl: "Crop",         tip: "Scale and/or crop to W×H — configure Fill/Crop below." },
    { id: "FORCE_EXACT",  lbl: "Exact",        tip: "Stretch to exact W×H (may distort)." },
];
const DIRECTION_OPTS  = ["down", "up", "both"];
const DIRECTION_LABEL = { down: "\u2193 Down", up: "\u2191 Up", both: "\u2195 Both" };
const DIRECTION_TITLE = {
    down: "Downscale Only — never enlarge an image smaller than the target.",
    up:   "Upscale Only — never shrink a larger image; only enlarges undersized ones.",
    both: "Both — always scale exactly to the target.",
};
const GRID_CELLS = [
    "top-left", "top", "top-right",
    "left", "center", "right",
    "bottom-left", "bottom", "bottom-right",
];
const RATIO_PRESETS = [
    { w: 1, h: 1, lbl: "1:1" }, { w: 16, h: 9, lbl: "16:9" }, { w: 9, h: 16, lbl: "9:16" },
    { w: 4, h: 5, lbl: "4:5" }, { w: 3, h: 2, lbl: "3:2" }, { w: 21, h: 9, lbl: "21:9" },
];
const ANCHOR_MODES = [
    { id: "grid", lbl: "Grid" }, { id: "face", lbl: "Face" },
    { id: "entropy", lbl: "Entropy" }, { id: "xy", lbl: "XY" },
];

// Displayed defaults of the scale panel. Used only when a host opts into
// seedDefaults, to persist what the panel shows (fills MISSING keys only).
const SCALE_DEFAULTS = {
    resize_mode: "LARGEST_EDGE", target_size: 1024, max_mp: 1.0,
    width: 1024, height: 1024, ratio_w: 1, ratio_h: 1,
    fill: true, crop_on: true,
    anchor_mode: "grid", anchor_grid: "center", anchor_xy: [0.5, 0.5],
    scale_direction: "down",
    torso_bias: 0.0, headroom: -0.20, face_margin_pct: 0.22,
    top_guard_pct: 0.16, face_top_guard_pct: 0.25,
    min_face_frac: 0.06, max_face_frac: 0.55,
    reject_too_low_faces: true, too_low_threshold_pct: 0.74,
    fallback_if_no_face: "entropy", speed_mode: "balanced",
};

function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
}

function injectScaleCSS() {
    if (document.getElementById(SCALE_STYLE_ID)) return;
    const a = "var(--ud-accent, #7aa8d4)";
    const inset = "var(--ud-inset, #202020)";
    const border = "var(--ud-border, #3a3a3a)";
    const text = "var(--ud-text, #ddd)";
    const dim = "var(--ud-text-dim, #888)";
    const s = document.createElement("style");
    s.id = SCALE_STYLE_ID;
    s.textContent = `
.us-root { display:flex; flex-direction:column; gap:10px; }
.us-section { display:flex; flex-direction:column; gap:6px; }
.us-title { font-size:9px; font-weight:700; letter-spacing:.07em; text-transform:uppercase; color:${a}; }
.us-chips { display:flex; flex-wrap:wrap; gap:4px; }
.us-chip { flex:0 1 auto; padding:4px 9px; border-radius:4px; background:${inset};
    border:1px solid ${border}; font-size:10px; color:${dim}; cursor:pointer; user-select:none; white-space:nowrap; transition:all .12s; }
.us-chip:hover { color:${text}; }
.us-chip.on { background:${a}; border-color:${a}; color:#fff; font-weight:600; }
.us-chip-sm { padding:3px 7px; font-size:10px; }
.us-size-row { display:flex; flex-wrap:wrap; gap:8px; }
.us-size-grp { display:flex; flex-direction:column; gap:2px; min-width:54px; flex:1; }
.us-size-lbl { font-size:9px; color:${dim}; }
.us-size-inp { background:${inset}; border:1px solid ${border}; border-radius:4px; color:${a};
    font-size:11px; font-weight:600; padding:3px 5px; width:100%; box-sizing:border-box; text-align:center; }
.us-size-inp:focus { outline:none; border-color:${a}; }
.us-toggle-row { display:flex; gap:6px; }
.us-pill { flex:1; padding:5px 12px; border-radius:4px; background:${inset}; border:1px solid ${border};
    font-size:11px; color:${dim}; cursor:pointer; user-select:none; text-align:center; transition:all .12s; }
.us-pill.on { background:${a}; border-color:${a}; color:#fff; font-weight:600; }
.us-grid { display:grid; grid-template-columns:repeat(3,1fr); grid-template-rows:repeat(3,1fr); gap:3px;
    width:100%; max-width:96px; aspect-ratio:1; margin:2px auto; background:${inset}; border:1px solid ${border};
    border-radius:5px; padding:5px; box-sizing:border-box; }
.us-cell { background:#2e2e2e; border-radius:3px; cursor:pointer; }
.us-cell:hover { background:#3a3a3a; }
.us-cell.active { background:${a}; }
.us-batch-row { display:flex; gap:8px; }
.us-adv-header { display:flex; align-items:center; gap:5px; cursor:pointer; user-select:none;
    font-size:9px; font-weight:700; letter-spacing:.07em; text-transform:uppercase; color:${a}; }
.us-adv-caret { font-size:8px; color:${dim}; transition:transform .15s; }
.us-adv-body { display:flex; flex-direction:column; gap:6px; padding-top:4px; }
.us-adv-row { display:flex; align-items:center; justify-content:space-between; gap:8px; }
.us-adv-lbl { font-size:10px; color:${dim}; flex:1; }
.us-adv-num, .us-adv-select { max-width:96px; background:${inset}; border:1px solid ${border};
    border-radius:4px; color:${text}; font-size:11px; padding:3px 5px; box-sizing:border-box; }
.us-adv-num:focus, .us-adv-select:focus { outline:none; border-color:${a}; }
.us-adv-checkbox { width:14px; height:14px; accent-color:${a}; }
.us-disabled { opacity:.4; pointer-events:none; }
.us-note { font-size:9px; color:${dim}; font-style:italic; }
`;
    document.head.appendChild(s);
}

function sizeGroup(label, defVal, min, max, step) {
    const g = el("div", "us-size-grp");
    const l = el("div", "us-size-lbl", label);
    const i = document.createElement("input");
    i.type = "number"; i.className = "us-size-inp"; i.value = defVal;
    i.min = min; i.max = max; i.step = step;
    g.append(l, i);
    return { g, i };
}

export function buildScaleSection(node, getState, patchState, opts = {}) {
    injectTheme();
    injectScaleCSS();
    const { onChange = () => {}, showUniform = true, isBboxConnected = () => false, seedDefaults = false } = opts;
    const root = el("div", "us-root");
    const emit = () => onChange();

    // ── Resize Mode ──────────────────────────────────────────
    const modeSection = el("div", "us-section");
    modeSection.append(el("div", "us-title", "Resize Mode"));
    const modeRow = el("div", "us-chips");
    const modeChips = {};
    MODES.forEach(({ id, lbl, tip }) => {
        const c = el("div", "us-chip", lbl); c.title = tip;
        c.addEventListener("click", (e) => { e.stopPropagation(); patchState(node, { resize_mode: id }); refresh(); emit(); });
        modeRow.appendChild(c); modeChips[id] = c;
    });
    modeSection.append(modeRow);

    // ── Size ─────────────────────────────────────────────────
    const sizeSection = el("div", "us-section");
    sizeSection.append(el("div", "us-title", "Size"));
    const sizeRow = el("div", "us-size-row");
    const sz1 = sizeGroup("Size", 1024, 8, 8192, 8);
    const szMP = sizeGroup("MP", 1.0, 0.1, 64, 0.1);
    const szW = sizeGroup("W", 1024, 8, 8192, 8);
    const szH = sizeGroup("H", 1024, 8, 8192, 8);
    const szRatioW = sizeGroup("W", 1, 1, 99, 1);
    const szRatioH = sizeGroup("H", 1, 1, 99, 1);
    sizeRow.append(sz1.g, szMP.g, szW.g, szH.g, szRatioW.g, szRatioH.g);
    sizeSection.append(sizeRow);

    const ratioPresetRow = el("div", "us-chips");
    RATIO_PRESETS.forEach(({ w, h, lbl }) => {
        const c = el("div", "us-chip us-chip-sm", lbl);
        c.addEventListener("click", (e) => { e.stopPropagation(); patchState(node, { ratio_w: w, ratio_h: h }); refresh(); emit(); });
        ratioPresetRow.appendChild(c);
    });
    sizeSection.append(ratioPresetRow);

    [sz1.i, szMP.i, szW.i, szH.i].forEach((inp) => inp.addEventListener("change", (e) => {
        e.stopPropagation();
        const mode = (getState(node).resize_mode || "LARGEST_EDGE").toUpperCase();
        if (mode === "LARGEST_EDGE" || mode === "SMALLEST_EDGE") patchState(node, { target_size: Math.max(8, parseInt(sz1.i.value) || 1024) });
        else if (mode === "MAX_MP") patchState(node, { max_mp: Math.max(0.1, parseFloat(szMP.i.value) || 1.0) });
        else patchState(node, { width: Math.max(8, parseInt(szW.i.value) || 1024), height: Math.max(8, parseInt(szH.i.value) || 1024) });
        refresh(); emit();
    }));
    [szRatioW.i, szRatioH.i].forEach((inp) => inp.addEventListener("change", (e) => {
        e.stopPropagation();
        patchState(node, { ratio_w: Math.max(1, parseInt(szRatioW.i.value) || 1), ratio_h: Math.max(1, parseInt(szRatioH.i.value) || 1) });
        refresh(); emit();
    }));

    // ── Crop Behavior (CROP mode only) ───────────────────────
    const fcSection = el("div", "us-section");
    fcSection.append(el("div", "us-title", "Crop Behavior"));
    const fcRow = el("div", "us-toggle-row");
    const fillToggle = el("div", "us-pill", "Fill");
    fillToggle.title = "Scale to cover the target box (may overflow one axis if Crop is off).";
    const cropToggle = el("div", "us-pill", "Crop");
    cropToggle.title = "Crop so output matches the target exactly (or, with Fill off, crop to a ratio at native resolution).";
    fcRow.append(fillToggle, cropToggle);
    fcSection.append(fcRow);
    fillToggle.addEventListener("click", (e) => { e.stopPropagation(); patchState(node, { fill: !(getState(node).fill !== false) }); refresh(); emit(); });
    cropToggle.addEventListener("click", (e) => { e.stopPropagation(); patchState(node, { crop_on: !(getState(node).crop_on !== false) }); refresh(); emit(); });

    // ── Anchor ───────────────────────────────────────────────
    const anchorSection = el("div", "us-section");
    anchorSection.append(el("div", "us-title", "Anchor"));
    const overrideNote = el("div", "us-note", "Overridden by connected bbox — disconnect it to use these.");
    overrideNote.style.display = "none";
    anchorSection.append(overrideNote);
    const anchorModeRow = el("div", "us-chips");
    const anchorChips = {};
    ANCHOR_MODES.forEach(({ id, lbl }) => {
        const c = el("div", "us-chip us-chip-sm", lbl);
        c.addEventListener("click", (e) => { e.stopPropagation(); patchState(node, { anchor_mode: id }); refresh(); emit(); });
        anchorModeRow.appendChild(c); anchorChips[id] = c;
    });
    anchorSection.append(anchorModeRow);

    const gridWrap = el("div", "us-grid");
    const gridCells = {};
    GRID_CELLS.forEach((g) => {
        const cell = el("div", "us-cell");
        cell.title = g.replace("-", " ");
        cell.addEventListener("click", (e) => { e.stopPropagation(); patchState(node, { anchor_grid: g }); refresh(); emit(); });
        gridWrap.appendChild(cell); gridCells[g] = cell;
    });
    anchorSection.append(gridWrap);

    const xyRow = el("div", "us-size-row");
    const xyX = sizeGroup("X", 0.5, 0, 1, 0.05);
    const xyY = sizeGroup("Y", 0.5, 0, 1, 0.05);
    xyRow.append(xyX.g, xyY.g);
    anchorSection.append(xyRow);
    [xyX.i, xyY.i].forEach((inp) => inp.addEventListener("change", (e) => {
        e.stopPropagation();
        const x = Math.min(1, Math.max(0, parseFloat(xyX.i.value) || 0.5));
        const y = Math.min(1, Math.max(0, parseFloat(xyY.i.value) || 0.5));
        patchState(node, { anchor_xy: [x, y] }); refresh(); emit();
    }));

    // ── Scale & Batch ────────────────────────────────────────
    const qSection = el("div", "us-section");
    qSection.append(el("div", "us-title", "Scale & Batch"));
    const qRow = el("div", "us-batch-row");
    const dirBtn = el("div", "us-pill", "\u2193 Down");
    qRow.append(dirBtn);
    let uniBtn = null;
    if (showUniform) {
        uniBtn = el("div", "us-pill", "Uniform: On");
        uniBtn.title = "Pad images to a common size so the batch tensor is uniform. Turn off when processing one image at a time.";
        qRow.append(uniBtn);
    }
    qSection.append(qRow);
    dirBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const i = (DIRECTION_OPTS.indexOf(getState(node).scale_direction || "down") + 1) % DIRECTION_OPTS.length;
        patchState(node, { scale_direction: DIRECTION_OPTS[i] }); refresh(); emit();
    });
    if (uniBtn) uniBtn.addEventListener("click", (e) => { e.stopPropagation(); patchState(node, { uniform_batch: getState(node).uniform_batch === false }); refresh(); emit(); });

    // ── Advanced (collapsed) ─────────────────────────────────
    const advSection = el("div", "us-section");
    const advHeader = el("div", "us-adv-header");
    const advCaret = el("span", "us-adv-caret", "\u25B8");
    advHeader.append(advCaret, el("span", "", "Advanced"));
    const advBody = el("div", "us-adv-body");
    advBody.style.display = "none";
    advSection.append(advHeader, advBody);
    let advOpen = false;
    advHeader.addEventListener("click", (e) => {
        e.stopPropagation();
        advOpen = !advOpen;
        advBody.style.display = advOpen ? "" : "none";
        advCaret.textContent = advOpen ? "\u25BE" : "\u25B8";
        emit();
    });

    function advField(label, key, type, fopts = {}) {
        const row = el("div", "us-adv-row");
        row.append(el("div", "us-adv-lbl", label));
        let input;
        if (type === "select") {
            input = document.createElement("select"); input.className = "us-adv-select";
            (fopts.options || []).forEach((o) => { const op = document.createElement("option"); op.value = o; op.textContent = o; input.appendChild(op); });
        } else if (type === "checkbox") {
            input = document.createElement("input"); input.type = "checkbox"; input.className = "us-adv-checkbox";
        } else {
            input = document.createElement("input"); input.type = "number"; input.className = "us-adv-num";
            if (fopts.min !== undefined) input.min = fopts.min;
            if (fopts.max !== undefined) input.max = fopts.max;
            input.step = fopts.step ?? 0.01;
        }
        if (fopts.tip) row.title = fopts.tip;
        row.append(input); advBody.append(row);
        input.addEventListener("change", (e) => {
            e.stopPropagation();
            let val;
            if (type === "checkbox") val = input.checked;
            else if (type === "select") val = input.value;
            else val = parseFloat(input.value);
            patchState(node, { [key]: val }); refresh(); emit();
        });
        return input;
    }

    const fTorsoBias    = advField("Torso Bias", "torso_bias", "number", { min: -0.5, max: 0.5, step: 0.01, tip: "Shift the crop toward the torso below a detected face." });
    const fHeadroom     = advField("Headroom", "headroom", "number", { min: -0.5, max: 0.5, step: 0.01, tip: "Vertical bias around a detected face; negative pulls up." });
    const fFaceMargin   = advField("Face Margin %", "face_margin_pct", "number", { min: 0, max: 0.5, step: 0.01, tip: "Padding kept around a detected face, as a fraction of face size." });
    const fTopGuard     = advField("Top Guard %", "top_guard_pct", "number", { min: 0, max: 0.3, step: 0.01, tip: "Minimum empty margin kept at the top of the crop." });
    const fFaceTopGuard = advField("Face Top Guard %", "face_top_guard_pct", "number", { min: 0, max: 0.7, step: 0.01, tip: "Top guard applied specifically when a face anchors the crop." });
    const fMinFace      = advField("Min Face Frac", "min_face_frac", "number", { min: 0.01, max: 0.5, step: 0.01, tip: "Ignore detected faces smaller than this fraction of the image." });
    const fMaxFace      = advField("Max Face Frac", "max_face_frac", "number", { min: 0.1, max: 0.95, step: 0.01, tip: "Ignore detected faces larger than this fraction of the image." });
    const fTooLowRej    = advField("Reject Too-Low Faces", "reject_too_low_faces", "checkbox", { tip: "Ignore faces sitting very low in the frame (often false positives)." });
    const fTooLowThr    = advField("Too-Low Threshold %", "too_low_threshold_pct", "number", { min: 0.5, max: 0.95, step: 0.01, tip: "How low a face must sit to be rejected." });
    const fFallback     = advField("Fallback (no face)", "fallback_if_no_face", "select", { options: ["entropy", "center"], tip: "Anchor used when no face is found." });
    const fSpeed        = advField("Speed", "speed_mode", "select", { options: ["fast", "balanced", "quality"], tip: "Detection/entropy quality vs speed tradeoff." });

    root.append(modeSection, sizeSection, fcSection, anchorSection, qSection, advSection);

    function refresh() {
        const st = getState(node);
        const mode = (st.resize_mode || "LARGEST_EDGE").toUpperCase();
        Object.entries(modeChips).forEach(([id, c]) => c.classList.toggle("on", id === mode));

        const fill = st.fill !== false;
        const cropOn = st.crop_on !== false;
        const isRatioOnly = mode === "CROP" && !fill && cropOn;
        const isBoxMode = mode === "FIT_AND_PAD" || mode === "FORCE_EXACT" || (mode === "CROP" && !isRatioOnly);

        sz1.g.style.display  = (mode === "LARGEST_EDGE" || mode === "SMALLEST_EDGE") ? "" : "none";
        szMP.g.style.display = mode === "MAX_MP" ? "" : "none";
        szW.g.style.display = szH.g.style.display = isBoxMode ? "" : "none";
        szRatioW.g.style.display = szRatioH.g.style.display = isRatioOnly ? "" : "none";
        ratioPresetRow.style.display = isRatioOnly ? "" : "none";
        sizeSection.style.display = mode === "OFF" ? "none" : "";

        sz1.i.value = st.target_size ?? 1024;
        szMP.i.value = st.max_mp ?? 1.0;
        szW.i.value = st.width ?? 1024;
        szH.i.value = st.height ?? 1024;
        szRatioW.i.value = st.ratio_w ?? 1;
        szRatioH.i.value = st.ratio_h ?? 1;

        fcSection.style.display = mode === "CROP" ? "" : "none";
        fillToggle.classList.toggle("on", fill);
        cropToggle.classList.toggle("on", cropOn);

        const cropsAtAll = mode === "CROP" && cropOn;
        anchorSection.style.display = cropsAtAll ? "" : "none";
        const bboxConnected = !!isBboxConnected();
        overrideNote.style.display = (cropsAtAll && bboxConnected) ? "" : "none";
        anchorModeRow.classList.toggle("us-disabled", bboxConnected);
        const anchorMode = st.anchor_mode || "grid";
        Object.entries(anchorChips).forEach(([id, c]) => c.classList.toggle("on", id === anchorMode));
        gridWrap.style.display = anchorMode === "grid" ? "" : "none";
        xyRow.style.display = anchorMode === "xy" ? "" : "none";
        gridWrap.classList.toggle("us-disabled", bboxConnected);
        xyRow.classList.toggle("us-disabled", bboxConnected);
        const ag = st.anchor_grid || "center";
        Object.entries(gridCells).forEach(([id, c]) => c.classList.toggle("active", id === ag));
        const axy = st.anchor_xy || [0.5, 0.5];
        xyX.i.value = axy[0]; xyY.i.value = axy[1];

        const dir = st.scale_direction || "down";
        dirBtn.textContent = DIRECTION_LABEL[dir] || DIRECTION_LABEL.down;
        dirBtn.classList.toggle("on", dir !== "down");
        dirBtn.title = DIRECTION_TITLE[dir] || "";
        qSection.style.display = mode === "OFF" ? "none" : "";

        if (uniBtn) {
            const isAR = mode === "LARGEST_EDGE" || mode === "SMALLEST_EDGE" || mode === "MAX_MP" || (mode === "CROP" && !(fill && cropOn));
            uniBtn.style.display = isAR ? "" : "none";
            const uni = st.uniform_batch === true;
            uniBtn.textContent = uni ? "Uniform: On" : "Uniform: Off";
            uniBtn.classList.toggle("on", uni);
        }

        fTorsoBias.value = st.torso_bias ?? 0.0;
        fHeadroom.value = st.headroom ?? -0.20;
        fFaceMargin.value = st.face_margin_pct ?? 0.22;
        fTopGuard.value = st.top_guard_pct ?? 0.16;
        fFaceTopGuard.value = st.face_top_guard_pct ?? 0.25;
        fMinFace.value = st.min_face_frac ?? 0.06;
        fMaxFace.value = st.max_face_frac ?? 0.55;
        fTooLowRej.checked = st.reject_too_low_faces !== false;
        fTooLowThr.value = st.too_low_threshold_pct ?? 0.74;
        fFallback.value = st.fallback_if_no_face || "entropy";
        fSpeed.value = st.speed_mode || "balanced";
    }

    if (seedDefaults) {
        const cur = getState(node) || {};
        const miss = {};
        for (const k in SCALE_DEFAULTS) if (!(k in cur)) miss[k] = SCALE_DEFAULTS[k];
        if (Object.keys(miss).length) patchState(node, miss);
    }

    refresh();
    return { root, refresh };
}

// ── Pure compute helpers (shared output-size math; no DOM) ────────────────────
export function applyDirection(scale, direction) {
    if (direction === "down") return Math.min(scale, 1.0);
    if (direction === "up")   return Math.max(scale, 1.0);
    return scale;
}

export function computeScaledOutput(imgW, imgH, state) {
    if (!imgW || !imgH) return null;
    const mode = (state.resize_mode || "LARGEST_EDGE").toUpperCase();
    const dir  = state.scale_direction || "down";

    if (mode === "OFF") return { w: imgW, h: imgH };
    if (mode === "SMALLEST_EDGE") {
        const t = state.target_size || 1024;
        const sm = Math.min(imgW, imgH) || 1;
        let sc = t / sm;
        if (dir === "down") sc = Math.min(sc, 1);
        if (dir === "up")   sc = Math.max(sc, 1);
        return { w: Math.round(imgW * sc), h: Math.round(imgH * sc) };
    }
    if (mode === "LARGEST_EDGE") {
        const T = parseInt(state.target_size) || 1024;
        const s = applyDirection(T / Math.max(imgW, imgH), dir);
        return { w: Math.max(1, Math.round(imgW * s)), h: Math.max(1, Math.round(imgH * s)) };
    }
    if (mode === "MAX_MP") {
        const targetPx = (parseFloat(state.max_mp) || 1.0) * 1024 * 1024;
        const s = applyDirection(Math.sqrt(targetPx / (imgW * imgH)), dir);
        return { w: Math.max(1, Math.round(imgW * s)), h: Math.max(1, Math.round(imgH * s)) };
    }
    const TW = parseInt(state.width) || 1024;
    const TH = parseInt(state.height) || 1024;
    if (mode === "FIT_AND_PAD" || mode === "FORCE_EXACT") {
        return { w: TW, h: TH };
    }
    if (mode === "CROP") {
        const fill = state.fill !== false;
        const cropOn = state.crop_on !== false;
        if (fill && cropOn) return { w: TW, h: TH };
        if (fill && !cropOn) {
            const s = applyDirection(Math.max(TW / imgW, TH / imgH), dir);
            return { w: Math.max(1, Math.round(imgW * s)), h: Math.max(1, Math.round(imgH * s)) };
        }
        if (!fill && cropOn) {
            const rw = Math.max(0.01, parseFloat(state.ratio_w) || 1);
            const rh = Math.max(0.01, parseFloat(state.ratio_h) || 1);
            const targetAr = rw / rh, srcAr = imgW / imgH;
            let cw, ch;
            if (srcAr > targetAr) { cw = imgH * targetAr; ch = imgH; }
            else { cw = imgW; ch = imgW / targetAr; }
            return { w: Math.max(1, Math.round(Math.min(cw, imgW))), h: Math.max(1, Math.round(Math.min(ch, imgH))) };
        }
        const s = applyDirection(Math.min(TW / imgW, TH / imgH), dir);
        return { w: Math.max(1, Math.round(imgW * s)), h: Math.max(1, Math.round(imgH * s)) };
    }
    return { w: imgW, h: imgH };
}
