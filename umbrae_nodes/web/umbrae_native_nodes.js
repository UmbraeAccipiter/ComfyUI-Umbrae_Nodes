// umbrae_native_nodes.js
// Gives the nodes that use ComfyUI's built-in widgets the shared umbrae look:
//   - every node here gets the standard title/body colors
//   - the busiest ones also get a themed panel (see umbrae_native_panel.js)

import { app } from "../../scripts/app.js";
import { applyNodeColors } from "./umbrae_theme.js";
import { skinNativeWidgets } from "./umbrae_native_panel.js";

const notPng = (get) => get("format") !== "png";

const PANELS = {
    IntegerStepper: [
        { title: "Mode", rows: [{ name: "mode", label: "Step mode" }] },
        { title: "Value", rows: [[{ name: "base" }, { name: "step" }], { name: "iteration" }] },
        { title: "Range", rows: [[{ name: "min_value", label: "Min" }, { name: "max_value", label: "Max" }],
            { name: "clamp_range", on: "Clamp to range: On", off: "Clamp to range: Off" }] },
        { title: "Random", rows: [{ name: "seed" }, { name: "control_after_generate", label: "After run" }] },
        { title: "Output", rows: [{ name: "zero_pad_width", label: "Zero-pad width" },
            { name: "advance_after_emit", on: "Advance after emit: On", off: "Advance after emit: Off" }] },
    ],
    MaskBatchOverlay: [
        { title: "Overlay", rows: [{ name: "opacity", step: 0.05 }, [{ name: "hue_offset", label: "Hue offset", step: 1 }, { name: "saturation", step: 0.05 }], { name: "brightness", step: 0.05 }] },
        { title: "Output", rows: [{ name: "resize_output", on: "Resize output: On", off: "Resize output: Off" },
            { name: "megapixels", step: 0.1, showIf: (g) => g("resize_output") !== false },
            { name: "resize_method", label: "Resize method", showIf: (g) => g("resize_output") !== false }] },
    ],
    SaveImageWithName: [
        { title: "Save", rows: [{ name: "image_filename", label: "Filename", placeholder: "filename" },
            { name: "output_dir", label: "Output folder", placeholder: "output folder" }] },
        { title: "Format", rows: [{ name: "format" }, { name: "quality", showIf: notPng }] },
        { title: "Options", rows: [{ name: "overwrite", on: "Overwrite: On", off: "Overwrite: Off" },
            { name: "keep_original_extension", on: "Keep original extension: On", off: "Keep original extension: Off" }] },
    ],
    SaveTrainingPair: [
        { title: "Save", rows: [{ name: "output_folder", label: "Output folder" }] },
        { title: "Format", rows: [{ name: "format" }] },
        { title: "Name", rows: [[{ name: "prefix", placeholder: "prefix" }, { name: "suffix", placeholder: "suffix" }],
            { name: "overwrite", on: "Overwrite: On", off: "Overwrite: Off" }] },
    ],
    UmbraeInpaintCropRGBA: [
        { title: "Size", rows: [{ name: "size_mode", label: "Size mode" }, { name: "target", step: 8 }, { name: "multiple", label: "Round to multiple of" }] },
        { title: "Mask", rows: [[{ name: "context_px", label: "Context px" }, { name: "mask_grow", label: "Grow" }],
            [{ name: "mask_blur", label: "Blur" }, { name: "softness" }]] },
        { title: "Stitch", rows: [{ name: "blend_mode", label: "Blend mode" },
            { name: "invert_mask", on: "Invert mask: On", off: "Invert mask: Off" }, { name: "matte" }] },
    ],
};

// plain nodes: standard colors only
const COLORS_ONLY = new Set([
    "ListFolderImages", "ConstantImage", "SelectImageAndName", "PickFilenameByIndex",
    "SaveMaskBatch", "LoadMaskBatch", "CombineMaskBatch", "BreakInserter", "SafeString",
    "UmbraeLoadImageRGBA", "UmbraeInpaintStitchRGBA", "UmbraeWildcardProcessor",
    "ExternalCheckpointLoaderSimple", "ExternalUNETLoader", "ExternalVAELoader", "ExternalCLIPLoader",
    "ExternalCLIPVisionLoader", "ExternalLoraLoader", "ExternalLoraLoaderModelOnly", "ExternalUpscaleModelLoader",
]);

app.registerExtension({
    name: "umbrae.NativeNodes",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const name = nodeData.name;
        const spec = PANELS[name];
        if (!spec && !COLORS_ONLY.has(name)) return;
        const onCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onCreated?.apply(this, arguments);
            applyNodeColors(this);
            if (spec) {
                try { skinNativeWidgets(this, spec); }
                catch (e) { console.error("[umbrae] panel failed for", name, e); }
            }
            return r;
        };
    },
});
