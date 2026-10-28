// attach.js — draws a coloured copy of a textarea's text behind it.
//
// The textarea keeps doing all the editing; its own text turns transparent and
// a backdrop element with identical font / padding / wrapping paints the same
// text with syntax colours underneath. The backdrop follows the textarea's
// position, size, scroll and visibility. If it ever fails to line up with the
// textarea the highlighting switches itself off and the textarea is restored,
// so a layout surprise can never hide the user's text.

import { tokenize, markSpans, toHtml } from "./tokens.js";

const CSS = `
.uwh-on{color:transparent!important;background:transparent!important;caret-color:var(--uwh-caret,#ddd)}
.uwh-on::selection{background:rgba(90,140,255,.38);color:transparent}
.uwh-on::placeholder{color:var(--uwh-placeholder,#888)}
.uwh-back{position:absolute;box-sizing:border-box;overflow:hidden;pointer-events:none;margin:0;
  border-style:solid;border-color:transparent;white-space:pre-wrap;overflow-wrap:break-word;word-break:normal}
.uwh-back>.uwh-in{position:absolute;left:0;top:0;box-sizing:border-box;margin:0;white-space:pre-wrap;overflow-wrap:break-word}
.uwh-tag{color:var(--uwh-tag,#5fb3ff)}
.uwh-tagd{color:var(--uwh-tagd,#3d7fb8)}
.uwh-var{color:var(--uwh-var,#ffa94d)}
.uwh-varo{color:var(--uwh-varo,#ffd43b)}
.uwh-sw{color:var(--uwh-sw,#b794f6)}
.uwh-swo{color:var(--uwh-swo,#e879f9)}
.uwh-pin{color:var(--uwh-pin,#8c9eff)}
.uwh-repl{color:var(--uwh-repl,#a3e635)}
.uwh-prot{color:var(--uwh-prot,#2dd4bf)}
.uwh-aspect{color:var(--uwh-aspect,#4ade80)}
.uwh-ctl{color:var(--uwh-weight,#22d3ee)}
.uwh-weight{color:var(--uwh-weight,#22d3ee);font-style:italic}
.uwh-sep{color:var(--uwh-sep,#9aa0ad)}
.uwh-esc{color:var(--uwh-esc,#c9b8a0);text-decoration:underline dotted}
.uwh-comment{color:var(--uwh-comment,#7d8f78);font-style:italic}
.uwh-br0{color:var(--uwh-br0,#f2c14e)}
.uwh-br1{color:var(--uwh-br1,#67e8f9)}
.uwh-br2{color:var(--uwh-br2,#c4b5fd)}
.uwh-br3{color:var(--uwh-br3,#86efac)}
.uwh-opt1{color:var(--uwh-opt1,#9fb4d9)}
.uwh-opt2{color:var(--uwh-opt2,#d9c89f)}
.uwh-opt3{color:var(--uwh-opt3,#a8d9a0)}
.uwh-tint1{background:color-mix(in srgb,var(--uwh-opt1,#9fb4d9) 24%,transparent);border-radius:3px}
.uwh-tint2{background:color-mix(in srgb,var(--uwh-opt2,#d9c89f) 24%,transparent);border-radius:3px}
.uwh-plain{color:inherit}
.uwh-bad{color:var(--uwh-bad,#ff5c5c);text-decoration:underline wavy var(--uwh-bad,#ff5c5c)}
.uwh-hit{background:rgba(128,128,128,.35);box-shadow:0 0 0 1px rgba(128,128,128,.7);border-radius:2px}
`;

function ensureCss() {
    if (document.getElementById("uwh-style")) return;
    const st = document.createElement("style");
    st.id = "uwh-style";
    st.textContent = CSS;
    document.head.appendChild(st);
}

// styles copied so the backdrop wraps text exactly like the textarea
const FONT_PROPS = ["fontFamily", "fontSize", "fontWeight", "fontStyle", "fontVariant", "fontStretch",
    "lineHeight", "letterSpacing", "wordSpacing", "textTransform", "textIndent", "tabSize",
    "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
    "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth", "direction"];
// inline geometry the ComfyUI frontend sets on a DOM widget's element
const GEOM_PROPS = ["position", "left", "top", "right", "bottom", "width", "height", "transform",
    "transformOrigin", "zIndex", "display", "visibility", "opacity", "clipPath"];

const instances = new Set();

// settings the highlighter reads on every repaint; index.js replaces them
let config = { optMode: "alternate", closeColor: true, pair: true, same: true, tagState: () => undefined };
const getConfig = () => config;
export function setConfig(next) {
    config = { ...config, ...next };
    for (const inst of instances) inst.queue();
}
let watchdog = null;

function startWatchdog() {
    if (watchdog) return;
    watchdog = setInterval(() => {
        for (const inst of instances) inst.poll();
        if (!instances.size) { clearInterval(watchdog); watchdog = null; }
    }, 700);
}

export function attachHighlight(ta, opts = {}) {
    if (!ta || ta._uwh) return ta?._uwh || null;
    ensureCss();

    const inst = {
        ta, back: null, inner: null, on: false, dead: false, raf: 0, checks: 0,
        saved: null, mo: null, ro: null,
    };
    ta._uwh = inst;

    const caretPos = () => (document.activeElement === ta ? ta.selectionStart : -1);

    inst.render = () => {
        inst.raf = 0;
        if (!inst.on) return;
        const cfg = getConfig();
        const text = ta.value;
        const { spans, pairs } = tokenize(text, { tagState: cfg.tagState });
        const caret = ta.selectionStart === ta.selectionEnd ? caretPos() : -1;
        const marked = (cfg.pair || cfg.same) ? markSpans(spans, pairs, caret, cfg) : null;
        inst.inner.innerHTML = toHtml(text, spans, marked, cfg);
        inst.syncScroll();
    };
    inst.queue = () => { if (!inst.raf) inst.raf = requestAnimationFrame(inst.render); };

    inst.syncScroll = () => {
        // inner is as wide as the textarea's text area (scrollbar excluded) and shifts with scrollTop
        const cs = getComputedStyle(ta);
        inst.inner.style.width = ta.clientWidth + "px";
        inst.inner.style.transform = `translate(${-ta.scrollLeft}px, ${-ta.scrollTop}px)`;
        inst.inner.style.paddingTop = cs.paddingTop;
        inst.inner.style.paddingLeft = cs.paddingLeft;
        inst.inner.style.paddingRight = cs.paddingRight;
        inst.inner.style.paddingBottom = cs.paddingBottom;
    };

    inst.syncStyle = () => {
        const cs = getComputedStyle(ta);
        for (const p of FONT_PROPS) { inst.back.style[p] = cs[p]; inst.inner.style[p] = cs[p]; }
        inst.inner.style.border = "0";
        inst.inner.style.padding = `${cs.paddingTop} ${cs.paddingRight} ${cs.paddingBottom} ${cs.paddingLeft}`;
        inst.back.style.padding = "0";
        inst.back.style.borderRadius = cs.borderRadius;
        inst.back.style.background = inst.saved.bg;
        inst.back.style.color = inst.saved.color;
    };

    inst.syncGeometry = () => {
        const wrapperMode = inst.wrapperMode;
        if (wrapperMode) {
            // textarea fills a positioned wrapper: the backdrop simply fills it too
            inst.back.style.position = "absolute";
            inst.back.style.inset = "0";
            inst.back.style.left = ta.offsetLeft + "px";
            inst.back.style.top = ta.offsetTop + "px";
            inst.back.style.width = ta.offsetWidth + "px";
            inst.back.style.height = ta.offsetHeight + "px";
            inst.back.style.zIndex = "0";
            inst.back.style.display = getComputedStyle(ta).display;
            inst.back.style.visibility = getComputedStyle(ta).visibility;
        } else {
            for (const p of GEOM_PROPS) inst.back.style[p] = ta.style[p];
            inst.back.style.position = "absolute";
            inst.back.style.zIndex = ta.style.zIndex ? String(Number(ta.style.zIndex) - 1 || 0) : "";
        }
        inst.syncScroll();
    };

    inst.verify = () => {
        // the backdrop must sit exactly over the textarea, else give up
        if (!inst.on || ta.offsetParent === null) return;
        const a = ta.getBoundingClientRect();
        const b = inst.back.getBoundingClientRect();
        const off = Math.abs(a.left - b.left) + Math.abs(a.top - b.top)
            + Math.abs(a.width - b.width) + Math.abs(a.height - b.height);
        if (a.width < 4 || a.height < 4) return;
        if (off > 3) {
            if (++inst.checks >= 3) {
                console.warn("[umbrae wildcard highlight] backdrop does not line up with the text box; highlighting turned off for it", { a, b });
                inst.disable();
                inst.dead = true;
            }
        } else {
            inst.checks = 0;
        }
    };

    inst.enable = () => {
        if (inst.on || inst.dead) return true;
        const parent = ta.parentElement;
        if (!parent) return false;
        const cs = getComputedStyle(ta);
        inst.saved = {
            bg: cs.backgroundColor, color: cs.color, caret: cs.caretColor,
            ph: null,
        };
        // if the textarea's own background is see-through, fall back to the input background variable
        if (/rgba?\(\s*0,\s*0,\s*0,\s*0\s*\)|transparent/.test(inst.saved.bg)) inst.saved.bg = "var(--comfy-input-bg,#222)";
        inst.wrapperMode = !(cs.position === "absolute" || cs.position === "fixed");
        if (inst.wrapperMode && getComputedStyle(parent).position === "static") {
            inst.parentPos = parent.style.position;
            parent.style.position = "relative";
        }
        inst.back = document.createElement("div");
        inst.back.className = "uwh-back";
        inst.inner = document.createElement("div");
        inst.inner.className = "uwh-in";
        inst.back.appendChild(inst.inner);
        parent.insertBefore(inst.back, ta);
        if (inst.wrapperMode) {
            // a positioned backdrop would paint over a static textarea and hide its caret: lift the textarea above it
            inst.taPos = { position: ta.style.position, zIndex: ta.style.zIndex };
            if (cs.position === "static") ta.style.position = "relative";
            ta.style.zIndex = "1";
        }
        ta.style.setProperty("--uwh-caret", inst.saved.color);
        ta.style.setProperty("--uwh-placeholder", "color-mix(in srgb, " + inst.saved.color + " 45%, transparent)");
        ta.classList.add("uwh-on");
        inst.on = true;
        inst.syncStyle();
        inst.syncGeometry();
        inst.render();

        inst.mo = new MutationObserver(() => { inst.syncGeometry(); inst.queue(); });
        inst.mo.observe(ta, { attributes: true, attributeFilter: ["style", "class"] });
        inst.ro = new ResizeObserver(() => { inst.syncGeometry(); inst.queue(); });
        inst.ro.observe(ta);
        setTimeout(inst.verify, 150);
        return true;
    };

    inst.disable = () => {
        if (!inst.on) return;
        inst.on = false;
        inst.mo?.disconnect();
        inst.ro?.disconnect();
        ta.classList.remove("uwh-on");
        ta.style.removeProperty("--uwh-caret");
        ta.style.removeProperty("--uwh-placeholder");
        inst.back?.remove();
        if (inst.taPos) { ta.style.position = inst.taPos.position; ta.style.zIndex = inst.taPos.zIndex; inst.taPos = null; }
        if (inst.parentPos !== undefined && ta.parentElement) ta.parentElement.style.position = inst.parentPos;
        inst.back = inst.inner = null;
    };

    inst.setEnabled = (flag) => {
        if (flag) { if (!inst.dead) inst.enable(); } else inst.disable();
    };

    // called by the watchdog: attach once the textarea is in the page, re-attach if it moved
    inst.poll = () => {
        if (inst.removed) return;
        if (!ta.isConnected) {
            if (inst.on && inst.back && !inst.back.isConnected) { /* parent gone with it */ }
            return;
        }
        if (inst.wanted === false || inst.dead) return;
        if (!inst.on) { inst.enable(); return; }
        if (inst.back.parentElement !== ta.parentElement) { inst.disable(); inst.enable(); return; }
        inst.verify();
        if (inst.on) inst.syncScroll();
    };

    inst.destroy = () => {
        inst.removed = true;
        inst.disable();
        instances.delete(inst);
        ta.removeEventListener("input", inst.queue);
        ta.removeEventListener("scroll", inst.syncScroll);
        document.removeEventListener("selectionchange", onSel);
        delete ta._uwh;
    };

    // events: typing, caret moves, scrolling, focus
    ta.addEventListener("input", inst.queue);
    ta.addEventListener("scroll", inst.syncScroll);
    for (const ev of ["keyup", "mouseup", "focus", "blur", "select"]) ta.addEventListener(ev, inst.queue);
    const onSel = () => { if (document.activeElement === ta) inst.queue(); };
    document.addEventListener("selectionchange", onSel);

    // programmatic changes (picker, workflow load) never fire 'input'
    try {
        const desc = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value");
        Object.defineProperty(ta, "value", {
            configurable: true,
            get() { return desc.get.call(this); },
            set(v) { desc.set.call(this, v); inst.queue(); },
        });
    } catch (e) { /* the 1 s watchdog repaint below still catches it */ }
    let lastSeen = null;
    const origPoll = inst.poll;
    inst.poll = () => {
        origPoll();
        if (inst.on && ta.value !== lastSeen) { lastSeen = ta.value; inst.render(); }
    };

    inst.wanted = opts.enabled !== false;
    instances.add(inst);
    startWatchdog();
    inst.poll();
    return inst;
}

export function setAllEnabled(flag) {
    for (const inst of instances) { inst.wanted = !!flag; inst.setEnabled(!!flag); }
}
