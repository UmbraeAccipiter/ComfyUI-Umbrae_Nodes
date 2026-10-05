// save_image_smart.js — SaveImageSmart UI on the umbrae framework.
// Function/Python unchanged: state lives in node.properties.sisState and is
// serialized to the hidden ui_state input via the graphToPrompt hook. All
// ui_state keys are identical to the previous version.
import { app } from "../../scripts/app.js";
import { buildScaleSection } from "./umbrae_scale.js";
import { injectTheme } from "./umbrae_theme.js";
import {
    createSection, createDivider, createPillRow, createToggle,
    createNumber, createText, createRow, createInfo,
} from "./umbrae_components.js";
import { measureRootContent, attachAutoHeight, applyAdaptiveCanvasOnly } from "./umbrae_resize.js";

const NODE_TYPE = "SaveImageSmart";

function setupNode(node) {
    injectTheme();
    if (!node.bgcolor) node.bgcolor = "#2a2a2a";
    if (!node.color) node.color = "#1f1f1f";

    function getState() { return node.properties?.sisState ?? {}; }
    function setState(patch) {
        if (!node.properties) node.properties = {};
        node.properties.sisState = { ...getState(), ...patch };
    }
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

    const renameSec = createSection("Rename Mode", { tooltip: "How output filenames are built." });
    const rename = createPillRow(
        [{ val: "source_stem", label: "Source Stem" }, { val: "base_stem", label: "Base Stem" }, { val: "pattern", label: "Pattern" }],
        st.rename_mode ?? "pattern", (v) => { setState({ rename_mode: v }); renderSave(); },
        { tooltip: "Source Stem reuses the input filename; Base Stem uses Base Name; Pattern uses the template below." });
    renameSec.body.appendChild(rename.el);

    const baseName = createText(st.base_name ?? "image", "Base name",
        (v) => setState({ base_name: v }), { tooltip: "Base filename used by Base Stem / {base}." });
    const pattern = createText(st.rename_pattern ?? "myset",
        "Pattern — {i} {z3} {stem} {base} {model} {date} …", (v) => setState({ rename_pattern: v }),
        {
            tooltip: "Filename template. Index tokens: {i} {z3} {seq} {zseq3} {stem} {base}. " +
                     "Metadata tokens: {model} {diffusion_model} {checkpoint} {seed} {steps} {cfg} " +
                     "{sampler} {scheduler} {denoise} {vae} {clip} {lora} {upscale_model} " +
                     "{controlnet} {loaded_image} {width} {height} {size}. Multi-instance workflows: " +
                     "append a number — {model2} = refiner's model (samplers in execution order), " +
                     "{lora2}, {clip2}, etc. (loaders in graph order); bare = first. Date/time: " +
                     "{date} = YYYY-MM-DD, {date:YY-MM-DD}, {time} = 24h HH-MM-SS, {time:12:HH-MM-SS} " +
                     "appends -AM/-PM. Missing metadata becomes unknown-<name>-. Metadata comes from " +
                     "the wired metadata input, the source file, or the live workflow, in that priority.",
        });

    const seqNum = createNumber(st.sequence_index ?? 0, 0, 999999, 1, (v) => setState({ sequence_index: v }),
        { tooltip: "Value substituted for {seq}/{zseq}." });
    const seqRow = createRow("Sequence", seqNum, { grow: true });

    const autoIdx = createToggle(st.auto_index !== false, "Auto Index: On", "Auto Index: Off",
        (v) => { setState({ auto_index: v }); renderSave(); }, { tooltip: "Append an incrementing number so files never overwrite." });
    const padNum = createNumber(st.auto_index_pad ?? 3, 1, 8, 1, (v) => setState({ auto_index_pad: v }),
        { tooltip: "Zero-pad width of the auto index (e.g. 3 → 007)." });
    const padRow = createRow("Index Padding", padNum, { grow: true });

    const autoAdv = createToggle(st.auto_advance !== false, "Auto Advance: On", "Auto Advance: Off",
        (v) => setState({ auto_advance: v }), {
            tooltip: "When a LoadImagesUniformBatch loader is feeding this node in single-image " +
                     "mode, advance its image_index after each save and re-queue until the folder " +
                     "is exhausted — full-folder conversion from one queue press. Inactive when a " +
                     "SaveTrainingPair node is present (it owns iteration).",
        });

    saveSec.body.append(
        folder.el, fmtSec.el, qualityRow, optimize.el, lossless.el, preserveMeta.el,
        renameSec.el, baseName.el, pattern.el, seqRow, autoIdx.el, padRow, autoAdv.el,
    );

    function renderSave() {
        const cur = getState();
        const f = cur.format ?? "png";
        qualityRow.style.display = (f === "jpg" || f === "webp") ? "" : "none";
        lossless.el.style.display = f === "webp" ? "" : "none";
        const mode = cur.rename_mode ?? "pattern";
        pattern.el.style.display = mode === "pattern" ? "" : "none";
        baseName.el.style.display = (mode === "base_stem" || mode === "pattern") ? "" : "none";
        padRow.style.display = (cur.auto_index !== false) ? "" : "none";
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
        const s = getState();
        folder.setValue(s.output_folder ?? "");
        fmt.setActive(s.format ?? "png");
        qualityNum.setValue(s.quality ?? 95);
        optimize.setValue(s.optimize !== false);
        lossless.setValue(s.lossless_webp === true);
        preserveMeta.setValue(s.preserve_metadata === true);
        rename.setActive(s.rename_mode ?? "pattern");
        baseName.setValue(s.base_name ?? "image");
        pattern.setValue(s.rename_pattern ?? "myset");
        seqNum.setValue(s.sequence_index ?? 0);
        autoIdx.setValue(s.auto_index !== false);
        padNum.setValue(s.auto_index_pad ?? 3);
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

        // Status line + folder iteration. Mirrors SaveTrainingPair's advance
        // mechanism, with guards so it only runs for conversion wiring:
        //  - toggle on (default), no SaveTrainingPair in the graph (it owns
        //    iteration), a LoadImagesUniformBatch present with a known file
        //    count, and that loader in single-image mode (uniform_batch off
        //    or resize OFF) — batch mode already delivered every image.
        const _oe = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function (message) {
            _oe?.apply(this, arguments);
            this._sisStatus?.(message);

            if (this.properties?.sisState?.auto_advance === false) return;
            if (app.graph?._nodes?.some((n) => n.type === "SaveTrainingPair" || n.comfyClass === "SaveTrainingPair")) return;

            const count = app._unpBatchFileCount ?? 0;
            if (count <= 1) return;

            const loader = app.graph?._nodes?.find((n) =>
                n.type === "LoadImagesUniformBatch" ||
                n.comfyClass === "LoadImagesUniformBatch" ||
                n.properties?.lbuState !== undefined
            );
            if (!loader) return;
            const ls = loader.properties?.lbuState ?? {};
            const single = !(ls.uniform_batch === true) || (ls.resize_mode ?? "LARGEST_EDGE") === "OFF";
            if (!single) return;

            const idxWidget = loader.widgets?.find((w) => w.name === "image_index");
            if (!idxWidget) return;

            const widgetVal = parseInt(idxWidget.value) || 0;
            if (app._unpCurrentIndex === undefined || widgetVal !== app._unpCurrentIndex)
                app._unpCurrentIndex = widgetVal;
            const current = app._unpCurrentIndex;

            if (current >= count - 1) {
                app._unpCurrentIndex = 0;
                idxWidget.value = 0;
                app._unpNextImageIndex = 0;
                app._unpBatchFileCount = 0;
                return;
            }

            app._unpCurrentIndex = current + 1;
            app._unpNextImageIndex = current + 1;
            idxWidget.value = current + 1;
            setTimeout(() => app.queuePrompt(0, 1), 300);
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
        entry.inputs.ui_state = JSON.stringify(node.properties?.sisState ?? {});
    }
    return result;
};
