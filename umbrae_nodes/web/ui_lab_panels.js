// ui_lab_panels.js  --  DEV ONLY (UI design lab; safe to delete with ui_lab.js, ui_lab_node.py, dev/)
//
// The same set of controls built three ways, to compare looks side by side:
//   A  current   cir-* helpers (what the crop nodes use today)
//   B  unified   ud-* components (what Save Image Smart uses)
//   C  skinned   B with the theme variables overridden (shows how a Pixaroma-style
//                look could be applied by changing tokens only)
// No ComfyUI imports here, so the dev/ui_lab_preview.html page can load it too.

import { injectTheme } from "./umbrae_theme.js";
import { makeNum, makeChips, makeToggle, makeText, subLabel } from "./umbrae_panel_controls.js";
import {
    createSection, createDivider, createPillRow, createToggle,
    createNumber, createText, createRow, createInfo,
} from "./umbrae_components.js";

const log = (what) => (v) => console.log("[ui lab]", what, v);

const SHAPES = [{ val: "nearest", label: "Nearest" }, { val: "bilinear", label: "Bilinear" }];
const UNITS = [{ val: "percentage", label: "%" }, { val: "pixels", label: "px" }];
const EXTRACT = [{ val: "both", label: "Both" }, { val: "bbox", label: "Bbox" }, { val: "mask", label: "Mask" }];

// ── A: current look (cir-*) ───────────────────────────────────────────────────
export function buildCurrent(onResize = () => {}) {
    injectTheme();
    const root = document.createElement("div");
    root.className = "cir-root";

    const label = (t) => { const d = document.createElement("div"); d.className = "cir-label"; d.textContent = t; return d; };
    const sec = (...kids) => { const d = document.createElement("div"); d.append(...kids); return d; };

    const mask = sec(label("Mask"), makeChips(SHAPES, "nearest", log("mask")).el);

    const padRow = document.createElement("div"); padRow.className = "cir-pad-row";
    const padNum = makeNum(10, 0, 100000, 1, log("padding"));
    padNum.wrap.className += " cir-pad-inp";
    const padUnit = document.createElement("div"); padUnit.className = "cir-unit";
    padUnit.append(makeChips(UNITS, "percentage", log("unit")).el);
    padRow.append(padNum.wrap, padUnit);
    const pad = sec(subLabel("Padding"), padRow);

    const tog = sec(makeToggle(true, "Min crop size: on", "Min crop size: off", log("toggle")).el);
    const name = sec(subLabel("Filename"), makeText("{stem}_{index}", "pattern", log("text")).el);

    const advHead = document.createElement("div"); advHead.className = "cir-adv-head";
    const advTitle = label("Advanced"); advTitle.style.marginBottom = "0";
    const advArrow = document.createElement("div"); advArrow.className = "cir-arrow"; advArrow.textContent = "▶";
    advHead.append(advTitle, advArrow);
    const advBody = document.createElement("div"); advBody.className = "cir-adv-body"; advBody.style.display = "none";
    advBody.append(
        makeToggle(true, "Region: merge detections", "Region: keep separate", log("flat")).el,
        sec(subLabel("Extract — Region"), makeChips(EXTRACT, "both", log("extract")).el),
    );
    advHead.onclick = () => {
        const open = advBody.style.display === "none";
        advBody.style.display = open ? "" : "none";
        advHead.classList.toggle("open", open);
        onResize();
    };
    root.append(mask, pad, tog, name, sec(advHead, advBody));
    return root;
}

// ── B: unified look (ud-*) ────────────────────────────────────────────────────
export function buildUnified(onResize = () => {}) {
    injectTheme();
    const root = document.createElement("div");
    root.className = "ud-root";

    const mask = createSection("Mask");
    mask.body.append(createPillRow(SHAPES, "nearest", log("mask")).el);

    const pad = createSection("Padding");
    const padRow = document.createElement("div");
    padRow.style.cssText = "display:flex; gap:4px; align-items:stretch;";
    const padNum = createNumber(10, 0, 100000, 1, log("padding"));
    padNum.el.style.flex = "1";
    const unit = createPillRow(UNITS, "percentage", log("unit"));
    unit.el.style.flex = "none";
    padRow.append(padNum.el, unit.el);
    pad.body.append(padRow);

    const tog = createToggle(true, "Min crop size: on", "Min crop size: off", log("toggle"));
    const name = createRow("Filename", createText("{stem}_{index}", "pattern", log("text")));

    const adv = createSection("Advanced", { collapsible: true, collapsed: true, onToggle: onResize });
    adv.body.append(
        createToggle(true, "Region: merge detections", "Region: keep separate", log("flat")).el,
        createRow("Extract", createPillRow(EXTRACT, "both", log("extract")), { grow: true }),
        createInfo("Info lines use the dim text color.").el,
    );

    root.append(mask.el, createDivider(), pad.el, createDivider(), tog.el, name, createDivider(), adv.el);
    return root;
}

// ── C: unified look with the theme tokens overridden ──────────────────────────
// Only CSS variables change; no class or layout differs from B.
export const SKIN_TOKENS = {
    "--ud-accent": "#f66744",
    "--ud-accent-hover": "#ff8466",
    "--ud-inset": "#1d1d1d",
    "--ud-inset-hover": "#232323",
    "--ud-border": "#3a3a3a",
    "--ud-divider": "#3a3a3a",
};

export function buildSkinned(onResize = () => {}) {
    const root = buildUnified(onResize);
    for (const [k, v] of Object.entries(SKIN_TOKENS)) root.style.setProperty(k, v);
    return root;
}

export const VARIANTS = [
    { key: "current", title: "A · current (cir-*)", build: buildCurrent },
    { key: "unified", title: "B · unified (ud-*)", build: buildUnified },
    { key: "skinned", title: "C · unified, tokens overridden", build: buildSkinned },
];
