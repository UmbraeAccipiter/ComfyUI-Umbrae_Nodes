// web/lora_loader/ui.js — umbrae_nodes v0.9.3
// Shared DOM helpers, the stylesheet for every lora loader panel, the overlay
// popup and the image lightbox.
import { app } from "../../../scripts/app.js";
import { injectTheme } from "../umbrae_theme.js";

const STYLE_ID = "umbrae-lora-loader-styles";

export function h(tag, props = {}, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(props)) {
        if (v === undefined || v === null) continue;
        if (k === "class") el.className = v;
        else if (k === "text") el.textContent = v;
        else if (k === "html") el.innerHTML = v;
        else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
        else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
        else if (k === "value") el.value = v;
        else if (k === "checked") el.checked = !!v;
        else if (k === "disabled") el.disabled = !!v;
        else el.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid);
    return el;
}
export function shield(el) {
    for (const ev of ["mousedown", "pointerdown", "keydown", "keyup", "wheel", "dblclick", "contextmenu"]) {
        el.addEventListener(ev, (e) => e.stopPropagation());
    }
    return el;
}
export function btn(label, title, onClick, cls = "") {
    return h("button", { class: ("ull-btn " + cls).trim(), text: label, title, type: "button", onclick: (e) => { e.stopPropagation(); onClick?.(e); } });
}
export function toast(severity, summary, detail) {
    try { app.extensionManager?.toast?.add({ severity, summary, detail, life: 3500 }); } catch (_) {}
}
export async function copyText(text, el) {
    try {
        await navigator.clipboard.writeText(text);
        if (el) { const t = el.textContent; el.textContent = "✓ copied"; setTimeout(() => (el.textContent = t), 900); }
    } catch (_) { toast("warn", "Copy failed", "Clipboard not available."); }
}
export function fmtBytes(n) {
    n = Number(n);
    if (!isFinite(n) || n <= 0) return "";
    if (n >= 1e9) return (n / 1e9).toFixed(2) + " GB";
    if (n >= 1e6) return (n / 1e6).toFixed(1) + " MB";
    if (n >= 1e3) return Math.round(n / 1e3) + " KB";
    return n + " B";
}
export function fmtCount(n) {
    n = Number(n);
    if (!isFinite(n)) return "";
    if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + "k";
    return String(n);
}
const EXT_RE = /\.(safetensors|sft|ckpt|pt|pth|bin)$/i;
export function baseName(name) {
    const s = String(name || "").replace(/\\/g, "/");
    const i = s.lastIndexOf("/");
    return i < 0 ? s : s.slice(i + 1);
}
export function folderOf(name) {
    const s = String(name || "").replace(/\\/g, "/");
    const i = s.lastIndexOf("/");
    return i < 0 ? "" : s.slice(0, i);
}
export function displayName(name, hideExt = true) {
    const b = baseName(name);
    return hideExt ? b.replace(EXT_RE, "") : b;
}
export function stripExt(name) { return String(name || "").replace(EXT_RE, ""); }

// ── overlay popup ────────────────────────────────────────────────────────────
// One at a time per `kind`; returns {overlay, pop, close}. Esc and a click on
// the backdrop close it.
const _open = new Map();
export function openOverlay(kind, { width = 760, onClose } = {}) {
    closeOverlay(kind);
    const overlay = h("div", { class: "ull-overlay" });
    const pop = shield(h("div", { class: "ud-root ull-pop", style: { width: `min(${width}px, 94vw)` }, tabindex: "-1" }));
    const close = () => {
        if (_open.get(kind) !== overlay) return;
        overlay.remove(); _open.delete(kind); onClose?.();
    };
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
    pop.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } });
    overlay.append(pop);
    document.body.append(overlay);
    _open.set(kind, overlay);
    setTimeout(() => pop.focus(), 0);
    return { overlay, pop, close };
}
export function closeOverlay(kind) {
    const o = _open.get(kind);
    if (o) { o.remove(); _open.delete(kind); }
}
export function closeAllOverlays() { for (const k of [..._open.keys()]) closeOverlay(k); }

// ── lightbox ─────────────────────────────────────────────────────────────────
// images: [{url, medium, thumb, w, h, prompt}]; onUse(image) adds a "Use as preview" button.
export function openLightbox(images, index = 0, { onUse } = {}) {
    if (!images?.length) return;
    let i = Math.max(0, Math.min(images.length - 1, index));
    const box = h("div", { class: "ud-root ull-lightbox", tabindex: "-1" });
    const img = h("img", { class: "ull-lb-img" });
    const cap = h("div", { class: "ull-lb-cap" });
    const prev = btn("‹", "Previous (←)", () => show(i - 1), "lb");
    const next = btn("›", "Next (→)", () => show(i + 1), "lb");
    const close = btn("✕", "Close (Esc)", () => box.remove(), "lb close");
    const use = onUse ? btn("Use as preview", "Save this picture as the LoRA's preview", () => onUse(images[i]), "primary") : null;
    const openNew = btn("Open full size ↗", "Open the original in a new tab", () => window.open(images[i].url, "_blank"));
    const promptBtn = btn("Copy prompt", "Copy the generation prompt of this picture", () => copyText(images[i].prompt || "", promptBtn));
    function show(k) {
        i = (k + images.length) % images.length;
        const im = images[i];
        img.src = im.medium || im.url;
        cap.textContent = `${i + 1} / ${images.length}` + (im.w && im.h ? ` · ${im.w}×${im.h}` : "") + (im.nsfw >= 4 ? " · adult" : "");
        promptBtn.style.display = im.prompt ? "" : "none";
    }
    box.addEventListener("keydown", (e) => {
        e.stopPropagation();
        if (e.key === "Escape") box.remove();
        if (e.key === "ArrowLeft") show(i - 1);
        if (e.key === "ArrowRight") show(i + 1);
    });
    box.addEventListener("mousedown", (e) => { e.stopPropagation(); if (e.target === box) box.remove(); });
    for (const ev of ["pointerdown", "wheel", "keyup", "contextmenu"]) box.addEventListener(ev, (e) => e.stopPropagation());
    box.append(prev, h("div", { class: "ull-lb-main" }, img, cap, h("div", { class: "ull-lb-bar" }, use, openNew, promptBtn)), next, close);
    document.body.append(box);
    show(i);
    box.focus();
}

// ── styles ───────────────────────────────────────────────────────────────────
export function ensureStyles() {
    injectTheme();
    if (document.getElementById(STYLE_ID)) return;
    const s = document.createElement("style");
    s.id = STYLE_ID;
    s.textContent = `
/* node face */
.ud-root.ull-root { gap: 0; user-select: none; }
.ull-root * { box-sizing: border-box; }
.ull-band { display:flex; align-items:center; gap:5px; padding-bottom:6px; }
.ull-add { flex:1; height:22px; background:var(--ud-accent); border:1px solid var(--ud-accent); color:#fff; border-radius:4px; font-size:11px; font-weight:600; cursor:pointer; }
.ull-add:hover { background:var(--ud-accent-hover); }
.ull-add:disabled { opacity:.4; cursor:default; }
.ull-all { display:flex; align-items:center; gap:6px; height:22px; padding:0 7px; background:var(--ud-inset); border:1px solid var(--ud-border); border-radius:4px; color:var(--ud-text-dim); font-size:10px; cursor:pointer; white-space:nowrap; }
.ull-all:hover { border-color:var(--ud-accent); color:var(--ud-text); }
.ull-gear { width:24px; height:22px; background:var(--ud-inset); border:1px solid var(--ud-border); border-radius:4px; color:var(--ud-text-dim); cursor:pointer; font-size:12px; display:flex; align-items:center; justify-content:center; }
.ull-gear:hover { border-color:var(--ud-accent); color:var(--ud-accent); }
.ull-rows { display:flex; flex-direction:column; gap:4px; }
.ull-row { display:flex; align-items:center; gap:5px; height:26px; padding:0 5px; background:var(--ud-inset); border:1px solid var(--ud-border); border-radius:4px; }
.ull-row.off { opacity:.45; }
.ull-row.drag { outline:1px dashed var(--ud-accent); }
.ull-sw { flex:none; width:26px; height:14px; border-radius:14px; background:#3a3a3a; border:1px solid #000; position:relative; cursor:pointer; }
.ull-sw::after { content:""; position:absolute; top:1px; left:1px; width:10px; height:10px; border-radius:50%; background:#8a8a8a; transition:left .12s, background .12s; }
.ull-sw.on { background:var(--ud-accent); }
.ull-sw.on::after { left:13px; background:#fff; }
.ull-name { flex:1; min-width:0; height:20px; display:flex; align-items:center; gap:4px; padding:0 6px; background:#161616; border:1px solid var(--ud-border); border-radius:4px; color:var(--ud-text); font-size:11px; cursor:pointer; overflow:hidden; }
.ull-name:hover { border-color:var(--ud-accent); }
.ull-name .nm { flex:1; min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.ull-name.empty .nm { color:var(--ud-text-dim); }
.ull-name.missing .nm { color:#e05555; }
.ull-name.missing::before { content:"⚠"; color:#e05555; font-size:10px; }
.ull-name .car { color:var(--ud-text-dim); font-size:8px; }
.ull-name .fld { color:var(--ud-text-dim); font-size:9px; flex:none; max-width:40%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ull-w { flex:none; display:flex; align-items:stretch; width:54px; height:20px; background:#161616; border:1px solid var(--ud-border); border-radius:4px; overflow:hidden; }
.ull-w:focus-within { border-color:var(--ud-accent); }
.ull-w input { flex:1; min-width:0; width:100%; background:transparent; border:0; outline:none; color:var(--ud-accent); text-align:center; font-size:10px; font-weight:600; padding:0; }
.ull-w.clip input { color:#b8a0d8; }
.ull-wspin { display:flex; flex-direction:column; width:12px; border-left:1px solid var(--ud-border); }
.ull-wspin button { flex:1; border:0; background:transparent; color:var(--ud-text-dim); font-size:6px; line-height:1; cursor:pointer; padding:0; }
.ull-wspin button:hover { color:var(--ud-accent); background:#2c2c2c; }
.ull-i { flex:none; width:20px; height:20px; border:1px solid var(--ud-border); background:#161616; border-radius:4px; color:var(--ud-text-dim); font:italic 600 11px Georgia,serif; cursor:pointer; }
.ull-i:hover { border-color:var(--ud-accent); color:var(--ud-accent); }
.ull-i.has { color:var(--ud-accent); }
.ull-empty { height:30px; display:flex; align-items:center; justify-content:center; color:var(--ud-text-dim); font-size:10px; border:1px dashed var(--ud-border); border-radius:4px; }
.ull-menu { position:fixed; z-index:10050; width:auto; display:block; gap:0; background:#262626; border:1px solid var(--ud-border); border-radius:4px; padding:3px; box-shadow:0 6px 20px #000a; font-family:var(--ud-font); font-size:11px; color:var(--ud-text); min-width:150px; }
.ull-menu div { padding:4px 10px; cursor:pointer; border-radius:3px; }
.ull-menu div:hover { background:var(--ud-accent); color:#fff; }
.ull-menu div.dis { opacity:.4; pointer-events:none; }
.ull-menu hr { border:0; border-top:1px solid var(--ud-divider); margin:3px 0; }

/* shared controls in panels */
.ull-btn { background:var(--ud-inset); border:1px solid var(--ud-border); color:var(--ud-text); border-radius:4px; padding:3px 8px; font-size:11px; cursor:pointer; line-height:1.3; white-space:nowrap; font-family:var(--ud-font); }
.ull-btn:hover { background:var(--ud-inset-hover); border-color:var(--ud-accent); }
.ull-btn.primary { background:var(--ud-accent); border-color:var(--ud-accent); color:#fff; font-weight:600; }
.ull-btn.primary:hover { background:var(--ud-accent-hover); }
.ull-btn.on { background:var(--ud-accent); border-color:var(--ud-accent); color:#fff; }
.ull-btn:disabled { opacity:.45; cursor:default; }
.ull-btn.tiny { padding:1px 6px; font-size:10px; }
.ull-btn.danger:hover { border-color:#e05555; color:#e05555; }
.ull-in { background:var(--ud-inset); border:1px solid var(--ud-border); color:var(--ud-text); border-radius:4px; padding:4px 7px; font-size:11px; outline:none; font-family:var(--ud-font); min-width:0; }
.ull-in:focus { border-color:var(--ud-accent); }
.ull-sel { background:var(--ud-inset); border:1px solid var(--ud-border); color:var(--ud-text); border-radius:4px; padding:3px 4px; font-size:11px; outline:none; font-family:var(--ud-font); }
.ull-sel option { background:var(--ud-inset); }
.ull-h3 { margin:0; font-size:11px; color:var(--ud-accent); text-transform:uppercase; letter-spacing:.07em; display:flex; gap:8px; align-items:center; }
.ull-h3 .sub { color:var(--ud-text-dim); text-transform:none; letter-spacing:0; font-weight:400; flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ull-bar { display:flex; align-items:center; gap:6px; flex-wrap:wrap; }
.ull-bar .grow { flex:1; min-width:120px; }
.ull-dim { color:var(--ud-text-dim); font-size:10px; }
.ull-err { color:#e08080; font-size:11px; }
.ull-label { font-size:9px; font-weight:700; text-transform:uppercase; letter-spacing:.07em; color:var(--ud-text-dim); }
.ull-sect { display:flex; flex-direction:column; gap:5px; }
.ull-divider { border:0; border-top:1px solid var(--ud-divider); margin:2px 0; }
.ull-chips { display:flex; flex-wrap:wrap; gap:4px; }
.ull-chip { display:inline-flex; align-items:center; gap:5px; padding:2px 8px; border-radius:12px; background:var(--ud-inset); border:1px solid var(--ud-border); color:var(--ud-text-dim); font-size:11px; cursor:pointer; user-select:none; max-width:100%; }
.ull-chip .ct { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ull-chip:hover { border-color:var(--ud-accent); color:var(--ud-text); }
.ull-chip.sel { background:var(--ud-accent); border-color:var(--ud-accent); color:#fff; }
.ull-chip.custom { border-style:dashed; }
.ull-chip .cx { font-size:9px; opacity:.7; }
.ull-chip .cx:hover { opacity:1; color:#ffb0b0; }
.ull-tag { display:inline-block; padding:1px 6px; border-radius:3px; background:#333; color:var(--ud-text-dim); font-size:9px; }
.ull-tag.base { background:#2d3744; color:#9fc3e8; }
.ull-prog { height:6px; background:var(--ud-inset); border:1px solid var(--ud-border); border-radius:3px; overflow:hidden; }
.ull-prog > div { height:100%; background:var(--ud-accent); width:0; transition:width .3s; }
.ull-desc { font-size:11px; line-height:1.45; color:var(--ud-text); white-space:pre-wrap; max-height:110px; overflow:hidden; position:relative; }
.ull-desc.open { max-height:none; overflow:auto; max-height:320px; }
.ull-desc:not(.open).long::after { content:""; position:absolute; left:0; right:0; bottom:0; height:30px; background:linear-gradient(transparent, #262626); }

/* overlay + pop */
.ull-overlay { position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:10000; display:flex; align-items:center; justify-content:center; }
.ull-pop { max-height:88vh; display:flex; flex-direction:column; gap:8px; background:#262626; border:1px solid var(--ud-border); border-radius:6px; padding:10px; color:var(--ud-text); font-family:var(--ud-font); font-size:11px; box-shadow:0 8px 30px #000a; outline:none; }
.ull-pop * { box-sizing:border-box; }
.ull-scroll { flex:1; min-height:120px; overflow:auto; border:1px solid var(--ud-border); border-radius:4px; background:var(--ud-inset); padding:4px; }
.ull-tabs { display:flex; gap:2px; border-bottom:1px solid var(--ud-divider); }
.ull-tab { padding:5px 12px; cursor:pointer; color:var(--ud-text-dim); border-bottom:2px solid transparent; font-size:11px; font-weight:600; }
.ull-tab:hover { color:var(--ud-text); }
.ull-tab.on { color:var(--ud-accent); border-bottom-color:var(--ud-accent); }

/* picker: local list */
.ull-crumb { display:flex; flex-wrap:wrap; gap:2px; align-items:center; color:var(--ud-text-dim); font-size:10px; }
.ull-crumb span.c { cursor:pointer; }
.ull-crumb span.c:hover { color:var(--ud-accent); }
.ull-crumb span.here { color:var(--ud-text); }
.ull-item { display:flex; align-items:center; gap:7px; padding:4px 7px; border-radius:3px; cursor:pointer; }
.ull-item:hover { background:#2d3744; }
.ull-item.cur { background:#2d3744; outline:1px solid var(--ud-accent); }
.ull-item .ic { width:14px; text-align:center; color:var(--ud-text-dim); flex:none; }
.ull-item .nm { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ull-item .fld { color:var(--ud-text-dim); font-size:9px; flex:none; }
.ull-item .thumb { width:28px; height:28px; object-fit:cover; border-radius:3px; background:#111; flex:none; }

/* picker: cards */
.ull-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(150px, 1fr)); gap:8px; }
.ull-card { background:#1e1e1e; border:1px solid var(--ud-border); border-radius:5px; overflow:hidden; cursor:pointer; display:flex; flex-direction:column; }
.ull-card:hover { border-color:var(--ud-accent); }
.ull-card .img { width:100%; aspect-ratio:1/1; background:#111 center/cover no-repeat; display:flex; align-items:flex-end; }
.ull-card .img.none { align-items:center; justify-content:center; color:var(--ud-text-dim); font-size:10px; }
.ull-card .body { padding:5px 6px; display:flex; flex-direction:column; gap:3px; }
.ull-card .nm { font-size:11px; font-weight:600; color:var(--ud-text); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ull-card .meta { display:flex; gap:6px; align-items:center; flex-wrap:wrap; color:var(--ud-text-dim); font-size:9px; }
.ull-card .adult { position:absolute; }

/* picker: detail */
.ull-detail { display:flex; gap:10px; min-height:0; flex:1; }
.ull-detail .left { width:42%; flex:none; display:flex; flex-direction:column; gap:6px; min-width:0; }
.ull-detail .right { flex:1; min-width:0; display:flex; flex-direction:column; gap:7px; overflow:auto; padding-right:3px; }
.ull-main { width:100%; aspect-ratio:1/1; background:#111 center/contain no-repeat; border:1px solid var(--ud-border); border-radius:4px; cursor:zoom-in; display:flex; align-items:center; justify-content:center; color:var(--ud-text-dim); font-size:10px; }
.ull-strip { display:flex; gap:4px; overflow-x:auto; padding-bottom:2px; scrollbar-width:thin; scrollbar-color:#555 #1a1a1a; }
.ull-pop, .ull-pop * { scrollbar-width:thin; scrollbar-color:#555 #1a1a1a; }
.ull-strip img { width:48px; height:48px; object-fit:cover; border-radius:3px; border:1px solid var(--ud-border); cursor:pointer; flex:none; background:#111; }
.ull-strip img.on { border-color:var(--ud-accent); }
.ull-file { display:flex; align-items:center; gap:6px; padding:4px 6px; background:#1e1e1e; border:1px solid var(--ud-border); border-radius:4px; }
.ull-file .nm { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-size:11px; }
.ull-file .sz { color:var(--ud-text-dim); font-size:10px; flex:none; }
.ull-kv { display:grid; grid-template-columns:auto 1fr; gap:3px 10px; font-size:10px; }
.ull-kv .k { color:var(--ud-text-dim); }
.ull-link { color:var(--ud-accent); text-decoration:none; cursor:pointer; }
.ull-link:hover { text-decoration:underline; }

/* info panel */
.ull-info { display:flex; gap:12px; min-height:0; flex:1; }
.ull-info .left { width:40%; flex:none; display:flex; flex-direction:column; gap:6px; min-width:0; }
.ull-info .right { flex:1; min-width:0; display:flex; flex-direction:column; gap:8px; overflow:auto; padding-right:3px; }
.ull-info .ull-main { aspect-ratio:3/4; }
.ull-pic-row { display:flex; gap:4px; flex-wrap:wrap; }
.ull-seg { display:inline-flex; border:1px solid var(--ud-border); border-radius:4px; overflow:hidden; }
.ull-seg span { padding:2px 8px; cursor:pointer; font-size:10px; color:var(--ud-text-dim); }
.ull-seg span.on { background:var(--ud-accent); color:#fff; }
.ull-title { font-size:14px; font-weight:600; color:var(--ud-text); line-height:1.2; }

/* settings */
.ull-grid2 { display:grid; grid-template-columns:auto 1fr; gap:6px 10px; align-items:center; }
.ull-grid2 .ull-in, .ull-grid2 .ull-sel { justify-self:start; }
.ull-grid2 .ull-in.wide { width:100%; justify-self:stretch; }
.ull-toggle { width:30px; height:16px; border-radius:16px; background:#3a3a3a; border:1px solid #000; position:relative; cursor:pointer; }
.ull-toggle::after { content:""; position:absolute; top:1px; left:1px; width:12px; height:12px; border-radius:50%; background:#8a8a8a; transition:left .12s; }
.ull-toggle.on { background:var(--ud-accent); }
.ull-toggle.on::after { left:15px; background:#fff; }

/* lightbox */
.ull-lightbox { position:fixed; inset:0; z-index:10060; background:rgba(0,0,0,.88); display:flex; align-items:center; justify-content:center; gap:10px; outline:none; font-family:var(--ud-font); }
.ull-lb-main { display:flex; flex-direction:column; align-items:center; gap:6px; max-width:88vw; max-height:94vh; }
.ull-lb-img { max-width:88vw; max-height:82vh; object-fit:contain; border-radius:4px; background:#000; }
.ull-lb-cap { color:#bbb; font-size:11px; }
.ull-lb-bar { display:flex; gap:6px; }
.ull-btn.lb { font-size:22px; padding:6px 14px; background:#222; }
.ull-btn.lb.close { position:absolute; top:12px; right:14px; font-size:14px; }
`;
    document.head.appendChild(s);
}
