import { app } from "../../scripts/app.js";
import { buildScaleSection } from "./umbrae_scale.js";
import { measureRootContent, attachAutoHeight, applyAdaptiveCanvasOnly } from "./umbrae_resize.js";
import { injectTheme } from "./umbrae_theme.js";
import { makeNum, makeChips, makeToggle, subLabel as sub } from "./umbrae_panel_controls.js";

const NODE_TYPE = "LatentAutoEncode";

function setupNode(node) {
    injectTheme();
    if (!node.bgcolor) node.bgcolor = "#2a2a2a";
    if (!node.color) node.color = "#1f1f1f";

    function getState() { return node.properties?.laeState ?? {}; }
    function syncStateWidget() {
        // A1: mirror state into the hidden ui_state widget so it serializes through
        // subgraph flattening. The graphToPrompt hook below only sees top-level
        // nodes; the widget value rides along with the node regardless of nesting.
        const w = (node.widgets || []).find(x => x.name === "ui_state");
        if (w) w.value = JSON.stringify(node.properties?.laeState ?? {});
    }
    function setState(patch) {
        if (!node.properties) node.properties = {};
        node.properties.laeState = { ...getState(), ...patch };
        syncStateWidget();
    }

    const st = getState();
    const root = document.createElement("div"); root.className = "cir-root";

    // ── Generate (used only when no image/latent is wired) ─────────────────────
    const genLabel = document.createElement("div"); genLabel.className = "cir-label"; genLabel.textContent = "Generate (no image / latent)";
    const genChips = makeChips([{ val: "empty", label: "Empty (t2i)" }, { val: "noise", label: "Random noise" }],
        st.gen_mode ?? "empty", v => { setState({ gen_mode: v }); renderGen(); });
    [...genChips.el.children].forEach((b, i) => {
        b.title = i === 0
            ? "Empty latent (zeros) — the normal t2i case; the sampler adds noise from its own seed."
            : "Seeded random-noise latent — niche; for samplers that take pre-made noise.";
    });
    const seedNum = makeNum(st.seed ?? 0, 0, 1e15, 1, v => setState({ seed: v }));
    const seedWrap = document.createElement("div"); seedWrap.append(sub("Seed (for random noise)"), seedNum.wrap);
    const genSec = document.createElement("div"); genSec.append(genLabel, genChips.el, seedWrap);
    function renderGen() { seedWrap.style.display = (getState().gen_mode ?? "empty") === "noise" ? "" : "none"; scheduleResize(); }

    // ── Size (target W/H; overridden by the width/height inputs) ────────────────
    const sizeLabel = document.createElement("div"); sizeLabel.className = "cir-label"; sizeLabel.textContent = "Size";
    const whRow = document.createElement("div"); whRow.className = "cir-pad-row";
    const wNum = makeNum(st.width ?? 1024, 8, 16384, 8, v => setState({ width: v }));
    const hNum = makeNum(st.height ?? 1024, 8, 16384, 8, v => setState({ height: v }));
    whRow.append(wNum.wrap, hNum.wrap);
    const sizeSec = document.createElement("div"); sizeSec.append(sizeLabel, sub("Width · Height (inputs override these)"), whRow);

    // ── Sigmas (Flux2 schedule, split on denoise) ──────────────────────────────
    const sigLabel = document.createElement("div"); sigLabel.className = "cir-label"; sigLabel.textContent = "Sigmas (Flux2)";
    const stepsNum = makeNum(st.steps ?? 20, 1, 4096, 1, v => setState({ steps: v }));
    const stepsWrap = document.createElement("div"); stepsWrap.append(sub("Steps"), stepsNum.wrap);
    const halfChips = makeChips(
        [{ val: "low", label: "Low" }, { val: "high", label: "High" }],
        st.sigmas_half ?? "low", v => { setState({ sigmas_half: v }); scheduleResize(); });
    [...halfChips.el.children].forEach((b, i) => {
        b.title = i === 0
            ? "On a split: low-noise tail sigmas[k:] (the usual i2i half)."
            : "On a split: high-noise front sigmas[:k+1].";
    });
    const sigSec = document.createElement("div");
    sigSec.append(sigLabel, stepsWrap,
        sub("Split half — only applies when a real source (image or non-empty latent) is at denoise < 1; otherwise the full schedule is output"),
        halfChips.el);

    // ── Resize image before encode (crop_core scale panel) ─────────────────────
    const resizeToggle = makeToggle(st.resize_on === true, "Resize image before encode: On", "Resize image before encode: Off",
        v => { setState({ resize_on: v }); renderResize(); });
    resizeToggle.el.title = "When an image is wired, run it through the resize settings below before VAE-encoding. A wired latent is cropped (never scaled) to the target W/H.";
    const { root: scaleRoot, refresh: refreshScale } = buildScaleSection(
        node, () => getState(), (_n, p) => setState(p),
        { showUniform: false, seedDefaults: true, onChange: () => scheduleResize(), isBboxConnected: () => false });
    const resizeSec = document.createElement("div"); resizeSec.append(resizeToggle.el, scaleRoot);
    function renderResize() { scaleRoot.style.display = (getState().resize_on === true) ? "" : "none"; scheduleResize(); }

    root.append(genSec, sizeSec, sigSec, resizeSec);

    // ── mount ──────────────────────────────────────────────────────────────────
    const measureH = () => measureRootContent(root);
    let auto = null;
    function scheduleResize() { if (auto) auto.scheduleRelayout(); }
    const _w = node.addDOMWidget("lae_ui", "custom", root, {
        getValue: () => null, setValue: () => {}, serialize: false,
        getMinHeight: measureH, getMaxHeight: measureH, margin: 4,
    });
    applyAdaptiveCanvasOnly(_w);
    if (_w?.element) { _w.element.style.width = "100%"; _w.element.style.boxSizing = "border-box"; }
    const _W = Math.max(node.size?.[0] ?? 0, 320);
    if (typeof node.setSize === "function") node.setSize([_W, node.size?.[1] ?? 120]);
    else if (node.size) node.size[0] = _W;
    auto = attachAutoHeight(node, root, _w);
    renderGen(); renderResize();
    syncStateWidget();
    const _onr = node.onRemoved;
    node.onRemoved = function() { auto.dispose(); return _onr?.apply(this, arguments); };

    function syncUI() {
        const s = getState();
        genChips.setActive(s.gen_mode ?? "empty");
        seedNum.setValue(s.seed ?? 0);
        wNum.setValue(s.width ?? 1024); hNum.setValue(s.height ?? 1024);
        stepsNum.setValue(s.steps ?? 20);
        halfChips.setActive(s.sigmas_half ?? "low");
        resizeToggle.setValue(s.resize_on === true);
        refreshScale(); renderGen(); renderResize(); syncStateWidget(); scheduleResize();
    }
    const _ocfg = node.onConfigure;
    node.onConfigure = function() { const r = _ocfg?.apply(this, arguments); syncUI(); return r; };
}

app.registerExtension({
    name: "UNP.LatentAutoEncode",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;
        const _onc = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function() { _onc?.apply(this, arguments); setupNode(this); };
    },
});

// ── graphToPrompt hook ────────────────────────────────────────────────────────
const _orig = app.graphToPrompt.bind(app);
app.graphToPrompt = async function(...args) {
    const result = await _orig(...args);
    const out = result?.output;
    if (!out) return result;
    for (const id in out) {
        const entry = out[id];
        if (!entry || entry.class_type !== NODE_TYPE) continue;
        const node = app.graph?._nodes?.find(n => String(n.id) === String(id));
        if (!node) continue;
        entry.inputs = entry.inputs || {};
        entry.inputs.ui_state = JSON.stringify(node.properties?.laeState ?? {});
    }
    return result;
};
