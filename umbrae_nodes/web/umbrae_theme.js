// umbrae_theme.js
// Single injected stylesheet for the umbrae node UI. One flat surface (the
// node body shows through), a single blue accent, controls as subtle insets.
// All colors are CSS custom properties so the accent is changed in one place.

const STYLE_ID = "umbrae-theme-v1";

export const UMBRAE_ACCENT = "#7aa8d4";

// One title/body color pair for every umbrae node. Applied only where the user has
// not already colored the node (pass force=true to override, e.g. on a fresh node).
export const NODE_TITLE_COLOR = "#1f1f1f";
export const NODE_BODY_COLOR = "#2a2a2a";
export function applyNodeColors(node, force = false) {
    if (force || !node.bgcolor) node.bgcolor = NODE_BODY_COLOR;
    if (force || !node.color) node.color = NODE_TITLE_COLOR;
}

export function injectTheme() {
    if (document.getElementById(STYLE_ID)) return;
    const s = document.createElement("style");
    s.id = STYLE_ID;
    s.textContent = `
.ud-root, .us-root, .lbu-root, .lbu-popup, .unp-m {
    /* ── tokens ───────────────────────────────────────────── */
    --ud-accent:        ${UMBRAE_ACCENT};
    --ud-accent-hover:  #92bbe0;
    --ud-inset:         #202020;   /* control background (subtle inset) */
    --ud-inset-hover:   #262626;
    --ud-border:        #3a3a3a;   /* thin border on controls only */
    --ud-divider:       #383838;   /* hairline between major groups */
    --ud-text:          #dddddd;
    --ud-text-dim:      #888888;
    --ud-font:          system-ui, 'Segoe UI', sans-serif;
}
.ud-root {
    /* one continuous surface — no inner boxes, no card borders */
    background: transparent;
    box-sizing: border-box;
    width: 100%;
    padding: 8px 10px;
    display: flex; flex-direction: column; gap: 10px;
    font-family: var(--ud-font);
    color: var(--ud-text);
}
.ud-root * { box-sizing: border-box; font-family: inherit; }

/* ── Section (a logical group) ───────────────────────────── */
.ud-section { display: flex; flex-direction: column; gap: 6px; }
.ud-title {
    font-size: 9px; font-weight: 700; letter-spacing: .07em;
    text-transform: uppercase; color: var(--ud-accent);
    display: flex; align-items: center; gap: 5px; user-select: none;
}
.ud-title.clickable { cursor: pointer; }
.ud-title.clickable:hover { color: var(--ud-accent-hover); }
.ud-title-arrow {
    font-size: 8px; transition: transform .15s; display: inline-block;
    color: var(--ud-text-dim);
}
.ud-section.collapsed .ud-title-arrow { transform: rotate(-90deg); }
.ud-section.collapsed .ud-section-body { display: none; }
.ud-section-body { display: flex; flex-direction: column; gap: 6px; }

/* ── Divider ─────────────────────────────────────────────── */
.ud-divider { height: 1px; background: var(--ud-divider); border: none; margin: 1px 0; }

/* ── Label + small caption ──────────────────────────────── */
.ud-label { font-size: 10px; color: var(--ud-text-dim); }

/* ── Pill row (single-select chips) ─────────────────────── */
.ud-pillrow { display: flex; flex-wrap: wrap; gap: 4px; }
.ud-pill {
    flex: 1 1 auto; min-width: 48px; height: 24px; padding: 0 8px;
    background: var(--ud-inset); border: 1px solid var(--ud-border);
    border-radius: 4px; color: var(--ud-text-dim);
    font-size: 10px; cursor: pointer; transition: all .12s;
}
.ud-pill:hover { background: var(--ud-inset-hover); color: var(--ud-text); }
.ud-pill.active { background: var(--ud-accent); border-color: var(--ud-accent); color: #fff; }

/* ── Toggle (full-width on/off) ─────────────────────────── */
.ud-toggle {
    width: 100%; padding: 6px 0; border-radius: 4px;
    background: var(--ud-inset); border: 1px solid var(--ud-border);
    color: var(--ud-text-dim); font-size: 11px; font-weight: 600;
    cursor: pointer; transition: all .12s;
}
.ud-toggle:hover { background: var(--ud-inset-hover); color: var(--ud-text); }
.ud-toggle.on { background: var(--ud-accent); border-color: var(--ud-accent); color: #fff; }

/* ── Number input (inset, centered, tiny spinners) ──────── */
.ud-num {
    display: flex; align-items: stretch; background: var(--ud-inset);
    border: 1px solid var(--ud-border); border-radius: 4px; overflow: hidden;
}
.ud-num:focus-within { border-color: var(--ud-accent); }
.ud-num input {
    flex: 1; min-width: 0; background: transparent; border: none; outline: none;
    padding: 3px 6px; color: var(--ud-accent); font-size: 11px; font-weight: 600;
    text-align: center;
}
.ud-num-spin { display: flex; flex-direction: column; width: 15px; border-left: 1px solid var(--ud-border); }
.ud-num-spin button {
    flex: 1; background: #232323; border: none; padding: 0; cursor: pointer;
    color: var(--ud-text-dim); position: relative; font-size: 8px; line-height: 1;
}
.ud-num-spin button:hover { background: #2c2c2c; color: var(--ud-accent); }
.ud-num-spin .up { border-bottom: 1px solid var(--ud-border); }

/* ── Labeled row (label left, control right) ────────────── */
.ud-row { display: flex; align-items: center; gap: 8px; }
.ud-row > .ud-label { flex-shrink: 0; }
.ud-row > .ud-grow { flex: 1; min-width: 0; }

/* ── Text input ─────────────────────────────────────────── */
.ud-text {
    width: 100%; background: var(--ud-inset); border: 1px solid var(--ud-border);
    border-radius: 4px; padding: 5px 8px; color: var(--ud-text);
    font-size: 11px; outline: none;
}
.ud-text:focus { border-color: var(--ud-accent); }

/* ── Select (dropdown) ──────────────────────────────────── */
.ud-select {
    width: 100%; background: var(--ud-inset); border: 1px solid var(--ud-border);
    border-radius: 4px; padding: 4px 6px; color: var(--ud-text); font-size: 11px; outline: none;
}
.ud-select:focus { border-color: var(--ud-accent); }
.ud-select option { background: var(--ud-inset); color: var(--ud-text); }

/* ── Control driven by a wired input: shown but not editable ── */
.ud-linked { opacity: .45; pointer-events: none; }

/* ── Layout helpers for stacked panels ──────────────────── */
.ud-ruled > div + div { border-top: 1px solid var(--ud-divider); padding-top: 9px; }
.ud-ruled > div > .ud-title { margin-bottom: 6px; }
.ud-ruled > div > .ud-label { margin-bottom: 4px; }
.ud-stack { display: flex; flex-direction: column; gap: 8px; }
.ud-padrow { display: flex; gap: 4px; align-items: stretch; }
.ud-padrow > .ud-grow { flex: 1; min-width: 0; }
.ud-padrow > .ud-text { flex: 1; min-width: 0; }
.ud-unit { flex: none; }
.ud-unit .ud-pill { flex: none; width: 34px; min-width: 0; padding: 0; }
.ud-adv-head { display: flex; align-items: center; justify-content: space-between; cursor: pointer; user-select: none; }
.ud-adv-head .ud-title { margin-bottom: 0; }
.ud-adv-arrow { font-size: 9px; color: var(--ud-text-dim); transition: transform .12s; }
.ud-adv-head.open .ud-adv-arrow { transform: rotate(90deg); }
.ud-adv-body { margin-top: 8px; }

/* ── Info line ──────────────────────────────────────────── */
.ud-info { font-size: 10px; color: var(--ud-text-dim); line-height: 1.5; }
`;
    document.head.appendChild(s);
}
