// umbrae_theme.js
// Single injected stylesheet for the umbrae node UI. One flat surface (the
// node body shows through), a single blue accent, controls as subtle insets.
// All colors are CSS custom properties so the accent is changed in one place.

const STYLE_ID = "umbrae-theme-v1";

export const UMBRAE_ACCENT = "#7aa8d4";

export function injectTheme() {
    if (document.getElementById(STYLE_ID)) return;
    const s = document.createElement("style");
    s.id = STYLE_ID;
    s.textContent = `
.ud-root, .cir-root, .us-root, .lbu-root, .unp-m {
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

/* ── Crop-panel classes (cir-*) shared by Crop Image Region, Crop Image and Training Prep ── */
.cir-root { padding:8px 9px 9px; width:100%; box-sizing:border-box; display:flex; flex-direction:column; gap:10px; font-family:system-ui,'Segoe UI',sans-serif; color:var(--ud-text); background:transparent; }
.cir-root > div + div { border-top:1px solid var(--ud-divider); padding-top:9px; }
.cir-label { font-size:9px; font-weight:700; color:var(--ud-accent); text-transform:uppercase; letter-spacing:.07em; margin-bottom:6px; }
.cir-chips { display:flex; gap:4px; }
.cir-chip { flex:1; height:24px; background:var(--ud-inset); border:1px solid var(--ud-border); border-radius:4px; color:var(--ud-text-dim); font-size:10px; cursor:pointer; font-family:inherit; padding:0; transition:all .12s; }
.cir-chip:hover { color:var(--ud-text); }
.cir-chip.active { background:var(--ud-accent); color:#fff; border-color:var(--ud-accent); font-weight:600; }
.cir-numinput { display:flex; background:var(--ud-inset); border:1px solid var(--ud-border); border-radius:4px; overflow:hidden; box-sizing:border-box; }
.cir-numinput:focus-within { border-color:var(--ud-accent); }
.cir-numinput input { flex:1; min-width:0; background:transparent; border:none; outline:none; padding:3px 6px; color:var(--ud-accent); font-size:11px; font-weight:600; text-align:center; font-family:inherit; }
.cir-spin { display:flex; flex-direction:column; width:14px; border-left:1px solid var(--ud-border); flex-shrink:0; }
.cir-spin button { flex:1; background:#262626; border:none; padding:0; cursor:pointer; color:var(--ud-text-dim); position:relative; }
.cir-spin button:hover { background:#333; color:var(--ud-accent); }
.cir-spin .up { border-bottom:1px solid var(--ud-border); }
.cir-spin .up::before, .cir-spin .dn::before { content:""; position:absolute; left:50%; top:50%; width:5px; height:5px; border-top:1px solid currentColor; border-right:1px solid currentColor; }
.cir-spin .up::before { transform:translate(-50%,-20%) rotate(-45deg); }
.cir-spin .dn::before { transform:translate(-50%,-80%) rotate(135deg); }
.cir-pad-row { display:flex; gap:4px; align-items:stretch; }
.cir-pad-inp { flex:1; }
.cir-unit { display:flex; gap:3px; flex-shrink:0; }
.cir-unit .cir-chip { flex:none; width:34px; }
.cir-toggle { width:100%; box-sizing:border-box; padding:6px 0; border-radius:4px; border:1px solid var(--ud-border); background:var(--ud-inset); color:var(--ud-text-dim); font-size:11px; font-weight:600; cursor:pointer; text-align:center; font-family:inherit; transition:all .12s; }
.cir-toggle:hover { color:var(--ud-text); }
.cir-toggle.on { border-color:var(--ud-accent); color:#fff; background:var(--ud-accent); }
.cir-textinput { width:100%; box-sizing:border-box; background:var(--ud-inset); border:1px solid var(--ud-border); border-radius:4px; padding:5px 8px; color:var(--ud-text); font-size:11px; outline:none; font-family:inherit; }
.cir-textinput:focus { border-color:var(--ud-accent); }
.cir-text-row { display:flex; gap:4px; }
.cir-text-row .cir-textinput { flex:1; min-width:0; }
.cir-save-fields { display:flex; flex-direction:column; gap:8px; }
.cir-adv-head { display:flex; align-items:center; justify-content:space-between; cursor:pointer; user-select:none; }
.cir-adv-head .cir-arrow { font-size:9px; color:var(--ud-text-dim); transition:transform .12s; }
.cir-adv-head.open .cir-arrow { transform:rotate(90deg); }
.cir-adv-body { display:flex; flex-direction:column; gap:8px; margin-top:8px; }
.cir-sub { font-size:9px; color:var(--ud-text-dim); margin-bottom:4px; }
.cir-fields { display:flex; flex-direction:column; gap:8px; }

/* ── Info line ──────────────────────────────────────────── */
.ud-info { font-size: 10px; color: var(--ud-text-dim); line-height: 1.5; }
`;
    document.head.appendChild(s);
}
