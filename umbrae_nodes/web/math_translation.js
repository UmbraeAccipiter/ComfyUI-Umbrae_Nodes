/**
 * web/math_translation.js — UNP
 *
 * Data flow:
 *   A → [input fn] ↘
 *                   [math op] → [output cond] → [type outputs]
 *   B → [input fn] ↗
 */

import { injectTheme } from "./umbrae_theme.js";
import { app } from "../../scripts/app.js";
import { measureRootContent, attachAutoHeight, applyAdaptiveCanvasOnly } from "./umbrae_resize.js";

const NODE_TYPE = "MathTranslation";
const STYLE_ID  = "unp-math-styles";
const MIN_W     = 280;

// ─── Colour helpers ───────────────────────────────────────────────────────────

let _typeColorCache = null;

function hexToRgb(hex) {
    const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
    return m ? [parseInt(m[1],16), parseInt(m[2],16), parseInt(m[3],16)] : null;
}
function makeVariants(hex) {
    const rgb = hexToRgb(hex);
    if (!rgb) return { text:hex, dot:hex, border:hex, bg:"rgba(128,128,128,0.08)" };
    const [r,g,b] = rgb;
    return { text:hex, dot:hex, border:`rgba(${r},${g},${b},0.6)`, bg:`rgba(${r},${g},${b},0.08)` };
}
function getTypeColors() {
    if (_typeColorCache) return _typeColorCache;
    const FB = { INT:"#3d87d4", FLOAT:"#9aab89", STRING:"#6ab150" };
    const c  = { OFF:{ border:"#2e2e2e", text:"#666", bg:"#252525", dot:"#555" } };
    for (const t of ["INT","FLOAT","STRING"]) {
        let color = null;
        if (typeof LiteGraph !== "undefined")
            color = LiteGraph.default_connection_color_byType?.[t]
                 ?? LiteGraph.registered_slot_out_types?.[t]?.color_on;
        c[t] = makeVariants(color || FB[t]);
    }
    c["STR"] = c["STRING"];
    _typeColorCache = c;
    return c;
}
function getWireInfo(node, slotIdx) {
    const inp = node.inputs?.[slotIdx];
    if (!inp?.link) return null;
    const link = node.graph?.links?.[inp.link];
    if (!link)     return null;
    const orig    = node.graph?.getNodeById(link.origin_id);
    const origOut = orig?.outputs?.[link.origin_slot];
    const raw     = String(origOut?.type ?? link.type ?? "").toUpperCase();
    const type    = raw === "INT" ? "INT" : raw === "FLOAT" ? "FLOAT"
                  : raw === "STRING" ? "STRING" : raw || "?";
    const color   = link.color
        || (typeof LiteGraph !== "undefined"
            ? LiteGraph.default_connection_color_byType?.[raw]
              ?? LiteGraph.registered_slot_out_types?.[raw]?.color_on
            : null)
        || origOut?.color_on
        || getTypeColors()[type]?.dot
        || "#888888";
    return { type, variants: makeVariants(color) };
}

// ─── State ────────────────────────────────────────────────────────────────────

const DEFAULT_STATE = {
    a_type:"OFF", a_int_val:0, a_float_val:0.0, a_str_val:"0",
    a_fn:"none", a_fn_round_by:1, a_fn_rounding_mode:"NEAREST",
    a_fn_tie_break:"HALF_AWAY_FROM_ZERO", a_fn_clamp_min:0.0, a_fn_clamp_max:100.0,
    b_type:"OFF", b_int_val:1, b_float_val:1.0, b_str_val:"1",
    b_fn:"none", b_fn_round_by:1, b_fn_rounding_mode:"NEAREST",
    b_fn_tie_break:"HALF_AWAY_FROM_ZERO", b_fn_clamp_min:0.0, b_fn_clamp_max:100.0,
    op:"NONE",
    out_cond:"none",
    rounding_mode:"NEAREST", tie_break:"HALF_AWAY_FROM_ZERO", round_by:1,
    clamp_min:0.0, clamp_max:100.0,
    out_clamp_enabled:false, out_clamp_min:0.0, out_clamp_max:100.0,
    int_rounding:"off", decimals:3, decimals_off:false,
    adv_open:false,
};
function getState(node) {
    if (!node.properties) node.properties = {};
    if (!node.properties.mathState) node.properties.mathState = { ...DEFAULT_STATE };
    return node.properties.mathState;
}
function patchState(node, patch) { Object.assign(getState(node), patch); }

// ─── Op & fn definitions ──────────────────────────────────────────────────────

const MATH_OPS = [
    { id:"NONE",lbl:"none",tip:"Pass A (or B) through unchanged" }, null,
    { id:"ADD", lbl:"+",  tip:"A + B" },
    { id:"SUB", lbl:"−",  tip:"A − B" },
    { id:"DIV", lbl:"÷",  tip:"A ÷ B  (0 when B=0)" },
    { id:"MUL", lbl:"×",  tip:"A × B" },
    { id:"MOD", lbl:"mod",tip:"Remainder of A ÷ B (modulo)" },
    { id:"PCT", lbl:"%",  tip:"A as a percent of B  (A ÷ B × 100)" },
    { id:"POW", lbl:"^",  tip:"A to the power of B" }, null,
    { id:"MIN", lbl:"min",tip:"Smaller of A and B" },
    { id:"MAX", lbl:"max",tip:"Larger of A and B" },
];

// Same function set used for per-input AND output conditioning
const COND_FNS = [
    { id:"none", lbl:"none",tip:"No function applied" }, null,
    { id:"ABS",  lbl:"|x|", tip:"Absolute value" },
    { id:"NEG",  lbl:"−x",  tip:"Negate  (×−1)" },
    { id:"FLOOR",lbl:"⌊⌋",  tip:"Floor: round down to nearest integer" },
    { id:"CEIL", lbl:"⌈⌉",  tip:"Ceiling: round up to nearest integer" },
    { id:"ROUND",lbl:"≈",   tip:"Round to a configurable step size" },
    { id:"CLAMP",lbl:"[ ]", tip:"Clamp to min / max range" },
];

// ─── CSS ─────────────────────────────────────────────────────────────────────

function injectCSS() {
    injectTheme();
    if (document.getElementById(STYLE_ID)) return;
    const s = document.createElement("style");
    s.id = STYLE_ID;
    s.textContent = `
.unp-m { width:100%; box-sizing:border-box; padding:8px 9px 9px; background:transparent;
         display:flex; flex-direction:column; gap:10px;
         font-family:system-ui,'Segoe UI',sans-serif; font-size:11px; color:var(--ud-text); align-self:flex-start }
.unp-m-sec { display:flex; flex-direction:column }
.unp-m-sec + .unp-m-sec { border-top:1px solid var(--ud-divider); padding-top:9px }
.unp-m-lbl { font-size:9px; font-weight:700; color:var(--ud-accent); text-transform:uppercase; letter-spacing:.07em; margin-bottom:6px }
.unp-m-chips { display:flex; gap:4px; flex-wrap:wrap }
.unp-m-chip { padding:4px 9px; border-radius:4px; border:1px solid var(--ud-border); background:var(--ud-inset);
              color:var(--ud-text-dim); font-size:10px; cursor:pointer; user-select:none; transition:all .12s }
.unp-m-chip:hover { color:var(--ud-text) }
.unp-m-chip.on { border-color:var(--ud-accent); background:var(--ud-accent); color:#fff; font-weight:600 }
.unp-m-val { display:flex; align-items:center; gap:5px }
.unp-m-sep-above { border-top:1px solid #303030; padding-top:6px; margin-top:6px }
.unp-m-sep-below { border-bottom:1px solid #303030; padding-bottom:6px; margin-bottom:6px }
.unp-m-vl  { font-size:9px; color:var(--ud-text-dim); width:22px; flex-shrink:0 }
.unp-m-inp { flex:1; background:var(--ud-inset); border:1px solid var(--ud-border); border-radius:4px;
             padding:3px 6px; font-size:11px; color:var(--ud-text); font-family:monospace; outline:none; min-width:0 }
.unp-m-inp:focus { border-color:var(--ud-accent) }
.unp-m-wire { display:flex; align-items:center; gap:6px; font-size:10px; padding:2px 0 }
.unp-m-dot  { width:8px; height:8px; border-radius:50%; flex-shrink:0 }
.unp-m-fn-row   { display:flex; align-items:center; gap:5px }
.unp-m-fn-lbl   { font-size:9px; color:var(--ud-text-dim); width:14px; flex-shrink:0 }
.unp-m-fn-chips { display:flex; gap:3px; flex-wrap:wrap }
.unp-m-fn-chip  { padding:3px 7px; border-radius:4px; border:1px solid var(--ud-border); background:var(--ud-inset);
                  color:var(--ud-text-dim); font-size:10px; cursor:pointer; user-select:none; transition:all .12s }
.unp-m-fn-chip:hover { color:var(--ud-text) }
.unp-m-fn-chip.on { border-color:var(--ud-accent); color:var(--ud-accent); background:#16242f }
.unp-m-fn-div   { width:1px; background:var(--ud-border); height:14px; margin:0 1px; flex-shrink:0 }
.unp-m-op-grid  { display:flex; gap:4px; flex-wrap:wrap; align-items:center }
.unp-m-op { padding:4px 8px; border-radius:4px; border:1px solid var(--ud-border); background:var(--ud-inset);
            color:#999; font-size:11px; cursor:pointer; user-select:none; transition:all .12s }
.unp-m-op:hover { color:var(--ud-text) }
.unp-m-op.on    { border-color:var(--ud-accent); color:var(--ud-accent); background:#16242f }
.unp-m-div  { width:1px; background:var(--ud-border); height:16px; margin:0 2px; flex-shrink:0 }
.unp-m-sub  { background:#1a1a1a; border-radius:4px; padding:6px 7px; margin-top:6px; border:1px solid #2e2e2e }
.unp-m-slbl { font-size:9px; color:var(--ud-text-dim); margin-bottom:4px; letter-spacing:.04em }
.unp-m-sc   { display:flex; gap:3px; flex-wrap:wrap }
.unp-m-sc .unp-m-chip { font-size:9px; padding:2px 6px }
.unp-m-pair { display:flex; align-items:center; gap:5px }
.unp-m-mini { background:var(--ud-inset); border:1px solid var(--ud-border); border-radius:3px;
              padding:2px 5px; font-size:10px; color:var(--ud-text); font-family:monospace; outline:none; width:58px }
.unp-m-mini:focus { border-color:var(--ud-accent) }
.unp-m-muted { font-size:9px; color:var(--ud-text-dim) }
.unp-m-adv-tog  { display:flex; align-items:center; gap:5px; font-size:9px; font-weight:700; color:var(--ud-accent);
                  text-transform:uppercase; letter-spacing:.07em; cursor:pointer; padding:6px 0 0;
                  border-top:1px solid var(--ud-divider); user-select:none }
.unp-m-adv-tog:hover { color:#9cc0e4 }
.unp-m-adv-body { margin-top:7px; display:flex; flex-direction:column; gap:7px }
.unp-m-adv-row  { display:flex; align-items:center; gap:6px }
.unp-m-adv-lbl  { font-size:10px; color:var(--ud-text-dim); width:72px; flex-shrink:0 }
.unp-m-tog { width:30px; height:16px; border-radius:8px; background:var(--ud-inset); border:1px solid var(--ud-border);
             position:relative; flex-shrink:0; cursor:pointer; transition:all .15s }
.unp-m-tog.on { background:#16242f; border-color:var(--ud-accent) }
.unp-m-tog-dot { width:12px; height:12px; border-radius:50%; background:#666;
                 position:absolute; top:1px; left:1px; transition:all .15s }
.unp-m-tog.on .unp-m-tog-dot { background:var(--ud-accent); left:15px }
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
function stopProp(e) { e.stopPropagation(); }
function makeInput(cls, type, val, opts) {
    const i = document.createElement("input");
    i.className=cls; i.type=type; i.value=val;
    if (opts) Object.assign(i, opts);
    i.addEventListener("mousedown", stopProp);
    i.addEventListener("pointerdown", stopProp);
    return i;
}
function makeChipSet(items, activeId, onPick) {
    const row = el("div","unp-m-sc");
    items.forEach(({id,lbl,tip}) => {
        const c = el("div","unp-m-chip"+(id===activeId?" on":""),lbl);
        if (tip) c.title=tip;
        c.addEventListener("click", e => {
            stopProp(e);
            row.querySelectorAll(".unp-m-chip").forEach(x=>x.classList.remove("on"));
            c.classList.add("on"); onPick(id);
        });
        row.appendChild(c);
    });
    return row;
}
function buildFnChips(activeFn, onPick) {
    const row = el("div","unp-m-fn-chips");
    COND_FNS.forEach(item => {
        if (!item) { row.appendChild(el("div","unp-m-fn-div")); return; }
        const {id,lbl,tip} = item;
        const c = el("div","unp-m-fn-chip"+(id===activeFn?" on":""),lbl);
        c.title=tip; c.dataset.fnId=id;
        c.addEventListener("click", e => {
            stopProp(e);
            row.querySelectorAll(".unp-m-fn-chip").forEach(x=>x.classList.remove("on"));
            c.classList.add("on"); onPick(id);
        });
        row.appendChild(c);
    });
    return row;
}

// ─── Sub-panel builders (prefix-aware) ───────────────────────────────────────

function buildRoundPanel(state, prefix, onPick) {
    const wrap = el("div","unp-m-sub");
    const rv=state[`${prefix}round_by`]??1, rm=state[`${prefix}rounding_mode`]??"NEAREST", tb=state[`${prefix}tie_break`]??"HALF_AWAY_FROM_ZERO";
    wrap.appendChild(el("div","unp-m-slbl","round to step"));
    const PRESETS=[1,8,16,64], stepRow=el("div","unp-m-sc"); stepRow.style.marginBottom="5px";
    let customInp;
    PRESETS.forEach(v => {
        const c=el("div","unp-m-chip"+(rv==v?" on":""),String(v));
        c.addEventListener("click",e=>{ stopProp(e); stepRow.querySelectorAll(".unp-m-chip").forEach(x=>x.classList.remove("on")); c.classList.add("on"); if(customInp) customInp.value=""; onPick({[`${prefix}round_by`]:v}); });
        stepRow.appendChild(c);
    });
    customInp=makeInput("unp-m-mini","number","",{placeholder:"…"}); customInp.style.width="44px";
    if(!PRESETS.includes(Number(rv))) customInp.value=rv;
    customInp.addEventListener("change",e=>{ stopProp(e); const v=parseFloat(customInp.value); if(!isNaN(v)&&v>0){stepRow.querySelectorAll(".unp-m-chip").forEach(x=>x.classList.remove("on")); onPick({[`${prefix}round_by`]:v});} });
    stepRow.appendChild(customInp); wrap.appendChild(stepRow);
    wrap.appendChild(el("div","unp-m-slbl","mode"));
    const MODES=[{id:"NEAREST",lbl:"nearest"},{id:"DOWN",lbl:"down"},{id:"UP",lbl:"up"},{id:"FURTHEST",lbl:"away"}];
    const modeRow=el("div","unp-m-sc"); modeRow.style.marginBottom="4px";
    let tieLbl,tieRow;
    MODES.forEach(({id,lbl})=>{
        const c=el("div","unp-m-chip"+(rm===id?" on":""),lbl);
        c.addEventListener("click",e=>{ stopProp(e); modeRow.querySelectorAll(".unp-m-chip").forEach(x=>x.classList.remove("on")); c.classList.add("on"); const st=id==="NEAREST"; if(tieLbl)tieLbl.style.display=st?"":"none"; if(tieRow)tieRow.style.display=st?"":"none"; onPick({[`${prefix}rounding_mode`]:id}); });
        modeRow.appendChild(c);
    });
    wrap.appendChild(modeRow);
    tieLbl=el("div","unp-m-slbl","tie-break"); tieLbl.style.display=rm==="NEAREST"?"":"none"; wrap.appendChild(tieLbl);
    const TIES=[{id:"HALF_UP",lbl:"half↑"},{id:"HALF_DOWN",lbl:"half↓"},{id:"HALF_TO_EVEN",lbl:"even"},{id:"HALF_AWAY_FROM_ZERO",lbl:"away"}];
    tieRow=makeChipSet(TIES,tb,id=>onPick({[`${prefix}tie_break`]:id})); tieRow.style.display=rm==="NEAREST"?"":"none"; wrap.appendChild(tieRow);
    return wrap;
}
function buildClampPanel(state, prefix, onPick) {
    const wrap=el("div","unp-m-sub"); wrap.appendChild(el("div","unp-m-slbl","bounds"));
    const pair=el("div","unp-m-pair");
    const mf=(lbl,key,def)=>{ pair.appendChild(el("span","unp-m-muted",lbl)); const inp=makeInput("unp-m-mini","number",state[key]??def); inp.addEventListener("change",e=>{ stopProp(e); const v=parseFloat(inp.value); if(!isNaN(v)) onPick({[key]:v}); }); pair.appendChild(inp); };
    mf("min",`${prefix}clamp_min`,0.0); mf("max",`${prefix}clamp_max`,100.0);
    wrap.appendChild(pair); return wrap;
}

// ─── Main setup ───────────────────────────────────────────────────────────────

function setupMathNode(node) {
    injectCSS();
    if (!node.bgcolor) node.bgcolor = "#2a2a2a";
    if (!node.color) node.color = "#1f1f1f";
    const root = el("div","unp-m");

    // A section: chips → value(below) → fn row
    const aWrap=el("div","unp-m-sec"); aWrap.appendChild(el("div","unp-m-lbl","A"));
    const aChips=el("div","unp-m-chips"), aWire=el("div","unp-m-wire"); aWire.style.display="none";
    const aValRow=el("div","unp-m-val unp-m-sep-above"), aInp=makeInput("unp-m-inp","text","");
    aValRow.append(el("div","unp-m-vl","val"),aInp);
    const aFnSep=el("div","unp-m-sep-above"), aFnRow=el("div","unp-m-fn-row");
    aFnRow.append(el("div","unp-m-fn-lbl","fn"));
    const aFnChips=buildFnChips(DEFAULT_STATE.a_fn,id=>{patchState(node,{a_fn:id});render();});
    aFnRow.appendChild(aFnChips);
    aWrap.append(aChips,aWire,aValRow,aFnSep,aFnRow);

    // B section: value(above) → chips → fn row
    const bWrap=el("div","unp-m-sec"); bWrap.appendChild(el("div","unp-m-lbl","B"));
    const bChips=el("div","unp-m-chips"), bWire=el("div","unp-m-wire"); bWire.style.display="none";
    const bValRow=el("div","unp-m-val unp-m-sep-below"), bInp=makeInput("unp-m-inp","text","");
    bValRow.append(el("div","unp-m-vl","val"),bInp);
    const bFnSep=el("div","unp-m-sep-above"), bFnRow=el("div","unp-m-fn-row");
    bFnRow.append(el("div","unp-m-fn-lbl","fn"));
    const bFnChips=buildFnChips(DEFAULT_STATE.b_fn,id=>{patchState(node,{b_fn:id});render();});
    bFnRow.appendChild(bFnChips);
    bWrap.append(bValRow,bWire,bChips,bFnSep,bFnRow);

    // Op section — math operations only
    const opWrap=el("div","unp-m-sec"); opWrap.appendChild(el("div","unp-m-lbl","Operation"));
    const opGrid=el("div","unp-m-op-grid");
    MATH_OPS.forEach(op=>{ if(!op){opGrid.appendChild(el("div","unp-m-div"));return;} const b=el("div","unp-m-op",op.lbl); b.title=op.tip; b.dataset.op=op.id; opGrid.appendChild(b); });
    opWrap.appendChild(opGrid);

    // Output conditioning section
    const condWrap=el("div","unp-m-sec"); condWrap.appendChild(el("div","unp-m-lbl","Output"));
    const condRow=el("div","unp-m-fn-row"); condRow.append(el("div","unp-m-fn-lbl","fn"));
    const condChips=buildFnChips(DEFAULT_STATE.out_cond,id=>{patchState(node,{out_cond:id});render();});
    condRow.appendChild(condChips); condWrap.appendChild(condRow);

    // Advanced
    const advWrap=el("div","unp-m-sec");

    root.append(aWrap,bWrap,opWrap,condWrap,advWrap);

    // Type chip rows
    function buildTypeRow(row,side) {
        ["OFF","INT","FLOAT","STR"].forEach(t=>{ const c=el("div","unp-m-chip",t.toLowerCase()); c.dataset.t=t; c.addEventListener("click",e=>{stopProp(e);patchState(node,{[`${side}_type`]:t==="STR"?"STRING":t});render();}); row.appendChild(c); });
    }
    buildTypeRow(aChips,"a"); buildTypeRow(bChips,"b");

    // Op grid events
    opGrid.querySelectorAll(".unp-m-op").forEach(btn=>btn.addEventListener("click",e=>{stopProp(e);patchState(node,{op:btn.dataset.op});render();}));

    // Value input events
    function wireVal(inp,side) {
        inp.addEventListener("change",e=>{stopProp(e);const st=getState(node),t=st[`${side}_type`];
            if(t==="INT")    patchState(node,{[`${side}_int_val`]:parseInt(inp.value)||0});
            if(t==="FLOAT")  patchState(node,{[`${side}_float_val`]:parseFloat(inp.value)||0.0});
            if(t==="STRING") patchState(node,{[`${side}_str_val`]:inp.value});
        });
    }
    wireVal(aInp,"a"); wireVal(bInp,"b");

    // Height + resize (verified mount contract)
    const measureH = () => measureRootContent(root);
    let auto = null;
    function scheduleResize(){ if (auto) auto.scheduleRelayout(); }

    const _mathWidget = node.addDOMWidget("unp_math_ui","custom",root,{
        getValue:()=>null, setValue:()=>{}, serialize:false,
        getMinHeight:measureH, getMaxHeight:measureH, margin:4,
    });
    applyAdaptiveCanvasOnly(_mathWidget);
    if (_mathWidget?.element) {
        _mathWidget.element.style.width = "100%";
        _mathWidget.element.style.boxSizing = "border-box";
    }
    const _W = Math.max(node.size?.[0] ?? 0, MIN_W);
    if (typeof node.setSize === "function") node.setSize([_W, node.size?.[1] ?? 120]);
    else if (node.size) node.size[0] = _W;
    auto = attachAutoHeight(node, root, _mathWidget);
    node._unpMathAuto = auto;

    // ── Render ────────────────────────────────────────────────────────────────

    const aFnLast={val:null}, bFnLast={val:null};
    let _lastOp=null, _lastOutCond=null;

    function updateSide(wrap,chips,wire,valRow,inp,fnSep,fnRowEl,fnChipsEl,side,slotIdx){
        const st=getState(node), wireInfo=getWireInfo(node,slotIdx), TC=getTypeColors();
        const activeType=(st[`${side}_type`]||"OFF").toUpperCase();
        const norm=activeType==="STRING"?"STR":activeType;
        const isActive=!!wireInfo||norm!=="OFF";

        if(wireInfo){
            chips.style.display="none"; valRow.style.display="none"; wire.style.display="";
            wire.innerHTML="";
            const {type,variants}=wireInfo;
            const dot=el("div","unp-m-dot"); dot.style.background=variants.dot;
            const txt=el("span"); txt.style.color=variants.text; txt.textContent=`${type.toLowerCase()} — wired (locked)`;
            wire.append(dot,txt);
            wrap.style.border="none"; wrap.style.borderLeft=`2px solid ${variants.dot}`; wrap.style.paddingLeft="7px";
        } else {
            wire.style.display="none"; chips.style.display="";
            chips.querySelectorAll(".unp-m-chip").forEach(c=>{
                const ct=c.dataset.t, isOn=ct===norm;
                const colors=TC[ct==="STR"?"STRING":ct]||TC.OFF;
                c.style.borderColor=isOn?colors.border:"#333";
                c.style.color=isOn?colors.text:"#666";
                c.style.background=isOn?colors.bg:"#252525";
            });
            const fc=TC[norm==="STR"?"STRING":norm]||TC.OFF;
            wrap.style.border="none"; wrap.style.borderLeft=norm==="OFF"?"2px solid #333":`2px solid ${fc.dot}`; wrap.style.paddingLeft="7px";
            valRow.style.display=norm!=="OFF"?"":"none";
            if(norm!=="OFF"){
                const colors=TC[activeType==="STRING"?"STRING":activeType]||TC.OFF;
                inp.style.borderColor=colors.border; inp.style.color=colors.text;
                if(activeType==="INT")       {inp.type="number";inp.step="1";  inp.value=st[`${side}_int_val`]??0;}
                else if(activeType==="FLOAT"){inp.type="number";inp.step="any";inp.value=st[`${side}_float_val`]??0.0;}
                else                        {inp.type="text";                  inp.value=st[`${side}_str_val`]??"";}
            }
        }

        // Fn row: visible only when input is active
        fnSep.style.display=fnRowEl.style.display=isActive?"":"none";
        const activeFn=st[`${side}_fn`]||"none";
        fnChipsEl.querySelectorAll(".unp-m-fn-chip").forEach(c=>c.classList.toggle("on",c.dataset.fnId===activeFn));
    }

    function updateFnSub(wrap,side,lastRef){
        const st=getState(node), fn=(st[`${side}_fn`]||"none").toUpperCase();
        if(fn===lastRef.val)return;
        lastRef.val=fn;
        const old=wrap.querySelector(".unp-m-fn-sub"); if(old)old.remove();
        if(fn==="ROUND"||fn==="CLAMP"){
            const sub=fn==="ROUND"?buildRoundPanel(st,`${side}_fn_`,p=>patchState(node,p)):buildClampPanel(st,`${side}_fn_`,p=>patchState(node,p));
            sub.classList.add("unp-m-fn-sub"); wrap.appendChild(sub);
        }
    }

    function updateOp(){
        const op=getState(node).op||"NONE";
        opGrid.querySelectorAll(".unp-m-op").forEach(b=>b.classList.toggle("on",b.dataset.op===op));
    }

    function updateCond(){
        const st=getState(node), fn=(st.out_cond||"none").toUpperCase();
        condChips.querySelectorAll(".unp-m-fn-chip").forEach(c=>c.classList.toggle("on",c.dataset.fnId===(st.out_cond||"none")));
        if(fn===_lastOutCond)return;
        _lastOutCond=fn;
        const old=condWrap.querySelector(".unp-m-fn-sub"); if(old)old.remove();
        if(fn==="ROUND"||fn==="CLAMP"){
            const sub=fn==="ROUND"?buildRoundPanel(st,"",p=>patchState(node,p)):buildClampPanel(st,"",p=>patchState(node,p));
            sub.classList.add("unp-m-fn-sub"); condWrap.appendChild(sub);
        }
    }

    function updateAdvanced(){
        const st=getState(node), isOpen=st.adv_open;
        advWrap.innerHTML="";
        const tog=el("div","unp-m-adv-tog"), tri=el("span",null,isOpen?"▾":"▸");
        tog.append(tri,el("span",null," Advanced"));
        tog.addEventListener("click",e=>{stopProp(e);patchState(node,{adv_open:!st.adv_open});render();});
        advWrap.appendChild(tog);
        if(!isOpen)return;
        const body=el("div","unp-m-adv-body");

        // Output clamp
        const ctRow=el("div","unp-m-adv-row"), ctog=el("div","unp-m-tog"+(st.out_clamp_enabled?" on":""));
        ctog.appendChild(el("div","unp-m-tog-dot")); ctRow.append(el("div","unp-m-adv-lbl","output clamp"),ctog); body.appendChild(ctRow);
        const cf=el("div","unp-m-adv-row"); cf.style.paddingLeft="78px"; cf.style.display=st.out_clamp_enabled?"":"none";
        const mcf=(lbl,key,def)=>{cf.appendChild(el("span","unp-m-muted",lbl));const inp=makeInput("unp-m-mini","number",st[key]??def);inp.addEventListener("change",e=>{stopProp(e);const v=parseFloat(inp.value);if(!isNaN(v))patchState(node,{[key]:v});});cf.appendChild(inp);};
        mcf("min","out_clamp_min",0.0);mcf("max","out_clamp_max",100.0);
        ctog.addEventListener("click",e=>{stopProp(e);const on=!ctog.classList.contains("on");ctog.classList.toggle("on",on);cf.style.display=on?"":"none";patchState(node,{out_clamp_enabled:on});scheduleResize();});
        body.appendChild(cf);

        // Int rounding
        const ir=el("div","unp-m-adv-row"); ir.appendChild(el("div","unp-m-adv-lbl","int rounding"));
        ir.appendChild(makeChipSet([
            {id:"off",lbl:"off",tip:"Python default int() — truncates"},
            {id:"nearest",lbl:"nearest",tip:"Round to nearest"},
            {id:"floor",lbl:"floor",tip:"Always round down"},
            {id:"ceil",lbl:"ceil",tip:"Always round up"},
        ],st.int_rounding??"off",id=>patchState(node,{int_rounding:id}))); body.appendChild(ir);

        // Str decimals
        const dr=el("div","unp-m-adv-row"); dr.appendChild(el("div","unp-m-adv-lbl","str decimals"));
        const doff=el("div","unp-m-chip"+(st.decimals_off?" on":""),"off"); doff.title="Off: full-precision float string";
        const dinp=makeInput("unp-m-mini","number",st.decimals??3,{min:0,max:10,step:1}); dinp.style.width="38px";
        dinp.style.opacity=st.decimals_off?"0.3":"1"; dinp.disabled=!!st.decimals_off;
        const dex=el("span","unp-m-muted",st.decimals_off?'e.g. "3.14159…"':'e.g. "3.142"');
        doff.addEventListener("click",e=>{stopProp(e);const n=!doff.classList.contains("on");doff.classList.toggle("on",n);dinp.disabled=n;dinp.style.opacity=n?"0.3":"1";dex.textContent=n?'e.g. "3.14159…"':'e.g. "3.142"';patchState(node,{decimals_off:n});});
        dinp.addEventListener("change",e=>{stopProp(e);const v=parseInt(dinp.value);if(!isNaN(v)&&v>=0)patchState(node,{decimals:v});});
        dr.append(doff,dinp,dex); body.appendChild(dr);

        advWrap.appendChild(body);
    }

    function render(){
        updateSide(aWrap,aChips,aWire,aValRow,aInp,aFnSep,aFnRow,aFnChips,"a",0);
        updateFnSub(aWrap,"a",aFnLast);
        updateSide(bWrap,bChips,bWire,bValRow,bInp,bFnSep,bFnRow,bFnChips,"b",1);
        updateFnSub(bWrap,"b",bFnLast);
        updateOp();
        updateCond();
        updateAdvanced();
        scheduleResize();
        node.setDirtyCanvas?.(true,true);
    }

    node._unpMathRender=render;
    queueMicrotask(()=>{
        if(!node._unpMathConfigured) node.size[0]=Math.max(node.size[0]??0,MIN_W);
        render();
    });
}

// ─── Extension ───────────────────────────────────────────────────────────────

app.registerExtension({
    name:"UNP.MathTranslation",
    async beforeRegisterNodeDef(nodeType,nodeData){
        if(nodeData.name!==NODE_TYPE)return;
        const _oc=nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated=function(){_oc?.apply(this,arguments);setupMathNode(this);};
        const _ocf=nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure=function(info){const r=_ocf?.apply(this,arguments);this._unpMathConfigured=true;queueMicrotask(()=>this._unpMathRender?.());return r;};
        const _occ=nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange=function(...a){const r=_occ?.apply(this,a);_typeColorCache=null;this._unpMathRender?.();return r;};
        const _or=nodeType.prototype.onRemoved;
        nodeType.prototype.onRemoved=function(){this._unpMathAuto?.dispose?.();return _or?.apply(this,arguments);};
        const _ors=nodeType.prototype.onResize;
        nodeType.prototype.onResize=function(size){if(size[0]<MIN_W)size[0]=MIN_W;return _ors?.apply(this,arguments);};
    },
    nodeCreated(node){
        if(node.comfyClass!==NODE_TYPE&&node.type!==NODE_TYPE)return;
        queueMicrotask(()=>{if(!node._unpMathConfigured)node._unpMathRender?.();});
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
        entry.inputs.ui_state=JSON.stringify(node.properties?.mathState??{});
    }
    return result;
};
