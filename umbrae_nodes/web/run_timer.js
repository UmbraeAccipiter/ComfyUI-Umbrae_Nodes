// run_timer.js — umbrae_nodes
//
// run timer [umbrae]: whole-workflow stopwatch + expandable run history.
//
// Face layout
//   ┌──────────────────────────────┐
//   │          0:14.8              │  clock: resets on Run, counts up live,
//   │        ● running             │         freezes on the total at the end
//   ├──────────────────────────────┤
//   │ LAST 3 RUNS          ▲ ▼  ✕  │  ▲ shows one more row, ▼ one fewer
//   │ 01 ⚡ 0:14.8          14:02  │  newest run on top, fastest shown marked
//   │ 02    0:15.1          13:58  │
//   │ 03    0:16.0          13:51  │
//   └──────────────────────────────┘
//
// The run itself is global (execution_start .. finish), so every run timer on
// the canvas shares one origin and records the same total. Only successful runs
// go into the history (an interrupted / errored run gives a partial, misleading
// time); the clock still freezes on them so you can see where it stopped.
//
// Persistence: node.properties (serialized with the workflow).
//   runTimerLastMs   frozen total of the last run (restored on load)
//   runTimerRows     visible history rows, 0 = clock only
//   runTimerHistory  [{ms, at}] newest first, capped at HISTORY_CAP
// The load path (onNodeCreated / onConfigure) only READS properties; writes
// happen on a finished run, an arrow click, or Clear.

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { injectTheme, applyNodeColors } from "./umbrae_theme.js";

const NODE_TYPE  = "UmbraeRunTimer";
const STYLE_ID   = "umbrae-run-timer-styles";

const PROP_LAST  = "runTimerLastMs";
const PROP_ROWS  = "runTimerRows";
const PROP_HIST  = "runTimerHistory";

const HISTORY_CAP   = 50;   // entries kept; the ▲ arrow can show up to this many
const ROWS_DEFAULT  = 0;    // fresh node = clock only
const ROW_STEP_BIG  = 5;    // shift-click on an arrow

const DEFAULT_W = 240;
const MIN_W     = 180;

// ---------------------------------------------------------------------------
// CSS
// ---------------------------------------------------------------------------

function ensureStyles() {
    injectTheme();
    if (document.getElementById(STYLE_ID)) return;
    const s = document.createElement("style");
    s.id = STYLE_ID;
    s.textContent = `
        .ud-root.urt-root { gap: 0; user-select: none; }
        .urt-clock-wrap {
            display: flex; flex-direction: column; align-items: center;
            padding: 4px 0 6px;
        }
        .urt-clock {
            font-family: ui-monospace, 'Cascadia Mono', Consolas, 'DejaVu Sans Mono', monospace;
            font-size: 28px; font-weight: 600; line-height: 1.1;
            color: var(--ud-text); letter-spacing: .02em;
            font-variant-numeric: tabular-nums;
            transition: color .15s;
        }
        .urt-clock.running { color: var(--ud-accent); }
        .urt-clock.stopped { color: var(--ud-text-dim); }
        .urt-status {
            display: flex; align-items: center; gap: 5px;
            font-size: 9px; font-weight: 700; letter-spacing: .08em;
            text-transform: uppercase; color: var(--ud-text-dim);
            margin-top: 2px; min-height: 12px;
        }
        .urt-dot {
            width: 6px; height: 6px; border-radius: 50%;
            background: var(--ud-border); flex: none;
        }
        .urt-dot.run  { background: var(--ud-accent); animation: urt-pulse 1s ease-in-out infinite; }
        .urt-dot.done { background: #7fc27f; }
        .urt-dot.stop { background: #c27f7f; }
        @keyframes urt-pulse { 0%,100% { opacity: 1; } 50% { opacity: .35; } }

        .urt-header {
            display: flex; align-items: center; gap: 4px;
            padding: 5px 0 4px;
            border-top: 1px solid var(--ud-divider);
            color: var(--ud-accent);
            font-size: 9px; font-weight: 700;
            text-transform: uppercase; letter-spacing: .07em;
        }
        .urt-header.has-rows { border-bottom: 1px solid var(--ud-divider); }
        .urt-header-label { flex: 1; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
        .urt-btn {
            background: var(--ud-inset); border: 1px solid var(--ud-border);
            color: var(--ud-text-dim); cursor: pointer;
            width: 20px; height: 16px; padding: 0; border-radius: 3px;
            font-size: 9px; line-height: 1; flex: none;
            display: inline-flex; align-items: center; justify-content: center;
            transition: all .12s;
        }
        .urt-btn:hover:not(:disabled) { background: var(--ud-inset-hover); color: var(--ud-accent); border-color: var(--ud-accent); }
        .urt-btn:disabled { opacity: .35; cursor: default; }
        .urt-btn.clear { margin-left: 4px; font-size: 10px; }

        .urt-rows { display: flex; flex-direction: column; }
        .urt-row {
            display: flex; align-items: center; gap: 6px;
            height: 20px; font-size: 11px;
            border-bottom: 1px solid var(--ud-divider);
            font-variant-numeric: tabular-nums;
        }
        .urt-row:last-child { border-bottom: none; }
        .urt-row.now  { color: var(--ud-accent); }
        .urt-row.now .urt-idx { color: var(--ud-accent); }
        .urt-row.empty { color: var(--ud-text-dim); opacity: .5; }
        .urt-idx  { width: 16px; flex: none; color: var(--ud-text-dim); font-size: 9px; text-align: right; }
        .urt-mark { width: 12px; flex: none; text-align: center; font-size: 10px; color: #7fc27f; }
        .urt-time {
            flex: 1; min-width: 0;
            font-family: ui-monospace, 'Cascadia Mono', Consolas, 'DejaVu Sans Mono', monospace;
            color: inherit;
        }
        .urt-row:not(.now) .urt-time { color: var(--ud-text); }
        .urt-row.empty .urt-time { color: inherit; }
        .urt-at { flex: none; color: var(--ud-text-dim); font-size: 9px; }
    `;
    document.head.appendChild(s);
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

// m:ss.t under an hour, h:mm:ss from an hour up. Tenths are floored so the
// live clock never shows a value ahead of the real elapsed time.
function fmtClock(ms) {
    const n = Math.max(0, Number(ms) || 0);
    const tenths = Math.floor(n / 100);
    const s = Math.floor(tenths / 10);
    if (s >= 3600) {
        const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
        return `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
    }
    const m = Math.floor(s / 60), sec = s % 60, t = tenths % 10;
    return `${m}:${String(sec).padStart(2, "0")}.${t}`;
}

// 24h clock-time of a run, for the dim column at the right of each row.
function fmtAt(epochMs) {
    const t = Number(epochMs);
    if (!isFinite(t) || t <= 0) return "";
    const d = new Date(t);
    return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

// ---------------------------------------------------------------------------
// Properties (read-normalised; never written on the load path)
// ---------------------------------------------------------------------------

function getHist(node) {
    const raw = node.properties?.[PROP_HIST];
    if (!Array.isArray(raw)) return [];
    const out = [];
    for (const e of raw) {
        if (!e || typeof e !== "object") continue;
        const ms = Number(e.ms);
        if (!isFinite(ms) || ms < 0) continue;
        out.push({ ms: Math.round(ms), at: Number(e.at) || 0 });
        if (out.length >= HISTORY_CAP) break;
    }
    return out;
}

function getRows(node) {
    const r = Number(node.properties?.[PROP_ROWS]);
    if (!isFinite(r)) return ROWS_DEFAULT;
    return Math.max(0, Math.min(HISTORY_CAP, Math.round(r)));
}

function setRows(node, n) {
    node.properties ||= {};
    node.properties[PROP_ROWS] = Math.max(0, Math.min(HISTORY_CAP, Math.round(n)));
}

function pushHistory(node, ms) {
    const dur = Math.round(Number(ms));
    if (!isFinite(dur) || dur < 0) return;
    node.properties ||= {};
    node.properties[PROP_HIST] = [{ ms: dur, at: Date.now() }, ...getHist(node)].slice(0, HISTORY_CAP);
}

function clearHistory(node) {
    node.properties ||= {};
    node.properties[PROP_HIST] = [];
    render(node);
}

function historyText(node) {
    const hist = getHist(node);
    return hist.map((e, i) => {
        const at = fmtAt(e.at);
        return `${String(i + 1).padStart(2, "0")}  ${fmtClock(e.ms)}${at ? "  " + at : ""}`;
    }).join("\n");
}

async function copyHistory(node) {
    const txt = historyText(node);
    if (!txt) return;
    try { await navigator.clipboard.writeText(txt); }
    catch {
        const ta = document.createElement("textarea");
        ta.value = txt; document.body.appendChild(ta); ta.select();
        try { document.execCommand("copy"); } catch {}
        ta.remove();
    }
}

// ---------------------------------------------------------------------------
// Sizing (same approach as frame_toggle_node.js: compute, don't measure)
// ---------------------------------------------------------------------------

const H_PAD    = 16;   // widget margins
const H_CLOCK  = 56;   // clock + status block
const H_HEADER = 24;   // "last N runs" row with the arrows
const H_ROW    = 20;
const H_CHROME = 42;   // title bar + slot area LiteGraph adds around the widget

function calcNodeHeight(rows) {
    return H_PAD + H_CLOCK + H_HEADER + rows * H_ROW + H_CHROME;
}

function applySize(node) {
    const rows = getRows(node);
    const h = calcNodeHeight(rows);
    const w = Math.max(node.size?.[0] || DEFAULT_W, MIN_W);
    node._urtComputedSize = [w, h];
    if (Array.isArray(node.size)) { node.size[0] = w; node.size[1] = h; }
    else node.size = [w, h];
    app.graph?.setDirtyCanvas(true, true);
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
}

function renderClock(node) {
    const ui = node._urt;
    if (!ui) return;
    const ms = node._urtRunning ? node._urtDisplayMs : (node._urtDisplayMs ?? 0);
    const txt = fmtClock(ms);
    if (ui.clock.textContent !== txt) ui.clock.textContent = txt;

    ui.clock.classList.toggle("running", !!node._urtRunning);
    ui.clock.classList.toggle("stopped", !node._urtRunning && node._urtLastState === "stop");

    let dot = "", label = "";
    if (node._urtRunning)                      { dot = "run";  label = "running"; }
    else if (node._urtLastState === "done")    { dot = "done"; label = "done"; }
    else if (node._urtLastState === "stop")    { dot = "stop"; label = "stopped"; }
    else if (node._urtDisplayMs > 0)           { dot = "";     label = "last run"; }
    else                                        { dot = "";     label = "ready"; }
    ui.dot.className = "urt-dot" + (dot ? " " + dot : "");
    if (ui.statusText.textContent !== label) ui.statusText.textContent = label;
}

function render(node) {
    const ui = node._urt;
    if (!ui) return;
    renderClock(node);

    const rows = getRows(node);
    const hist = getHist(node);
    const shown = hist.slice(0, rows);

    ui.label.textContent = rows === 0 ? "history" : (rows === 1 ? "last run" : `last ${rows} runs`);
    ui.header.classList.toggle("has-rows", rows > 0);
    ui.up.disabled   = rows >= HISTORY_CAP;
    ui.down.disabled = rows <= 0;
    ui.clear.disabled = hist.length === 0;
    ui.clear.style.display = hist.length === 0 ? "none" : "";

    ui.rows.innerHTML = "";
    if (rows === 0) return;

    let bestIdx = -1;
    if (shown.length > 1) {
        bestIdx = 0;
        for (let i = 1; i < shown.length; i++) if (shown[i].ms < shown[bestIdx].ms) bestIdx = i;
    }

    for (let i = 0; i < rows; i++) {
        const e = shown[i];
        const row = el("div", "urt-row" + (e ? (i === 0 ? " now" : "") : " empty"));
        row.appendChild(el("span", "urt-idx", String(i + 1).padStart(2, "0")));
        row.appendChild(el("span", "urt-mark", e && i === bestIdx ? "⚡" : ""));
        row.appendChild(el("span", "urt-time", e ? fmtClock(e.ms) : "–"));
        row.appendChild(el("span", "urt-at", e ? fmtAt(e.at) : ""));
        if (e) {
            row.title = (i === 0 ? "Newest run" : "")
                + (i === bestIdx ? (i === 0 ? ", fastest shown" : "Fastest shown") : "");
        }
        ui.rows.appendChild(row);
    }
}

function changeRows(node, delta) {
    const cur = getRows(node);
    const next = Math.max(0, Math.min(HISTORY_CAP, cur + delta));
    if (next === cur) return;
    setRows(node, next);
    render(node);
    applySize(node);
}

// ---------------------------------------------------------------------------
// Run lifecycle (shared by every run timer on the canvas)
// ---------------------------------------------------------------------------

const _timers = new Set();
let _tick = null;
let _runLive = false;
let _runStart = null;

function tick() {
    const now = performance.now();
    let any = false;
    for (const node of _timers) {
        if (!node._urtRunning) continue;
        any = true;
        node._urtDisplayMs = now - node._urtStart;
        renderClock(node);
    }
    if (!any) { clearInterval(_tick); _tick = null; }
}
function ensureTick() { if (_tick == null) _tick = setInterval(tick, 100); }

// A node created mid-run (tab switch, fresh drop) joins the run in progress.
function adoptLiveRun(node) {
    if (!_runLive || _runStart == null || node._urtRunning) return;
    node._urtRunning = true;
    node._urtStart = _runStart;
    node._urtDisplayMs = performance.now() - _runStart;
    node._urtLastState = "";
    renderClock(node);
    ensureTick();
}

function startAll() {
    _runLive = true;
    _runStart = performance.now();
    for (const node of _timers) {
        node._urtRunning = true;
        node._urtStart = _runStart;
        node._urtDisplayMs = 0;
        node._urtLastState = "";
        renderClock(node);
    }
    if (_timers.size) ensureTick();
}

function finishAll(success) {
    _runLive = false;
    for (const node of _timers) {
        if (!node._urtRunning) continue;          // idempotent: first finish wins
        node._urtRunning = false;
        node._urtDisplayMs = performance.now() - node._urtStart;
        node._urtLastState = success ? "done" : "stop";
        node.properties ||= {};
        node.properties[PROP_LAST] = Math.round(node._urtDisplayMs);
        if (success) pushHistory(node, node._urtDisplayMs);
        render(node);
    }
}

let _listeners = false;
function installRunListeners() {
    if (_listeners) return;
    _listeners = true;
    api.addEventListener("execution_start", () => startAll());
    // Older builds: 'executing' with a null node = queue item finished.
    api.addEventListener("executing", (e) => {
        const d = e?.detail;
        const id = (d && typeof d === "object") ? d.node : d;
        if (id == null) finishAll(true);
    });
    api.addEventListener("execution_success", () => finishAll(true));
    api.addEventListener("execution_error", () => finishAll(false));
    api.addEventListener("execution_interrupted", () => finishAll(false));
}

// ---------------------------------------------------------------------------
// Node UI
// ---------------------------------------------------------------------------

function buildUI(node) {
    const root = el("div", "ud-root urt-root");
    ["mousedown", "pointerdown", "touchstart"].forEach(ev =>
        root.addEventListener(ev, e => e.stopPropagation(), { passive: false }));
    // let the canvas keep zooming when the wheel is over the node
    root.addEventListener("wheel", e => e.stopPropagation(), { passive: true });

    const clockWrap = el("div", "urt-clock-wrap");
    const clock = el("div", "urt-clock", "0:00.0");
    const status = el("div", "urt-status");
    const dot = el("span", "urt-dot");
    const statusText = el("span", null, "ready");
    status.append(dot, statusText);
    clockWrap.append(clock, status);

    const header = el("div", "urt-header");
    const label = el("span", "urt-header-label", "history");
    const up = el("button", "urt-btn", "▲");
    up.title = "Show one more run (shift: five)";
    const down = el("button", "urt-btn", "▼");
    down.title = "Show one fewer run (shift: five)";
    const clear = el("button", "urt-btn clear", "✕");
    clear.title = "Clear the run history";
    up.addEventListener("click", e => { e.stopPropagation(); changeRows(node, e.shiftKey ? ROW_STEP_BIG : 1); });
    down.addEventListener("click", e => { e.stopPropagation(); changeRows(node, -(e.shiftKey ? ROW_STEP_BIG : 1)); });
    clear.addEventListener("click", e => { e.stopPropagation(); clearHistory(node); });
    header.append(label, up, down, clear);

    const rows = el("div", "urt-rows");
    root.append(clockWrap, header, rows);

    node._urt = { root, clock, dot, statusText, header, label, up, down, clear, rows };

    const w = node.addDOMWidget("run_timer_ui", "custom", root, {
        getValue: () => "",
        setValue: () => {},
        serialize: false,       // everything lives on node.properties
    });
    if (w?.element) {
        w.element.style.width = "100%";
        w.element.style.boxSizing = "border-box";
    }
}

// Restore the frozen total from the saved workflow. Read-only.
function restoreLast(node) {
    if (node._urtRunning) return;
    const ms = Number(node.properties?.[PROP_LAST]);
    node._urtDisplayMs = isFinite(ms) && ms >= 0 ? ms : 0;
    node._urtLastState = "";
}

app.registerExtension({
    name: "umbrae.runTimer",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;
        const proto = nodeType.prototype;
        if (proto._urtPatched) return;
        proto._urtPatched = true;

        const origCreated = proto.onNodeCreated;
        proto.onNodeCreated = function () {
            origCreated?.apply(this, arguments);
            ensureStyles();
            installRunListeners();
            applyNodeColors(this);
            this._urtRunning = false;
            this._urtDisplayMs = 0;
            this._urtLastState = "";
            this.size = [DEFAULT_W, calcNodeHeight(ROWS_DEFAULT)];
            this._urtComputedSize = [...this.size];
            buildUI(this);
            _timers.add(this);
            // configure() (saved properties) lands after onNodeCreated; render
            // once it has, and adopt a run already under way (tab switch).
            queueMicrotask(() => {
                restoreLast(this);
                adoptLiveRun(this);
                render(this);
                applySize(this);
            });
        };

        const origConfigure = proto.onConfigure;
        proto.onConfigure = function (info) {
            const r = origConfigure?.apply(this, arguments);
            restoreLast(this);
            adoptLiveRun(this);
            render(this);
            applySize(this);
            return r;
        };

        const origRemoved = proto.onRemoved;
        proto.onRemoved = function () {
            _timers.delete(this);
            this._urt = null;
            return origRemoved?.apply(this, arguments);
        };

        // LiteGraph calls computeSize() during interaction and would otherwise
        // snap the node back to its default height.
        proto.computeSize = function () {
            return [
                this._urtComputedSize?.[0] ?? DEFAULT_W,
                this._urtComputedSize?.[1] ?? calcNodeHeight(ROWS_DEFAULT),
            ];
        };

        // Width is free (above the minimum); height follows the row count.
        const origResize = proto.onResize;
        proto.onResize = function (size) {
            if (size[0] < MIN_W) size[0] = MIN_W;
            const h = calcNodeHeight(getRows(this));
            size[1] = h;
            this._urtComputedSize = [size[0], h];
            return origResize?.apply(this, arguments);
        };

        const origMenu = proto.getExtraMenuOptions;
        proto.getExtraMenuOptions = function (_, options) {
            const r = origMenu?.apply(this, arguments);
            const has = getHist(this).length > 0;
            options.push(
                { content: "Copy run times", disabled: !has, callback: () => copyHistory(this) },
                { content: "Clear run history", disabled: !has, callback: () => clearHistory(this) },
            );
            return r;
        };
    },
});
