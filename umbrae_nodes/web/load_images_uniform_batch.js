/**
 * web/load_images_uniform_batch.js — UNP
 *
 * DOM widget for the batch folder loader. Single unified panel — the native
 * `image_index` and `custom_folder_path` widgets are hidden and folded into
 * this panel so there is only one visual surface, not two stacked interfaces.
 *
 * Layout (top → bottom), each in its own labeled card:
 *   SOURCE   [Browse Folder] then ← [folder  N images] → ↺   (or custom path)
 *   IMAGE    ← [filename   i / N] →
 *   —        [INPUT dims] → [OUTPUT dims]
 *   RESIZE MODE   Row1: [Largest Edge] [Max MP]   Row2: [Fit & Pad] [Crop to Fill] [Exact]
 *   SIZE     (one input for aspect-preserving modes, W+H or MP for the others)
 *   QUALITY & BATCH   [Resample] [Scale Direction] [Uniform/Anchor]
 *   PREVIEW  canvas that redraws on node resize, dims label
 */

import { injectTheme } from "./umbrae_theme.js";
import { app } from "../../scripts/app.js";
import { buildScaleSection, computeScaledOutput, applyDirection } from "./umbrae_scale.js";
import { applyAdaptiveCanvasOnly } from "./umbrae_resize.js";

const NODE_TYPE  = "LoadImagesUniformBatch";
const STYLE_ID   = "unp-lbu-styles";
const ACCENT     = "#7aa8d4";
const PREV_MIN_H = 90;
const PREV_MAX_H = 320;

// ─── Default state (mirrors Python DEFAULT_STATE) ─────────────────────────────

const DEFAULT = {
    folder_label:    "",
    resize_mode:     "LARGEST_EDGE",
    target_size:     1024,
    width:           1024,
    height:          1024,
    max_mp:          1.0,
    interpolation:   "lanczos",
    scale_direction: "down",
    uniform_batch:   true,
    fill:            true,
    crop_on:         true,
    ratio_w:         1,
    ratio_h:         1,
    anchor_mode:     "grid",
    anchor_grid:     "center",
    anchor_xy:       [0.5, 0.5],
    torso_bias:            0.0,
    headroom:              -0.20,
    face_margin_pct:       0.22,
    top_guard_pct:         0.16,
    face_top_guard_pct:    0.25,
    min_face_frac:         0.06,
    max_face_frac:         0.55,
    reject_too_low_faces:  true,
    too_low_threshold_pct: 0.74,
    fallback_if_no_face:   "entropy",
    speed_mode:            "balanced",
};

const RESAMPLE_OPTS = ["lanczos","bilinear","bicubic","nearest"];

// ─── CSS ─────────────────────────────────────────────────────────────────────

function injectCSS() {
    injectTheme();
    if (document.getElementById(STYLE_ID)) return;
    const s = document.createElement("style");
    s.id = STYLE_ID;
    s.textContent = `
.lbu-root {
    width:100%; box-sizing:border-box; padding:8px; background:transparent;
    border-radius:4px; display:flex; flex-direction:column; gap:8px;
    font-family:ui-sans-serif,system-ui,sans-serif; font-size:11px; color:var(--ud-text);
    align-self:flex-start;
}
.lbu-section { display:flex; flex-direction:column; gap:4px; }
.lbu-section-lbl {
    font-size:9px; font-weight:700; color:var(--ud-accent); text-transform:uppercase; letter-spacing:.07em;
}
/* nav row: ← [pill] → [btn] */
.lbu-row { display:flex; gap:5px; align-items:stretch; }
.lbu-nav {
    background:#1d1d1d; border:1px solid #444; border-radius:4px; color:${ACCENT};
    font-size:11px; font-weight:700; cursor:pointer; width:26px; flex-shrink:0;
    display:flex; align-items:center; justify-content:center; user-select:none;
    transition:background .08s, border-color .08s;
}
.lbu-nav:hover:not(.disabled) { background:#252525; border-color:${ACCENT}; }
.lbu-nav.disabled { opacity:.25; cursor:default; }
.lbu-nav.icon { font-size:13px; font-weight:400; }
/* prominent browse button */
.lbu-browse-btn {
    background:${ACCENT}; border:none; border-radius:4px; color:#15202b;
    font-size:11px; font-weight:600; padding:7px 8px; cursor:pointer;
    display:flex; align-items:center; justify-content:center; gap:6px;
    transition:filter .08s; width:100%; box-sizing:border-box;
}
.lbu-browse-btn:hover { filter:brightness(1.08); }
/* pill */
.lbu-pill {
    flex:1; min-width:0; background:#1d1d1d; border:1px solid #444; border-radius:4px;
    padding:5px 9px; display:flex; align-items:center; justify-content:space-between;
    gap:6px; cursor:pointer; transition:border-color .08s;
}
.lbu-pill:hover { border-color:${ACCENT}; }
.lbu-pill-name { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; color:#ccc; font-size:11px; }
.lbu-pill-cnt  { color:var(--ud-text-dim); font-size:9px; flex-shrink:0; white-space:nowrap; cursor:text; border-radius:3px; padding:1px 3px; }
.lbu-pill-cnt:hover { background:#2a2a2a; color:${ACCENT}; }
.lbu-pill-cnt-inp {
    width:34px; background:#111; border:1px solid ${ACCENT}; border-radius:3px;
    color:${ACCENT}; font-size:9px; text-align:center; outline:none; padding:1px 2px;
}
/* custom path inline editor */
.lbu-path-row { display:flex; gap:5px; align-items:stretch; }
.lbu-path-inp {
    flex:1; min-width:0; background:#1d1d1d; border:1px solid #444; border-radius:4px;
    padding:5px 9px; font-size:11px; color:${ACCENT}; outline:none; font-family:inherit;
}
.lbu-path-inp:focus { border-color:${ACCENT}; }
.lbu-path-clear {
    background:#1d1d1d; border:1px solid #444; border-radius:4px; color:#999;
    font-size:12px; cursor:pointer; width:26px; flex-shrink:0;
    display:flex; align-items:center; justify-content:center;
}
.lbu-path-clear:hover { border-color:#aa6666; color:#dd8888; }
/* dimension cards */
.lbu-cards {
    display:flex; align-items:stretch; gap:0; background:#1d1d1d; border-radius:4px;
    padding:6px 8px; border:1px solid var(--ud-border);
}
.lbu-card { flex:1; display:flex; flex-direction:column; align-items:center; gap:3px; }
.lbu-card-lbl  { font-size:9px; color:#777; text-transform:uppercase; letter-spacing:.06em; }
.lbu-card-dims { font-size:11px; font-weight:500; color:#999; }
.lbu-card-dims.accent { color:${ACCENT}; }
.lbu-ar-wrap   { width:48px; height:36px; display:flex; align-items:center; justify-content:center; }
.lbu-ar-rect   { border:1px solid #444; background:transparent; }
.lbu-ar-rect.accent { border-color:${ACCENT}; background:rgba(122,168,212,0.08); }
.lbu-card-ratio { font-size:9px; color:#666; }
.lbu-card-arrow { display:flex; align-items:center; padding:0 8px; color:#777; font-size:13px; flex-shrink:0; }
/* mode chips — large, equal */
.lbu-chips { display:flex; gap:4px; }
.lbu-chip {
    flex:1; padding:7px 6px; border-radius:4px; border:1px solid var(--ud-border); background:#1d1d1d;
    color:var(--ud-text-dim); font-size:10.5px; cursor:pointer; text-align:center; user-select:none;
    transition:border-color .1s, color .1s, background .1s;
}
.lbu-chip:hover { border-color:#666; color:#bbb; }
.lbu-chip.on { border-color:${ACCENT}; color:#fff; background:${ACCENT}; }
/* size inputs */
.lbu-size-row { display:flex; align-items:center; gap:8px; }
.lbu-size-grp { display:flex; align-items:center; gap:6px; flex:1; }
.lbu-size-lbl { font-size:9px; color:#777; flex-shrink:0; text-transform:uppercase; }
.lbu-size-inp {
    flex:1; background:#1d1d1d; border:1px solid var(--ud-border); border-radius:4px;
    padding:5px 7px; font-size:11px; color:#ccc; outline:none; font-family:inherit;
    min-width:0;
}
.lbu-size-inp:focus { border-color:${ACCENT}; }
/* quality & batch — 3 equal cards, same language as dimension cards */
.lbu-qcards {
    display:flex; gap:6px;
}
.lbu-qcard {
    flex:1; min-width:0; background:#1d1d1d; border:1px solid var(--ud-border); border-radius:4px;
    padding:6px 5px; display:flex; flex-direction:column; align-items:center; gap:5px;
}
.lbu-qcard-lbl { font-size:9px; color:#777; text-transform:uppercase; letter-spacing:.05em; }
.lbu-qcard-resample { display:flex; align-items:center; gap:2px; width:100%; }
.lbu-qcard-resample .lbu-nav { width:16px; font-size:9px; flex-shrink:0; }
.lbu-rs-lbl {
    flex:1; min-width:0; background:#232323; border:1px solid var(--ud-border); border-radius:4px;
    padding:4px 2px; font-size:9.5px; color:#bbb; text-align:center; cursor:pointer;
    transition:border-color .08s; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;
}
.lbu-rs-lbl:hover { border-color:${ACCENT}; }
.lbu-toggle-btn {
    width:100%; box-sizing:border-box; padding:4px 2px; border-radius:4px;
    border:1px solid var(--ud-border); background:#232323; color:var(--ud-text-dim); font-size:10px;
    font-weight:600; cursor:pointer; user-select:none; text-align:center;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
    transition:border-color .1s, color .1s, background .1s;
}
.lbu-toggle-btn.on { border-color:${ACCENT}; color:#fff; background:${ACCENT}; }
/* preview — same elevated tone as everything else */
.lbu-preview { background:#1d1d1d; border:1px solid var(--ud-border); border-radius:4px; display:flex; flex-direction:column; align-items:center; justify-content:center; min-height:${PREV_MIN_H}px; overflow:hidden; }
.lbu-canvas  { display:block; }
.lbu-prev-dims { font-size:9px; color:#777; padding:4px 0 5px; text-align:center; }
.lbu-msg { font-size:10px; color:#555; padding:18px; text-align:center; }
/* folder popup */
.lbu-popup {
    position:fixed; z-index:9999; background:#1d1d1d; border:1px solid #555;
    border-radius:5px; max-height:240px; overflow-y:auto; min-width:200px;
    box-shadow:0 4px 16px rgba(0,0,0,.6);
}
.lbu-popup-item { padding:6px 12px; font-size:11px; color:#bbb; cursor:pointer; white-space:nowrap; }
.lbu-popup-item:hover { background:#252525; color:#fff; }
.lbu-popup-item.active { color:${ACCENT}; }
.lbu-browse-path-row { display:flex; gap:5px; padding:8px 8px 6px; }
.lbu-browse-path-inp {
    flex:1; min-width:0; background:#111; border:1px solid #444; border-radius:4px;
    padding:5px 8px; color:${ACCENT}; font-size:11px; outline:none; font-family:inherit;
}
.lbu-browse-path-inp:focus { border-color:${ACCENT}; }
.lbu-browse-go {
    background:${ACCENT}; border:none; border-radius:4px; color:#15202b;
    font-size:11px; font-weight:600; padding:0 12px; cursor:pointer;
}
.lbu-browse-go:hover { filter:brightness(1.08); }
.lbu-popup-divider {
    font-size:9px; color:#777; text-transform:uppercase; letter-spacing:.05em;
    padding:4px 12px 2px;
}
.lbu-popup.lbu-browse-wide { max-height:none; overflow:visible; }
.lbu-browse-loc { display:flex; align-items:center; gap:6px; padding:0 8px 6px; }
.lbu-browse-up {
    background:#1d1d1d; border:1px solid #444; border-radius:4px; color:#aaa;
    font-size:10px; padding:4px 8px; cursor:pointer; flex-shrink:0;
}
.lbu-browse-up:hover { border-color:${ACCENT}; color:${ACCENT}; }
.lbu-browse-up.disabled { opacity:.3; cursor:default; pointer-events:none; }
.lbu-browse-loc-lbl {
    flex:1; min-width:0; font-size:10px; color:var(--ud-text-dim); overflow:hidden;
    text-overflow:ellipsis; white-space:nowrap;
}
.lbu-browse-list { max-height:220px; overflow-y:auto; border-top:1px solid #333; border-bottom:1px solid #333; }
.lbu-browse-dir-item {
    display:flex; justify-content:space-between; gap:8px; padding:6px 12px;
    font-size:11px; color:#ccc; cursor:pointer; white-space:nowrap;
}
.lbu-browse-dir-item:hover { background:#252525; color:#fff; }
.lbu-browse-dir-name { overflow:hidden; text-overflow:ellipsis; }
.lbu-browse-dir-count { color:#666; font-size:9px; flex-shrink:0; }
.lbu-browse-select {
    width:100%; box-sizing:border-box; margin-top:6px; background:${ACCENT}; border:none;
    border-radius:4px; color:#15202b; font-size:11px; font-weight:600; padding:7px 0; cursor:pointer;
}
.lbu-browse-select:hover { filter:brightness(1.08); }
.lbu-browse-select:disabled { opacity:.4; cursor:default; filter:none; }
    `;
    document.head.appendChild(s);
}

// ─── DOM helpers ──────────────────────────────────────────────────────────────

function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls)  e.className = cls;
    if (text) e.textContent = text;
    return e;
}
function sp(e) { e.stopPropagation(); }
function makeInput(cls, type, val) {
    const i = document.createElement("input");
    i.className = cls; i.type = type; i.value = val;
    i.addEventListener("mousedown", sp); i.addEventListener("pointerdown", sp);
    return i;
}
function navBtn(label, icon) {
    const b = el("button", "lbu-nav" + (icon ? " icon" : ""), label);
    b.type = "button"; return b;
}

// ─── Hide a native widget but keep it fully functional for serialization ────
// Same technique used throughout the ComfyUI ecosystem for "internal" widgets:
// hidden + zero computeSize + canvasOnly keeps it out of both the legacy and
// Vue/Nodes-2.0 renderers while its .value / .callback keep working normally.
function hideNativeWidget(node, name) {
    const w = node.widgets?.find(x => x.name === name);
    if (!w || w._lbuHidden) return w;
    w._lbuHidden = true;
    w.hidden = true;
    w.computeSize = () => [0, -4];
    if (!w.options) w.options = {};
    w.options.canvasOnly = true;
    if (w.element) w.element.style.display = "none";
    requestAnimationFrame(() => {
        if (w.element) w.element.style.display = "none";
        if (w.inputEl)  w.inputEl.style.display  = "none";
    });
    return w;
}

// ─── State ────────────────────────────────────────────────────────────────────

function getState(node) {
    if (!node.properties) node.properties = {};
    if (!node.properties.lbuState) node.properties.lbuState = { ...DEFAULT };
    return node.properties.lbuState;
}
function patchState(node, patch) { Object.assign(getState(node), patch); }

// ─── Output dimension calculator (delegates to the shared module) ───────────

function computeOutput(imgW, imgH, state) {
    return computeScaledOutput(imgW, imgH, state);
}

// ─── Aspect ratio rect drawing ────────────────────────────────────────────────

function gcd(a, b) { a=Math.abs(a); b=Math.abs(b); while(b){const t=b;b=a%b;a=t;} return a||1; }
function ratioLabel(w, h) {
    const g=gcd(w,h), rw=w/g, rh=h/g;
    const known=["1:1","2:1","1:2","16:9","9:16","4:3","3:4","3:2","2:3","21:9"];
    const s=`${rw}:${rh}`;
    if (known.includes(s)) return s;
    const r=w/h;
    return r>=1?`~${r.toFixed(2)}:1`:`~1:${(1/r).toFixed(2)}`;
}
function arRectStyle(w, h, maxW, maxH) {
    const a=w/h;
    let rw,rh;
    if(a>=maxW/maxH){rw=maxW;rh=Math.round(maxW/a);}
    else{rh=maxH;rw=Math.round(maxH*a);}
    rw=Math.max(4,rw); rh=Math.max(4,rh);
    return `width:${rw}px;height:${rh}px;`;
}

// ─── Folder popup ─────────────────────────────────────────────────────────────

let _popup = null;
function closePopup() {
    if (_popup) { _popup._close(); _popup = null; }
}

function openFolderPopup(node, anchorEl, folders, onPick) {
    closePopup();
    const st = getState(node);
    const popup = el("div", "lbu-popup");
    if (!folders.length) {
        popup.appendChild(el("div","lbu-popup-item","(no folders found)"));
    }
    folders.forEach(f => {
        const item = el("div","lbu-popup-item" + (f.label === st.folder_label ? " active" : ""), f.label);
        item.addEventListener("click", e => { sp(e); onPick(f); closePopup(); });
        popup.appendChild(item);
    });
    document.body.appendChild(popup);
    const rect = anchorEl.getBoundingClientRect();
    popup.style.left = rect.left + "px";
    popup.style.top  = (rect.bottom + 4) + "px";
    const close = (e) => { if (!popup.contains(e.target)) closePopup(); };
    document.addEventListener("click", close, true);
    popup._close = () => { popup.remove(); document.removeEventListener("click", close, true); };
    _popup = popup;
}

// ─── Server API ───────────────────────────────────────────────────────────────

async function fetchFolders() {
    try {
        const r = await fetch("/unp/batch_folders");
        return r.ok ? (await r.json()).folders ?? [] : [];
    } catch { return []; }
}
async function fetchFiles(folderLabel, customPath) {
    const p = new URLSearchParams({ folder_label: folderLabel || "", custom_path: customPath || "" });
    try {
        const r = await fetch(`/unp/batch_images?${p}`);
        return r.ok ? await r.json() : null;
    } catch { return null; }
}
function previewSrc(folderPath, filename) {
    return `/unp/batch_image_view?${new URLSearchParams({ folder_path:folderPath, filename, t:Date.now() })}`;
}

// ─── Main setup ───────────────────────────────────────────────────────────────

function setupNode(node) {
    injectCSS();

    // Match the node's own title/body color to our panel tone so the output
    // socket area above the panel doesn't read as a separate, mismatched block.
    node.color   = "#1d1d1d";
    node.bgcolor = "#2a2a2a";

    // ── Build DOM ─────────────────────────────────────────────────────────────

    const root = el("div", "lbu-root");

    // SOURCE section — prominent browse button + folder pill, or custom path editor
    const srcSection = el("div", "lbu-section");
    srcSection.append(el("div","lbu-section-lbl","Source Folder"));

    const browseBtn = el("button","lbu-browse-btn","\u{1F4C1}  Browse Folders");
    browseBtn.type = "button";

    const folderRow = el("div","lbu-row");
    const fPill = el("div","lbu-pill"); const fName = el("div","lbu-pill-name","—"); const fCnt = el("div","lbu-pill-cnt","");
    fPill.append(fName, fCnt);
    const fRefresh = navBtn("↺", true); fRefresh.title = "Reload the images in this folder (keeps your image index unless the file count changed)";
    folderRow.append(fPill, fRefresh);

    srcSection.append(browseBtn, folderRow);

    // IMAGE section
    const imgSection = el("div", "lbu-section");
    imgSection.append(el("div","lbu-section-lbl","Image"));
    const imgRow = el("div","lbu-row");
    const iPrev = navBtn("◀"); const iNext = navBtn("▶");
    const iPill = el("div","lbu-pill"); const iName = el("div","lbu-pill-name","—"); const iCnt = el("div","lbu-pill-cnt","");
    iPill.append(iName, iCnt);
    imgRow.append(iPrev, iPill, iNext);
    imgSection.append(imgRow);

    // Dimension cards (no extra label — they're self-labeled)
    const cardsEl = el("div","lbu-cards");
    const inCard  = el("div","lbu-card");
    const inLbl   = el("div","lbu-card-lbl","Input");
    const inDims  = el("div","lbu-card-dims","—");
    const inAR    = el("div","lbu-ar-wrap"); const inRect = el("div","lbu-ar-rect"); inAR.appendChild(inRect);
    const inRatio = el("div","lbu-card-ratio","—");
    inCard.append(inLbl, inDims, inAR, inRatio);
    const arrow   = el("div","lbu-card-arrow","→");
    const outCard = el("div","lbu-card");
    const outLbl  = el("div","lbu-card-lbl","Output");
    const outDims = el("div","lbu-card-dims accent","—");
    const outAR   = el("div","lbu-ar-wrap"); const outRect = el("div","lbu-ar-rect accent"); outAR.appendChild(outRect);
    const outRatio= el("div","lbu-card-ratio","—");
    outCard.append(outLbl, outDims, outAR, outRatio);
    cardsEl.append(inCard, arrow, outCard);

    // SCALING section — shared module, identical across all three nodes
    const scaleHost = el("div","lbu-section");
    function isBboxOverrideConnected() {
        const idx = node.findInputSlot ? node.findInputSlot("bbox_override") : -1;
        return idx >= 0 && node.inputs?.[idx]?.link != null;
    }

    const { root: scaleRoot, refresh: refreshScale } = buildScaleSection(
        node,
        getState,
        patchState,
        {
            showUniform: true,
            isBboxConnected: isBboxOverrideConnected,
            onChange: () => {
                const w = node._lbuImgEl?.naturalWidth, h = node._lbuImgEl?.naturalHeight;
                renderCards(w, h);
            },
        }
    );
    scaleHost.append(scaleRoot);

    // RESAMPLE section — kept node-specific (not part of the shared module's
    // agreed scope); CropImageRegion/SaveImageSmart use a fixed Lanczos resample.
    const rsSection = el("div","lbu-section");
    rsSection.append(el("div","lbu-section-lbl","Resample"));
    const rsRow = el("div","lbu-qcards");
    const rsCard = el("div","lbu-qcard");
    const rsInner = el("div","lbu-qcard-resample");
    const rsPrev = navBtn("◀"); const rsNext = navBtn("▶");
    const rsLbl  = el("div","lbu-rs-lbl","lanczos");
    rsInner.append(rsPrev, rsLbl, rsNext);
    rsCard.append(rsInner);
    rsRow.append(rsCard);
    rsSection.append(rsRow);

    // PREVIEW section
    const prevSection = el("div","lbu-section");
    prevSection.append(el("div","lbu-section-lbl","Preview"));
    const prevEl  = el("div","lbu-preview");
    const canvas  = el("canvas","lbu-canvas"); canvas.style.display="none";
    const msgEl   = el("div","lbu-msg","Select a folder to begin");
    const dimsLbl = el("div","lbu-prev-dims","");
    prevEl.append(canvas, msgEl, dimsLbl);
    prevSection.append(prevEl);

    root.append(srcSection, imgSection, cardsEl, scaleHost, rsSection, prevSection);

    // ── State ─────────────────────────────────────────────────────────────────

    node._lbuFolders = [];
    node._lbuFolderIdx = 0;
    node._lbuFiles   = [];
    node._lbuFolder  = "";
    node._lbuIdx     = node.properties?.unpStartIndex ?? 0;
    node._lbuImgEl   = null;   // last loaded <img> — reused on resize-redraw

    function measureH() {
        let h = 0;
        for (const child of root.children) {
            if (child.offsetParent === null && child !== root) continue;
            h += child.offsetHeight;
        }
        const cs = getComputedStyle(root);
        h += (parseFloat(cs.paddingTop)||0) + (parseFloat(cs.paddingBottom)||0);
        h += Math.max(0, root.children.length - 1) * (parseFloat(cs.gap)||8);
        return h < 60 ? 420 : h;
    }
    function isVue(){return!!window.LiteGraph?.vueNodesMode;}
    function resize(){
        const SH=(typeof LiteGraph!=="undefined"?LiteGraph.NODE_SLOT_HEIGHT:null)||20;
        const tgt=(node.outputs?.length??6)*SH+6+measureH();
        if(Math.abs((node.size?.[1]??0)-tgt)>2){ if(typeof node.setSize==="function") node.setSize([node.size[0], tgt]); else node.size[1]=tgt; node.setDirtyCanvas?.(true,true); try{ app?.canvas?.draw?.(true,true); }catch(_){} }
    }
    let _raf=null;
    function scheduleResize(){if(_raf)cancelAnimationFrame(_raf);_raf=requestAnimationFrame(()=>{_raf=null;resize();});}

    const _lbuWidget = node.addDOMWidget("lbu_ui","custom",root,{
        getValue:()=>null, setValue:()=>{}, serialize:false,
        getMinHeight:measureH, getMaxHeight:measureH,
    });
    if (_lbuWidget?.element) {
        _lbuWidget.element.style.width = "100%";
        _lbuWidget.element.style.boxSizing = "border-box";
    }
    applyAdaptiveCanvasOnly(_lbuWidget);
    if (!node.bgcolor) node.bgcolor = "#2a2a2a";
    if (!node.color) node.color = "#1f1f1f";
    const _lbuW = Math.max(node.size?.[0] ?? 0, 360);
    if (typeof node.setSize === "function") node.setSize([_lbuW, node.size?.[1] ?? 200]);
    else if (node.size) node.size[0] = _lbuW;

    // ── Preview redraw — fit current image to the CURRENT panel width,
    //    clamped between PREV_MIN_H/PREV_MAX_H. Re-runs whenever the node
    //    is resized (ResizeObserver on the preview box itself), so the
    //    image always fills the available width and never overflows.
    function redrawPreview() {
        const im = node._lbuImgEl;
        if (!im || !im.complete || !im.naturalWidth) return;
        const cssW = prevEl.clientWidth || 260;
        const aspect = im.naturalHeight / im.naturalWidth;
        const dh = Math.max(PREV_MIN_H, Math.min(Math.round(cssW * aspect), PREV_MAX_H));
        const scale = Math.min(cssW / im.naturalWidth, dh / im.naturalHeight, 1);
        const dw = Math.max(1, Math.round(im.naturalWidth * scale));
        const ch = Math.max(1, Math.round(im.naturalHeight * scale));
        canvas.width = dw; canvas.height = ch;
        canvas.style.width = dw + "px"; canvas.style.height = ch + "px";
        const ctx = canvas.getContext("2d");
        ctx.clearRect(0, 0, dw, ch);
        ctx.drawImage(im, 0, 0, dw, ch);
        canvas.style.display = "block"; msgEl.style.display = "none";
        dimsLbl.textContent = `${im.naturalWidth}\u202f×\u202f${im.naturalHeight}`;
    }
    let _prevRaf = null;
    function schedulePreviewRedraw() {
        if (_prevRaf) cancelAnimationFrame(_prevRaf);
        _prevRaf = requestAnimationFrame(() => { _prevRaf = null; redrawPreview(); });
    }
    const _previewRO = new ResizeObserver(() => schedulePreviewRedraw());
    _previewRO.observe(prevEl);

    // Re-measure and correct node height whenever the user drag-resizes the
    // node (onResize) or the panel's actual rendered content changes size
    // for any other reason (ResizeObserver on root — defense in depth).
    // Without this, getMinHeight/getMaxHeight only get re-evaluated on our
    // own state-change-triggered renders, so a manual corner-drag leaves
    // LiteGraph working off a stale measurement.
    node._lbuRootRO = new ResizeObserver(() => scheduleResize());
    node._lbuRootRO.observe(root);
    node.onResize = function() { scheduleResize(); };

    const _occ = node.onConnectionsChange;
    node.onConnectionsChange = function() {
        refreshScale();
        return _occ?.apply(this, arguments);
    };

    // ── Render helpers ────────────────────────────────────────────────────────

    function renderFolderRow() {
        // One always-visible source row: Browse button + current-folder display
        // + reload. The folder is chosen only through the Browse dialog.
        const folderPath = node._lbuFolder || getState(node).custom_path || "";
        fName.textContent = folderPath || "(no folder selected)";
        fName.title       = folderPath || "";
        const n = node._lbuFiles?.length ?? 0;
        fCnt.textContent  = n ? `${n} image${n === 1 ? "" : "s"}` : "";
    }

    function renderImageRow() {
        const files = node._lbuFiles, idx = node._lbuIdx, total = files.length;
        const can = total > 1;
        iPrev.classList.toggle("disabled",!can); iNext.classList.toggle("disabled",!can);
        iName.textContent = total>0 ? (files[idx]||"—") : "—";
        iCnt.textContent  = total>0 ? `${idx+1}\u202f/\u202f${total}` : "";
    }

    function renderCards(imgW, imgH) {
        if (!imgW || !imgH) {
            inDims.textContent="—"; inRatio.textContent=""; inRect.style="";
            outDims.textContent="—"; outRatio.textContent=""; outRect.style="";
            return;
        }
        const st  = getState(node);
        const out = computeOutput(imgW, imgH, st);
        const outW= out?.w ?? imgW, outH = out?.h ?? imgH;
        const changed = outW!==imgW || outH!==imgH;

        inDims.textContent = `${imgW}\u202f×\u202f${imgH}`;
        inRatio.textContent = ratioLabel(imgW,imgH);
        inRect.style = arRectStyle(imgW,imgH,46,34);

        outDims.textContent = `${outW}\u202f×\u202f${outH}`;
        outDims.className   = "lbu-card-dims" + (changed?" accent":"");
        outRatio.textContent = ratioLabel(outW,outH);
        outRect.style = arRectStyle(outW,outH,46,34);
        outRect.className   = "lbu-ar-rect" + (changed?" accent":"");
    }

    function renderResample() {
        rsLbl.textContent = getState(node).interpolation || "lanczos";
    }

    function updateNav(imgW, imgH) {
        renderFolderRow(); renderImageRow(); renderCards(imgW,imgH); refreshScale(); renderResample(); scheduleResize();
    }

    // ── Image preview ─────────────────────────────────────────────────────────

    async function loadPreview(idx) {
        const files = node._lbuFiles, folder = node._lbuFolder;
        if (!files.length) {
            node._lbuImgEl = null;
            canvas.style.display="none"; msgEl.style.display=""; dimsLbl.textContent="";
            renderCards(); scheduleResize(); return;
        }
        idx = ((idx%files.length)+files.length)%files.length;
        node._lbuIdx = idx;
        if (!node.properties) node.properties={};
        node.properties.unpStartIndex = idx;
        // Keep the hidden image_index widget in sync so Python receives the
        // correct value and SaveTrainingPair's iteration logic stays accurate.
        const idxWidget = node.widgets?.find(w => w.name === "image_index");
        if (idxWidget) idxWidget.value = idx;
        renderImageRow();

        await new Promise(resolve => {
            const img = new Image();
            img.onload = () => {
                node._lbuImgEl = img;
                redrawPreview();
                renderCards(img.naturalWidth, img.naturalHeight);
                scheduleResize();
                resolve();
            };
            img.onerror = () => {
                node._lbuImgEl = null;
                canvas.style.display="none"; msgEl.style.display="";
                msgEl.textContent="Preview unavailable"; dimsLbl.textContent="";
                renderCards(); scheduleResize(); resolve();
            };
            img.src = previewSrc(folder, files[idx]);
        });
        fetchImageInfo(folder, files[idx]);
        node.setDirtyCanvas?.(true,true);
    }

    async function fetchImageInfo(folderPath, filename) {
        node._lbuImgInfo = null;
        try {
            const p = new URLSearchParams({ folder_path: folderPath, filename });
            const r = await fetch(`/unp/batch_image_info?${p}`);
            node._lbuImgInfo = r.ok ? await r.json() : null;
        } catch { node._lbuImgInfo = null; }
        node.setDirtyCanvas?.(true,true);
    }

    // ── Folder loading ────────────────────────────────────────────────────────

    async function loadFolderImages(folderLabel, customPath) {
        const data = await fetchFiles(folderLabel, customPath);
        node._lbuFiles  = data?.files       ?? [];
        node._lbuFolder = data?.folder_path ?? "";
        if (!node.properties) node.properties = {};
        node.properties._fileCount = node._lbuFiles.length;
        app._unpBatchFileCount = node._lbuFiles.length;
        renderFolderRow();
        const idx = Math.min(node._lbuIdx, Math.max(0,node._lbuFiles.length-1));
        await loadPreview(idx);
    }

    async function selectFolder(folder) {
        patchState(node,{ folder_label: folder.label });
        await loadFolderImages(folder.label, "");
    }

    async function refreshFolders() {
        const folders = await fetchFolders();
        node._lbuFolders = folders;
        const st = getState(node);
        // Match on the folder name only: the label also carries the image count, which changes.
        const base = l => String(l || "").split(" (")[0].trim();
        let idx = folders.findIndex(f=>base(f.label)===base(st.folder_label));
        if (idx<0) idx=0;
        node._lbuFolderIdx = idx;
        renderFolderRow();
        if (folders.length) await selectFolder(folders[idx]);
        else { msgEl.textContent="No folders found"; renderImageRow(); }
    }

    // Write to the hidden custom_folder_path widget so Python sees the value.
    function setCustomPathWidget(v) {
        const cpw = node.widgets?.find(w => w.name === "custom_folder_path");
        if (cpw) cpw.value = v;
    }

    // Real filesystem browser — drill into subfolders, go up a level, jump
    // by pasting a path, and confirm with "Use This Folder". Distinct from
    // the small pill's popup, which is just a fast list of already-known
    // folders under ComfyUI/output.
    async function fetchBrowseDir(p) {
        try {
            const r = await fetch(`/unp/browse_dir?${new URLSearchParams({ path: p || "" })}`);
            return r.ok ? await r.json() : null;
        } catch { return null; }
    }

    function openBrowsePopup(anchorEl) {
        closePopup();
        const st = getState(node);

        const popup = el("div", "lbu-popup lbu-browse-wide");

        const pathRow = el("div", "lbu-browse-path-row");
        const inp = document.createElement("input");
        inp.type = "text"; inp.className = "lbu-browse-path-inp";
        inp.placeholder = "Paste a path and press Enter…";
        inp.value = st.custom_path || "";
        const goBtn = el("button", "lbu-browse-go", "Go");
        goBtn.type = "button";
        pathRow.append(inp, goBtn);

        const locRow  = el("div", "lbu-browse-loc");
        const upBtn   = el("button", "lbu-browse-up", "⬆ Up"); upBtn.type = "button";
        const locLbl  = el("div", "lbu-browse-loc-lbl", "Loading…");
        locRow.append(upBtn, locLbl);

        const listEl    = el("div", "lbu-browse-list");
        const selectBtn = el("button", "lbu-browse-select", "Use This Folder"); selectBtn.type = "button";

        popup.append(pathRow, locRow, listEl, selectBtn);

        async function loadDir(p) {
            locLbl.textContent = "Loading…";
            const data = await fetchBrowseDir(p);
            if (!data || data.error) {
                locLbl.textContent = data?.error || "Unable to read this location";
                listEl.innerHTML = "";
                upBtn.classList.add("disabled");
                selectBtn.disabled = true;
                return;
            }
            inp.value = data.current_path || "";
            locLbl.textContent = data.current_path || "Choose a drive";
            const canGoUp = data.parent_path !== null && data.parent_path !== undefined;
            upBtn.classList.toggle("disabled", !canGoUp);
            upBtn.onclick = e => { sp(e); if (canGoUp) loadDir(data.parent_path); };
            selectBtn.disabled = !data.current_path;

            listEl.innerHTML = "";
            if (data.image_count > 0) {
                listEl.appendChild(el("div","lbu-popup-divider",
                    `${data.image_count} image${data.image_count===1?"":"s"} in this folder`));
            }
            if (!data.dirs.length) {
                listEl.appendChild(el("div","lbu-popup-item","(no subfolders)"));
            }
            data.dirs.forEach(d => {
                const item = el("div","lbu-browse-dir-item");
                item.appendChild(el("span","lbu-browse-dir-name", d.name));
                if (d.image_count > 0) item.appendChild(el("span","lbu-browse-dir-count", `${d.image_count} images`));
                item.addEventListener("click", e => { sp(e); loadDir(d.path); });
                listEl.appendChild(item);
            });
        }

        goBtn.addEventListener("click", e => { sp(e); loadDir(inp.value.trim()); });
        inp.addEventListener("mousedown", sp); inp.addEventListener("pointerdown", sp);
        inp.addEventListener("keydown", e => {
            e.stopPropagation();
            if (e.key === "Enter") { e.preventDefault(); loadDir(inp.value.trim()); }
        });

        selectBtn.addEventListener("click", async e => {
            sp(e);
            const v = inp.value.trim();
            if (!v) return;
            patchState(node, { custom_path: v });
            setCustomPathWidget(v);
            node._lbuIdx = 0;
            await loadFolderImages("", v);
            closePopup();
        });

        document.body.appendChild(popup);
        const rect = anchorEl.getBoundingClientRect();
        popup.style.left  = rect.left + "px";
        popup.style.top   = (rect.bottom + 4) + "px";
        popup.style.width = Math.max(300, rect.width) + "px";
        const close = (e) => { if (!popup.contains(e.target)) closePopup(); };
        document.addEventListener("click", close, true);
        popup._close = () => { popup.remove(); document.removeEventListener("click", close, true); };
        _popup = popup;

        // Start at the folder currently in use (a folder picked from the list has no
        // custom_path), so Browse doesn't open on the drive list.
        loadDir(node._lbuFolder || st.custom_path || "");
        requestAnimationFrame(() => inp.focus());
    }

    // ── Events ────────────────────────────────────────────────────────────────

    // Prominent browse button — type any path, or pick from known folders.
    // Genuinely different from the pill below it, which only cycles the list.
    browseBtn.addEventListener("click", e => {
        sp(e);
        openBrowsePopup(browseBtn);
    });

    // ↺ reloads the images in the CURRENT folder (re-scans files). Keeps the
    // current image index if the file count is unchanged; resets to the first
    // image if the count changed (added/removed files shift what each index is).
    fRefresh.addEventListener("click", async e => {
        sp(e);
        const st = getState(node);
        const prevCount = node._lbuFiles?.length ?? 0;
        const prevIdx   = node._lbuIdx ?? 0;
        const data = await fetchFiles(st.folder_label || "", st.custom_path || "");
        node._lbuFiles  = data?.files ?? [];
        node._lbuFolder = data?.folder_path ?? node._lbuFolder;
        if (!node.properties) node.properties = {};
        node.properties._fileCount = node._lbuFiles.length;
        app._unpBatchFileCount = node._lbuFiles.length;
        const newCount = node._lbuFiles.length;
        const idx = (newCount === prevCount)
            ? Math.min(prevIdx, Math.max(0, newCount - 1))
            : 0;
        await loadPreview(idx);
        renderFolderRow();
    });

    // Image arrows
    iPrev.addEventListener("click",async e=>{ sp(e); if(iPrev.classList.contains("disabled"))return; await loadPreview(node._lbuIdx-1); });
    iNext.addEventListener("click",async e=>{ sp(e); if(iNext.classList.contains("disabled"))return; await loadPreview(node._lbuIdx+1); });

    // Click the count badge to type an exact index directly (1-based) — keeps
    // manual "resume from N" possible now that the native stepper is hidden.
    iCnt.addEventListener("click", e => {
        sp(e);
        if (!node._lbuFiles.length) return;
        const inp = document.createElement("input");
        inp.type = "text"; inp.inputMode = "numeric";
        inp.className = "lbu-pill-cnt-inp";
        inp.value = String(node._lbuIdx + 1);
        iCnt.replaceWith(inp);
        inp.addEventListener("mousedown", sp); inp.addEventListener("pointerdown", sp);
        inp.focus(); inp.select();
        const commit = async () => {
            const n = parseInt(inp.value);
            inp.replaceWith(iCnt);
            if (isFinite(n)) await loadPreview(n - 1);
        };
        inp.addEventListener("blur", commit);
        inp.addEventListener("keydown", ke => {
            ke.stopImmediatePropagation();
            if (ke.key === "Enter") { ke.preventDefault(); inp.blur(); }
        });
    });

    // Resample arrows (kept node-specific — see note above)
    rsPrev.addEventListener("click",e=>{ sp(e); const st=getState(node); const i=(RESAMPLE_OPTS.indexOf(st.interpolation||"lanczos")-1+RESAMPLE_OPTS.length)%RESAMPLE_OPTS.length; patchState(node,{interpolation:RESAMPLE_OPTS[i]}); renderResample(); });
    rsNext.addEventListener("click",e=>{ sp(e); const st=getState(node); const i=(RESAMPLE_OPTS.indexOf(st.interpolation||"lanczos")+1)%RESAMPLE_OPTS.length; patchState(node,{interpolation:RESAMPLE_OPTS[i]}); renderResample(); });
    rsLbl.addEventListener("click",e=>{ sp(e); const st=getState(node); const i=(RESAMPLE_OPTS.indexOf(st.interpolation||"lanczos")+1)%RESAMPLE_OPTS.length; patchState(node,{interpolation:RESAMPLE_OPTS[i]}); renderResample(); });

    // ── Initial load ──────────────────────────────────────────────────────────

    node._lbuRefresh = refreshFolders;
    node._lbuLoadFolder = loadFolderImages;

    // Hide the native image_index / custom_folder_path widgets — everything
    // they control is now represented in this panel.
    hideNativeWidget(node, "image_index");
    hideNativeWidget(node, "custom_folder_path");

    queueMicrotask(async () => {
        const st = getState(node);
        refreshScale(); renderResample();

        const cpw = node.widgets?.find(w => w.name === "custom_folder_path");
        const cpv = (cpw?.value || st.custom_path || "").trim();

        if (cpv) {
            patchState(node, { custom_path: cpv });
            renderFolderRow();
            await this._lbuLoadFolder?.("", cpv);
        } else {
            await refreshFolders();
            if (st.folder_label && node._lbuFiles.length === 0) {
                await loadFolderImages(st.folder_label, "");
            }
        }
    });
}

// ─── Extension ───────────────────────────────────────────────────────────────

app.registerExtension({
    name:"UNP.LoadImagesUniformBatch",

    async beforeRegisterNodeDef(nodeType,nodeData){
        if(nodeData.name!==NODE_TYPE)return;

        const _oc=nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated=function(){_oc?.apply(this,arguments);setupNode(this);};

        const _ocf=nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure=function(info){
            const r=_ocf?.apply(this,arguments);
            this._lbuConfigured=true;
            hideNativeWidget(this, "image_index");
            hideNativeWidget(this, "custom_folder_path");
            queueMicrotask(async()=>{
                const cpw = this.widgets?.find(w => w.name === "custom_folder_path");
                const cpv = (cpw?.value || "").trim();
                if (cpv) {
                    await loadFolderImages("", cpv);
                } else {
                    const st = getState(this);
                    if (st.folder_label) await this._lbuRefresh?.();
                }
            });
            return r;
        };

        // Store file count when Python execution completes so SaveTrainingPair
        // can read it without needing a wired input or relying on _lbuFiles.
        const _oex = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function(message) {
            _oex?.apply(this, arguments);
            const count = message?.file_count?.[0];
            if (count !== undefined) {
                if (!this.properties) this.properties = {};
                this.properties._fileCount = count;
                app._unpBatchFileCount = count;
                this.properties._currentIdx = message?.current_idx?.[0] ?? 0;
            }
        };

        // The output-socket rows (images/filenames/folder_path/count/last_index/
        // current_index) only have a dot+label on the far right — the rest of
        // that width is otherwise dead space. Show a thumbnail of what the node
        // actually OUTPUTS (post resize/crop/pad — not just the raw source)
        // alongside a compact info readout. The bbox_override input
        // socket occupies the top-left row, so the block starts below it.
        function drawModePreviewBox(ctx, im, boxX, boxY, boxW, boxH, mode, srcW, srcH, outW, outH, direction, fill, cropOn) {
            ctx.save();
            ctx.beginPath();
            if (ctx.roundRect) ctx.roundRect(boxX, boxY, boxW, boxH, 3); else ctx.rect(boxX, boxY, boxW, boxH);
            ctx.clip();
            ctx.fillStyle = "#000";
            ctx.fillRect(boxX, boxY, boxW, boxH);

            const stretchExact = mode === "FORCE_EXACT" && !(direction === "down" && srcW <= outW && srcH <= outH);
            if (stretchExact) {
                ctx.drawImage(im, 0, 0, srcW, srcH, boxX, boxY, boxW, boxH);
            } else if (mode === "CROP" && fill && cropOn) {
                // Fill+Crop: cover-scale then crop the overflow (fixed-size output).
                const coverScale = applyDirection(Math.max(outW / srcW, outH / srcH), direction);
                const fracW = (srcW * coverScale) / outW, fracH = (srcH * coverScale) / outH;
                const dW = boxW * fracW, dH = boxH * fracH;
                ctx.drawImage(im, 0, 0, srcW, srcH, boxX + (boxW - dW) / 2, boxY + (boxH - dH) / 2, dW, dH);
            } else if (mode === "CROP" && !fill && cropOn) {
                // Crop-only (ratio crop): scale-free, direct native-res crop at a ratio.
                const fracW = srcW / outW, fracH = srcH / outH;
                const dW = boxW * fracW, dH = boxH * fracH;
                ctx.drawImage(im, 0, 0, srcW, srcH, boxX + (boxW - dW) / 2, boxY + (boxH - dH) / 2, dW, dH);
            } else {
                // FIT_AND_PAD, FORCE_EXACT-falling-back-to-pad, LARGEST_EDGE/MAX_MP/OFF
                // (aspect-preserving), and CROP Fill-only (no crop, box already matches
                // the overflowed aspect so this naturally fills it with no bars).
                const fitScale = applyDirection(Math.min(outW / srcW, outH / srcH), direction);
                const fracW = (srcW * fitScale) / outW, fracH = (srcH * fitScale) / outH;
                const dW = boxW * fracW, dH = boxH * fracH;
                ctx.drawImage(im, 0, 0, srcW, srcH, boxX + (boxW - dW) / 2, boxY + (boxH - dH) / 2, dW, dH);
            }
            ctx.restore();
            ctx.strokeStyle = "rgba(255,255,255,0.12)";
            ctx.lineWidth = 1;
            ctx.strokeRect(boxX + 0.5, boxY + 0.5, boxW - 1, boxH - 1);
        }

        const _odf = nodeType.prototype.onDrawForeground;
        nodeType.prototype.onDrawForeground = function(ctx) {
            const r = _odf?.apply(this, arguments);
            if (this.flags?.collapsed) return r;
            const info = this._lbuImgInfo;
            const im   = this._lbuImgEl;
            if (!info || info.error) return r;

            const slotH = (typeof LiteGraph !== "undefined" ? LiteGraph.NODE_SLOT_HEIGHT : null) || 20;
            const nOut  = this.outputs?.length || 0;
            const nIn   = this.inputs?.length  || 0;
            if (nOut <= 0) return r;

            const rightReserved = 118; // room for the dot + output label text
            const leftMargin = 10;
            const topMargin  = nIn * slotH + 6; // clear any input socket rows (e.g. bbox_override)
            const availW = Math.max(0, (this.size?.[0] || 300) - rightReserved - leftMargin);
            const availH = Math.max(0, nOut * slotH - topMargin - 4);
            if (availW < 60 || availH < 24) return r;

            let textX = leftMargin;
            if (im && im.complete && im.naturalWidth) {
                const st = this.properties?.lbuState || {};
                const mode = (st.resize_mode || "LARGEST_EDGE").toUpperCase();
                const direction = st.scale_direction || "down";
                const fill = st.fill !== false, cropOn = st.crop_on !== false;
                const out = computeOutput(im.naturalWidth, im.naturalHeight, st) || { w: im.naturalWidth, h: im.naturalHeight };
                const thumbH = Math.min(availH, 84);
                let thumbW = thumbH * (out.w / out.h);
                thumbW = Math.min(thumbW, availW * 0.46);
                const thumbHActual = thumbW * (out.h / out.w);
                const ty = topMargin + (availH - thumbHActual) / 2;
                drawModePreviewBox(ctx, im, leftMargin, ty, thumbW, thumbHActual,
                    mode, im.naturalWidth, im.naturalHeight, out.w, out.h, direction, fill, cropOn);
                textX = leftMargin + thumbW + 10;
            }

            const lines = [
                `${info.width}\u202f×\u202f${info.height}px  ·  ${info.megapixels} MP`,
                `${info.aspect_ratio}  ·  ${info.format}  ·  ${info.mode}`,
                info.file_size_human,
            ];
            if (info.frame_count > 1) lines.push(`${info.frame_count} frames`);
            if (info.dpi) lines.push(`${Math.round(info.dpi[0])} dpi`);
            if (info.exif_orientation && info.exif_orientation !== 1) lines.push(`EXIF rot ${info.exif_orientation}`);

            const lineH  = 13;
            const textW  = Math.max(0, availW - (textX - leftMargin));
            if (textW > 40) {
                ctx.save();
                ctx.font = "11px ui-sans-serif, system-ui, sans-serif";
                ctx.textBaseline = "middle";
                ctx.fillStyle = "#999";
                const startY = topMargin + Math.max(0, (availH - lines.length * lineH) / 2);
                lines.forEach((line, i) => ctx.fillText(line, textX, startY + lineH * i + lineH / 2));
                ctx.restore();
            }
            return r;
        };

        const _or=nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved=function(){
            closePopup();
            this._lbuRootRO?.disconnect();
            return _or?.apply(this,arguments);
        };
    },

    nodeCreated(node){
        if(node.comfyClass!==NODE_TYPE&&node.type!==NODE_TYPE)return;
        queueMicrotask(async()=>{
            if(!node._lbuConfigured) await node._lbuRefresh?.();
        });
    },
});

// ─── graphToPrompt ────────────────────────────────────────────────────────────

const _origGTP=app.graphToPrompt.bind(app);
app.graphToPrompt=async function(...args){
    const result=await _origGTP(...args);
    const out=result?.output;
    if(!out)return result;
    const nodes=app.graph?._nodes??[];
    for(const id in out){
        const entry=out[id];
        if(!entry||entry.class_type!==NODE_TYPE)continue;
        const node=nodes.find(n=>String(n.id)===String(id));
        if(!node)continue;
        entry.inputs=entry.inputs||{};
        const _lbuState = {...(node.properties?.lbuState??{})};
        if (app._unpNextImageIndex !== undefined) {
            _lbuState.next_index = app._unpNextImageIndex;
        } else {
            delete _lbuState.next_index;
        }
        entry.inputs.ui_state = JSON.stringify(_lbuState);
    }
    delete app._unpNextImageIndex;
    return result;
};
