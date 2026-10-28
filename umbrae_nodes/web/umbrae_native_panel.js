// umbrae_native_panel.js
// Skins a node that uses ComfyUI's built-in widgets: the native widgets stay on the node
// (same names, same values, same saved workflows, Python untouched) but are hidden, and a
// themed panel reads and writes them. A control whose input is wired is shown disabled.
//
// spec = [{ title, rows: [row | [row, row]] }]
// row  = { name, label?, kind?: "number"|"pills"|"select"|"toggle"|"text",
//          step?, on?, off?, showIf?: (get) => boolean }

import { app } from "../../scripts/app.js";
import { injectTheme } from "./umbrae_theme.js";
import {
    createPillRow, createToggle, createNumber, createText, createSelect, createLabel,
} from "./umbrae_components.js";
import { measureRootContent, attachAutoHeight, applyAdaptiveCanvasOnly } from "./umbrae_resize.js";

function hideWidget(w) {
    if (!w || w._umbHidden) return;
    w._umbHidden = true;
    w.hidden = true;
    w.computeSize = () => [0, -4];
    if (!w.options) w.options = {};
    w.options.canvasOnly = true;
    const hide = () => { if (w.element) w.element.style.display = "none"; if (w.inputEl) w.inputEl.style.display = "none"; };
    hide();
    requestAnimationFrame(hide);
}

function kindOf(w, row) {
    if (row.kind) return row.kind;
    switch (w.type) {
        case "number": case "slider": return "number";
        case "combo": return (w.options?.values?.length ?? 0) <= 4 ? "pills" : "select";
        case "toggle": case "boolean": return "toggle";
        default: return "text";
    }
}

const prettify = (n) => n.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

export function skinNativeWidgets(node, spec) {
    injectTheme();
    const find = (name) => node.widgets?.find((w) => w.name === name);
    const get = (name) => find(name)?.value;
    const controls = [];   // { w, row, wrap, set(v) }
    let auto = null;
    const relayout = () => auto?.scheduleRelayout();

    function commit(w, v) {
        w.value = v;
        try { w.callback?.(v, app.canvas, node, [0, 0], null); } catch (e) { console.warn("[umbrae] widget callback", e); }
        node.setDirtyCanvas?.(true, true);
        refresh();
    }

    function buildControl(row) {
        const w = find(row.name);
        if (!w) return null;
        const kind = kindOf(w, row);
        const tip = w.tooltip ?? w.options?.tooltip;
        const label = row.label ?? prettify(row.name);
        const wrap = document.createElement("div");
        let ctl;
        if (kind === "toggle") {
            const on = row.on ?? `${label}: On`, off = row.off ?? `${label}: Off`;
            ctl = createToggle(!!w.value, on, off, (v) => commit(w, v), { tooltip: tip });
        } else {
            wrap.append(createLabel(label));
            if (kind === "number") {
                const prec = w.options?.precision;
                const step = row.step ?? (prec > 0 ? Math.pow(10, -prec) : (Number.isInteger(w.value) ? 1 : 0.01));
                const min = row.min ?? w.options?.min ?? -Infinity;
                const max = row.max ?? w.options?.max ?? Infinity;
                ctl = createNumber(Number(w.value ?? 0), min, max, step, (v) => commit(w, v), { tooltip: tip });
            } else if (kind === "pills" || kind === "select") {
                const items = (w.options?.values ?? []).map((v) => ({ val: v, label: String(v) }));
                ctl = kind === "pills"
                    ? createPillRow(items, w.value, (v) => commit(w, v), { tooltip: tip })
                    : createSelect(items, w.value, (v) => commit(w, v), { tooltip: tip });
            } else {
                ctl = createText(w.value ?? "", row.placeholder ?? "", (v) => commit(w, v), { tooltip: tip });
            }
        }
        wrap.appendChild(ctl.el);
        hideWidget(w);
        return { w, row, wrap, set: (v) => (ctl.setValue ?? ctl.setActive)?.call(ctl, v) };
    }

    const root = document.createElement("div");
    root.className = "ud-root ud-ruled";
    for (const sec of spec) {
        const secEl = document.createElement("div");
        const title = document.createElement("div");
        title.className = "ud-title"; title.textContent = sec.title;
        const body = document.createElement("div");
        body.className = "ud-stack";
        for (const item of sec.rows) {
            const rows = Array.isArray(item) ? item : [item];
            const holder = Array.isArray(item) ? Object.assign(document.createElement("div"), { className: "ud-padrow" }) : body;
            let made = 0;
            for (const row of rows) {
                const c = buildControl(row);
                if (!c) continue;
                if (Array.isArray(item)) c.wrap.classList.add("ud-grow");
                holder.appendChild(c.wrap); controls.push(c); made++;
            }
            if (Array.isArray(item) && made) body.appendChild(holder);
        }
        if (!body.children.length) continue;
        secEl.append(title, body);
        root.appendChild(secEl);
    }

    function refresh() {
        for (const c of controls) {
            c.set(c.w.value);
            const slot = node.inputs?.find((i) => i.name === c.w.name);
            c.wrap.classList.toggle("ud-linked", slot?.link != null);
            const show = c.row.showIf ? !!c.row.showIf(get) : true;
            c.wrap.style.display = show ? "" : "none";
        }
        // hide a section whose controls are all hidden
        for (const secEl of root.children) {
            const any = [...secEl.querySelectorAll(":scope > .ud-stack > div")].some((d) => d.style.display !== "none");
            secEl.style.display = any ? "" : "none";
        }
        relayout();
    }

    const measureH = () => measureRootContent(root);
    const dw = node.addDOMWidget("umbrae_panel", "custom", root, {
        getValue: () => null, setValue: () => {}, serialize: false,
        getMinHeight: measureH, getMaxHeight: measureH, margin: 4,
    });
    applyAdaptiveCanvasOnly(dw);
    if (dw?.element) { dw.element.style.width = "100%"; dw.element.style.boxSizing = "border-box"; }
    const W = Math.max(node.size?.[0] ?? 0, 300);
    if (typeof node.setSize === "function") node.setSize([W, node.size?.[1] ?? 120]);
    auto = attachAutoHeight(node, root, dw);

    // keep the panel in step with the widgets: workflow load, wiring changes, and
    // values changed by other code (e.g. control_after_generate)
    const chain = (name, fn) => { const o = node[name]; node[name] = function () { const r = o?.apply(this, arguments); fn(); return r; }; };
    chain("onConfigure", () => setTimeout(refresh, 0));
    chain("onConnectionsChange", refresh);
    let snap = "";
    chain("onDrawForeground", () => {
        const s = controls.map((c) => c.w.value).join("\u0001");
        if (s !== snap) { snap = s; refresh(); }
    });
    const onRemoved = node.onRemoved;
    node.onRemoved = function () { auto?.dispose(); return onRemoved?.apply(this, arguments); };

    refresh();
    return { root, refresh };
}
