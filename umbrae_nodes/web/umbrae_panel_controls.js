// umbrae_panel_controls.js
// Control factories for the crop-style panels (cir-* classes, styled in umbrae_theme.js).
// Shared by Crop Image Region, Crop Image, Training Prep and Latent Auto Encode.

export function makeNum(value, min, max, step, onCommit) {
    const wrap = document.createElement("div"); wrap.className = "cir-numinput";
    const inp = document.createElement("input");
    inp.type = "text"; inp.inputMode = "decimal"; inp.spellcheck = false; inp.value = String(value);
    const spin = document.createElement("div"); spin.className = "cir-spin";
    const up = document.createElement("button"); up.className = "up"; up.type = "button"; up.tabIndex = -1;
    const dn = document.createElement("button"); dn.className = "dn"; dn.type = "button"; dn.tabIndex = -1;
    spin.append(up, dn); wrap.append(inp, spin);
    let cur = value;
    const clamp = v => Math.max(min, Math.min(max, v));
    const roundS = v => step >= 1 ? Math.round(v) : parseFloat(v.toFixed(2));
    function commit() { const v = parseFloat(inp.value); cur = clamp(roundS(isFinite(v) ? v : cur)); inp.value = String(cur); onCommit(cur); }
    function step1(d) { cur = clamp(roundS(cur + d * step)); inp.value = String(cur); onCommit(cur); }
    inp.addEventListener("blur", commit);
    inp.addEventListener("keydown", e => { e.stopImmediatePropagation();
        if (e.key === "Enter") { e.preventDefault(); inp.blur(); }
        if (e.key === "ArrowUp") { e.preventDefault(); step1(1); }
        if (e.key === "ArrowDown") { e.preventDefault(); step1(-1); } });
    up.addEventListener("mousedown", e => { e.preventDefault(); step1(1); });
    dn.addEventListener("mousedown", e => { e.preventDefault(); step1(-1); });
    return { wrap, inp, setValue(v) { cur = v; inp.value = String(v); } };
}

export function makeChips(items, active, onChange) {
    const row = document.createElement("div"); row.className = "cir-chips";
    const btns = [];
    for (const { val, label } of items) {
        const b = document.createElement("button"); b.type = "button";
        b.className = "cir-chip" + (val === active ? " active" : "");
        b.textContent = label;
        b.onclick = () => { btns.forEach(x => x.classList.remove("active")); b.classList.add("active"); onChange(val); };
        row.appendChild(b); btns.push(b);
    }
    return { el: row, setActive(v) {
        btns.forEach(b => b.classList.toggle("active", b.textContent === items.find(i => i.val === v)?.label));
    }};
}

export function makeToggle(value, onLabel, offLabel, onChange) {
    const b = document.createElement("button"); b.type = "button";
    b.className = "cir-toggle" + (value ? " on" : "");
    b.textContent = value ? onLabel : offLabel;
    b.onclick = () => { value = !value; b.classList.toggle("on", value); b.textContent = value ? onLabel : offLabel; onChange(value); };
    return { el: b, setValue(v) { value = v; b.classList.toggle("on", v); b.textContent = v ? onLabel : offLabel; } };
}

export function makeText(value, placeholder, onCommit) {
    const inp = document.createElement("input"); inp.type = "text"; inp.className = "cir-textinput";
    inp.value = value ?? ""; if (placeholder) inp.placeholder = placeholder;
    inp.addEventListener("blur", () => onCommit(inp.value));
    inp.addEventListener("keydown", e => { e.stopImmediatePropagation(); if (e.key === "Enter") { e.preventDefault(); inp.blur(); } });
    return { el: inp, setValue(v) { inp.value = v ?? ""; } };
}

export function subLabel(t) { const d = document.createElement("div"); d.className = "cir-sub"; d.textContent = t; return d; }
