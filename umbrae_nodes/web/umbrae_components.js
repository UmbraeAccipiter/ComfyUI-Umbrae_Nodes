// umbrae_components.js
// Factory functions that stamp out the themed classes. Every interactive
// control accepts an optional `tooltip` that maps to the native title.
// Each returns { el, ... } so callers can read/update without re-querying.

function setTip(el, tip) { if (tip) el.title = tip; }

// ── Section (optionally collapsible) ─────────────────────────
export function createSection(title, opts = {}) {
    const el = document.createElement("div");
    el.className = "ud-section" + (opts.collapsed ? " collapsed" : "");

    const titleEl = document.createElement("div");
    titleEl.className = "ud-title" + (opts.collapsible ? " clickable" : "");
    if (opts.collapsible) {
        const arrow = document.createElement("span");
        arrow.className = "ud-title-arrow";
        arrow.textContent = "\u25BC";
        titleEl.appendChild(arrow);
    }
    titleEl.appendChild(document.createTextNode(title));
    setTip(titleEl, opts.tooltip);

    const body = document.createElement("div");
    body.className = "ud-section-body";

    el.append(titleEl, body);

    if (opts.collapsible) {
        titleEl.addEventListener("click", () => {
            el.classList.toggle("collapsed");
            opts.onToggle && opts.onToggle(!el.classList.contains("collapsed"));
        });
    }
    return {
        el, body,
        setCollapsed(b) { el.classList.toggle("collapsed", b); },
    };
}

// ── Divider ──────────────────────────────────────────────────
export function createDivider() {
    const d = document.createElement("div");
    d.className = "ud-divider";
    return d;
}

// ── Label ────────────────────────────────────────────────────
export function createLabel(text) {
    const l = document.createElement("div");
    l.className = "ud-label";
    l.textContent = text;
    return l;
}

// ── Pill row (single-select) ─────────────────────────────────
export function createPillRow(options, active, onChange, opts = {}) {
    const row = document.createElement("div");
    row.className = "ud-pillrow";
    setTip(row, opts.tooltip);
    const pills = [];
    options.forEach(({ val, label }) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "ud-pill" + (val === active ? " active" : "");
        b.textContent = label;
        b.addEventListener("click", () => {
            pills.forEach((p) => p.el.classList.toggle("active", p.val === val));
            onChange && onChange(val);
        });
        row.appendChild(b);
        pills.push({ el: b, val });
    });
    return {
        el: row,
        setActive(v) { pills.forEach((p) => p.el.classList.toggle("active", p.val === v)); },
    };
}

// ── Toggle ───────────────────────────────────────────────────
export function createToggle(value, onLabel, offLabel, onChange, opts = {}) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "ud-toggle" + (value ? " on" : "");
    b.textContent = value ? onLabel : offLabel;
    setTip(b, opts.tooltip);
    b.addEventListener("click", () => {
        value = !value;
        b.classList.toggle("on", value);
        b.textContent = value ? onLabel : offLabel;
        onChange && onChange(value);
    });
    return {
        el: b,
        setValue(v) { value = v; b.classList.toggle("on", v); b.textContent = v ? onLabel : offLabel; },
    };
}

// ── Number input (with spinners) ─────────────────────────────
export function createNumber(value, min, max, step, onChange, opts = {}) {
    const wrap = document.createElement("div");
    wrap.className = "ud-num";
    setTip(wrap, opts.tooltip);

    const inp = document.createElement("input");
    inp.type = "text"; inp.inputMode = "decimal"; inp.spellcheck = false;
    inp.value = String(value);

    const spin = document.createElement("div");
    spin.className = "ud-num-spin";
    const up = document.createElement("button"); up.type = "button"; up.className = "up"; up.textContent = "\u25B2"; up.tabIndex = -1;
    const dn = document.createElement("button"); dn.type = "button"; dn.className = "dn"; dn.textContent = "\u25BC"; dn.tabIndex = -1;
    spin.append(up, dn);
    wrap.append(inp, spin);

    let cur = value;
    const clamp = (v) => Math.max(min, Math.min(max, v));
    const roundS = (v) => (step >= 1 ? Math.round(v) : parseFloat(v.toFixed(4)));
    function commit() {
        const v = parseFloat(inp.value);
        cur = clamp(roundS(isFinite(v) ? v : cur));
        inp.value = String(cur);
        onChange && onChange(cur);
    }
    function bump(dir) {
        cur = clamp(roundS(cur + dir * step));
        inp.value = String(cur);
        onChange && onChange(cur);
    }
    inp.addEventListener("blur", commit);
    inp.addEventListener("keydown", (e) => {
        e.stopImmediatePropagation();
        if (e.key === "Enter") { e.preventDefault(); inp.blur(); }
        if (e.key === "ArrowUp") { e.preventDefault(); bump(1); }
        if (e.key === "ArrowDown") { e.preventDefault(); bump(-1); }
    });
    up.addEventListener("mousedown", (e) => { e.preventDefault(); bump(1); });
    dn.addEventListener("mousedown", (e) => { e.preventDefault(); bump(-1); });

    return { el: wrap, setValue(v) { cur = v; inp.value = String(v); } };
}

// ── Text input ───────────────────────────────────────────────
export function createText(value, placeholder, onCommit, opts = {}) {
    const inp = document.createElement("input");
    inp.type = "text"; inp.className = "ud-text";
    inp.value = value ?? "";
    if (placeholder) inp.placeholder = placeholder;
    setTip(inp, opts.tooltip);
    inp.addEventListener("blur", () => onCommit && onCommit(inp.value));
    inp.addEventListener("keydown", (e) => {
        e.stopImmediatePropagation();
        if (e.key === "Enter") { e.preventDefault(); inp.blur(); }
    });
    return { el: inp, setValue(v) { inp.value = v ?? ""; } };
}

// ── Labeled row (label + control, optional grow) ─────────────
export function createRow(label, control, opts = {}) {
    const row = document.createElement("div");
    row.className = "ud-row";
    const lbl = createLabel(label);
    if (opts.labelWidth) lbl.style.width = opts.labelWidth;
    row.appendChild(lbl);
    const c = control.el || control;
    if (opts.grow !== false) c.classList.add("ud-grow");
    row.appendChild(c);
    setTip(row, opts.tooltip);
    return row;
}

// ── Info line ────────────────────────────────────────────────
export function createInfo(text = "") {
    const el = document.createElement("div");
    el.className = "ud-info";
    el.textContent = text;
    return { el, setText(t) { el.textContent = t; } };
}
