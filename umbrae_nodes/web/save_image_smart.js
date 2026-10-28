// save_image_smart.js — SaveImageSmart UI on the umbrae framework.
// Function/Python unchanged: state lives in node.properties.sisState and is
// serialized to the hidden ui_state input via the graphToPrompt hook. All
// ui_state keys are identical to the previous version.
import { app } from "../../scripts/app.js";
import { requestAdvance, findLoader, currentJobPos } from "./umbrae_loop.js";
import { buildScaleSection } from "./umbrae_scale.js";
import { injectTheme, applyNodeColors } from "./umbrae_theme.js";
import {
    createSection, createDivider, createPillRow, createToggle,
    createNumber, createText, createRow, createInfo,
} from "./umbrae_components.js";
import { measureRootContent, attachAutoHeight, applyAdaptiveCanvasOnly } from "./umbrae_resize.js";

const NODE_TYPE = "SaveImageSmart";

// Pre-template workflows: rename_mode / base_name / rename_pattern / auto_index
// -> filename_template / number_files / digits. Mirrors _migrate_naming() in
// the Python so the panel shows what the server will do.
function migrateNaming(node) {
    const s = node.properties?.sisState;
    if (!s || s.filename_template !== undefined) return;
    const mode = s.rename_mode ?? "pattern";
    let tpl;
    if (mode === "source_stem") tpl = "{stem}";
    else if (mode === "base_stem") tpl = s.base_name || "image";
    else tpl = s.rename_pattern || "{stem}";
    const patch = { filename_template: tpl };
    if (s.auto_index !== undefined && s.number_files === undefined) patch.number_files = s.auto_index !== false;
    if (s.auto_index_pad !== undefined && s.digits === undefined) patch.digits = s.auto_index_pad;
    if (/\{(i|z\d+|seq|zseq\d+)\}/.test(tpl)) patch.number_files = false;
    node.properties.sisState = { ...s, ...patch };
}

function setupNode(node) {
    injectTheme();
    applyNodeColors(node);

    function getState() { return node.properties?.sisState ?? {}; }
    function setState(patch) {
        if (!node.properties) node.properties = {};
        node.properties.sisState = { ...getState(), ...patch };
    }
    // Workflows saved before the single-template naming: derive it once.
    migrateNaming(node);
    const st = getState();

    const root = document.createElement("div");
    root.className = "ud-root";

    let auto = null;
    const relayout = () => auto && auto.scheduleRelayout();

    function bboxConnected() {
        const i = node.findInputSlot ? node.findInputSlot("bbox_override") : -1;
        return i >= 0 && node.inputs?.[i]?.link != null;
    }

    // ── Shared scale / anchor / advanced section ─────────────
    const scale = buildScaleSection(
        node,
        () => getState(),
        (_n, patch) => setState(patch),
        { showUniform: false, isBboxConnected: bboxConnected, onChange: relayout },
    );

    // ── Save-specific fields ─────────────────────────────────
    const saveSec = createSection("Save");

    const folder = createText(st.output_folder ?? "", "Output folder (blank = default output dir)",
        (v) => setState({ output_folder: v }), {
            tooltip: "Where files are written. Blank uses ComfyUI's output directory; relative paths " +
                     "are rooted there. Metadata wildcards work per path segment, and / creates " +
                     "subfolders — e.g. images/{model}/{date:YYYY-MM}.",
        });

    const fmtSec = createSection("Format");
    const fmt = createPillRow(
        [{ val: "png", label: "png" }, { val: "jpg", label: "jpg" }, { val: "webp", label: "webp" }],
        st.format ?? "png", (v) => { setState({ format: v }); renderSave(); },
        { tooltip: "Output image format." });
    fmtSec.body.appendChild(fmt.el);

    const qualityNum = createNumber(st.quality ?? 95, 1, 100, 1, (v) => setState({ quality: v }),
        { tooltip: "JPEG/WebP quality (1–100). Ignored for PNG." });
    const qualityRow = createRow("Quality", qualityNum, { grow: true });

    const optimize = createToggle(st.optimize !== false, "Optimize: On", "Optimize: Off",
        (v) => setState({ optimize: v }), { tooltip: "Slower save, smaller file." });
    const lossless = createToggle(st.lossless_webp === true, "Lossless WebP: On", "Lossless WebP: Off",
        (v) => setState({ lossless_webp: v }), { tooltip: "WebP only: store without quality loss." });
    const preserveMeta = createToggle(st.preserve_metadata === true,
        "Preserve Source Metadata: On", "Preserve Source Metadata: Off",
        (v) => setState({ preserve_metadata: v }), {
            tooltip: "Off: embed this run's workflow into saved files (drag-and-drop restores it). " +
                     "On: copy the source image's embedded prompt/workflow verbatim instead — for " +
                     "format conversion that keeps the original generation history.",
        });

    const nameSec = createSection("Filename", {
        tooltip: "One template + numbering + overwrite. Same scheme as Save Training Pair.",
    });
    const tmpl = createText(st.filename_template ?? "{stem}", "{stem}",
        (v) => setState({ filename_template: v }), {
            tooltip: "Name template. {stem} = source filename without extension (blank when nothing " +
                     "is wired). {n} places the number ({n4} = 4 digits); without it the number is " +
                     "appended as _{n}. Metadata tokens: {model} {diffusion_model} {checkpoint} {seed} " +
                     "{steps} {cfg} {sampler} {scheduler} {denoise} {vae} {clip} {lora} {upscale_model} " +
                     "{controlnet} {loaded_image} {width} {height} {size}; {model2} {lora2} … for " +
                     "further instances. Date/time: {date} = YYYY-MM-DD, {date:YY-MM-DD}, {time} = " +
                     "HH-MM-SS, {time:12:HH-MM-SS}. Missing metadata becomes unknown-<name>-. An " +
                     "empty result saves as the number alone.",
        });
    nameSec.body.appendChild(tmpl.el);

    const numToggle = createToggle(st.number_files !== false, "Number Files: On", "Number Files: Off",
        (v) => { setState({ number_files: v }); renderSave(); }, {
            tooltip: "Every saved file gets a number that counts up through a batch-loader job " +
                     "(or one queue press without a loader).",
        });
    const startNum = createNumber(st.start_index ?? 0, 0, 999999999, 1, (v) => setState({ start_index: v }),
        { tooltip: "First number of a job." });
    const startRow = createRow("Start at", startNum, { grow: true });
    const digitsNum = createNumber(st.digits ?? 4, 1, 8, 1, (v) => setState({ digits: v }),
        { tooltip: "Zero padding (4 -> 0007)." });
    const digitsRow = createRow("Digits", digitsNum, { grow: true });
    const overwrite = createToggle(st.overwrite === true, "Overwrite: On", "Overwrite: Off",
        (v) => setState({ overwrite: v }), {
            tooltip: "On: the next job restarts at Start and replaces the previous job's files; a " +
                     "same-named file is replaced. Off: numbering continues after the highest number " +
                     "already in the folder and nothing on disk is ever replaced.",
        });

    const autoAdv = createToggle(st.auto_advance !== false, "Auto Advance: On", "Auto Advance: Off",
        (v) => setState({ auto_advance: v }), {
            tooltip: "When a LoadImagesUniformBatch loader is feeding this node in single-image " +
                     "mode, advance its image_index after each save and re-queue until the folder " +
                     "is exhausted — full-folder conversion from one queue press. Inactive when a " +
                     "SaveTrainingPair node is present (it owns iteration).",
        });

    saveSec.body.append(
        folder.el, fmtSec.el, qualityRow, optimize.el, lossless.el, preserveMeta.el,
        nameSec.el, numToggle.el, startRow, digitsRow, overwrite.el, autoAdv.el,
    );

    function renderSave() {
        const cur = getState();
        const f = cur.format ?? "png";
        qualityRow.style.display = (f === "jpg" || f === "webp") ? "" : "none";
        lossless.el.style.display = f === "webp" ? "" : "none";
        const numbered = cur.number_files !== false;
        startRow.style.display = numbered ? "" : "none";
        digitsRow.style.display = numbered ? "" : "none";
        relayout();
    }

    const info = createInfo("");
    // Status line fed from the ui block save() returns (via onExecuted).
    node._sisStatus = function (message) {
        const files = message?.saved_files ?? [];
        const n = message?.saved_count?.[0] ?? files.length;
        if (!n) { info.setText("Saved: nothing"); relayout(); return; }
        const shown = files.slice(0, 3).join(", ") + (files.length > 3 ? ", …" : "");
        const loaderTotal = app._unpBatchFileCount ?? 0;
        const prog = loaderTotal > 0 ? `  [${(app._unpCurrentIndex ?? 0) + 1}/${loaderTotal}]` : "";
        info.setText(`Saved ${n}: ${shown}${prog}`);
        relayout();
    };

    root.append(scale.root, createDivider(), saveSec.el, createDivider(), info.el);
    renderSave();

    // ── Mount (verified contract) ────────────────────────────
    const widget = node.addDOMWidget("sis_ui", "custom", root, {
        getValue: () => null, setValue: () => {}, serialize: false,
        getMinHeight: () => measureRootContent(root),
        getMaxHeight: () => measureRootContent(root),
        margin: 4,
    });
    applyAdaptiveCanvasOnly(widget);
    if (widget?.element) { widget.element.style.width = "100%"; widget.element.style.boxSizing = "border-box"; }

    const W = Math.max(node.size?.[0] ?? 0, 360);
    if (typeof node.setSize === "function") node.setSize([W, node.size?.[1] ?? 120]);
    else if (node.size) node.size[0] = W;

    auto = attachAutoHeight(node, root, widget);

    // Re-grey the anchor controls when bbox_override is wired/unwired.
    const _occ = node.onConnectionsChange;
    node.onConnectionsChange = function () { const r = _occ?.apply(this, arguments); scale.refresh(); relayout(); return r; };

    // Push restored properties back into the panel. Controls capture their
    // initial value at build time, but LiteGraph restores node.properties in
    // configure() AFTER onNodeCreated — on workflow load, reload, and the
    // frontend's undo/graph-checkpoint restores around runs — leaving the
    // display at defaults while the real (serialized) state stays correct.
    // Same onConfigure→syncUI pattern as every other DOM-panel node in the pack.
    function syncUI() {
        migrateNaming(node);
        const s = getState();
        folder.setValue(s.output_folder ?? "");
        fmt.setActive(s.format ?? "png");
        qualityNum.setValue(s.quality ?? 95);
        optimize.setValue(s.optimize !== false);
        lossless.setValue(s.lossless_webp === true);
        preserveMeta.setValue(s.preserve_metadata === true);
        tmpl.setValue(s.filename_template ?? "{stem}");
        numToggle.setValue(s.number_files !== false);
        startNum.setValue(s.start_index ?? 0);
        digitsNum.setValue(s.digits ?? 4);
        overwrite.setValue(s.overwrite === true);
        autoAdv.setValue(s.auto_advance !== false);
        scale.refresh();
        renderSave();
    }
    const _ocfg = node.onConfigure;
    node.onConfigure = function () { const r = _ocfg?.apply(this, arguments); syncUI(); return r; };

    const _onRemoved = node.onRemoved;
    node.onRemoved = function () { auto.dispose(); return _onRemoved?.apply(this, arguments); };
}

app.registerExtension({
    name: "umbrae.SaveImageSmart",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_TYPE) return;
        const _onc = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () { _onc?.apply(this, arguments); setupNode(this); };

        // Status line + folder iteration. The step itself lives in
        // umbrae_loop.js (once per finished run, shared with the other
        // iteration nodes); this only decides whether to ask for it:
        //  - toggle on (default), a LoadImagesUniformBatch present, and that
        //    loader in single-image mode (uniform_batch off or resize OFF) —
        //    batch mode already delivered every image.
        const _oe = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            _oe?.apply(this, arguments);
            this._sisStatus?.(message);

            if (this.properties?.sisState?.auto_advance === false) return;
            const loader = findLoader();
            if (!loader) return;
            const ls = loader.properties?.lbuState ?? {};
            const single = !(ls.uniform_batch === true) || (ls.resize_mode ?? "LARGEST_EDGE") === "OFF";
            if (!single) return;
            requestAdvance();
        };
    },
});

// Serialize node.properties.sisState into the hidden ui_state input (unchanged).
const _orig = app.graphToPrompt.bind(app);
app.graphToPrompt = async function (...args) {
    const result = await _orig(...args);
    const out = result?.output;
    if (!out) return result;
    for (const id in out) {
        const entry = out[id];
        if (!entry || entry.class_type !== NODE_TYPE) continue;
        const node = app.graph?._nodes?.find((n) => String(n.id) === String(id));
        if (!node) continue;
        entry.inputs = entry.inputs || {};
        entry.inputs.ui_state = JSON.stringify({ ...(node.properties?.sisState ?? {}), job_pos: currentJobPos() });
    }
    return result;
};
