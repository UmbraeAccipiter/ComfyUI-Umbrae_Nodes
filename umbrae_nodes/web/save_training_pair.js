import { app } from "../../scripts/app.js";
import { requestAdvance, currentJobPos } from "./umbrae_loop.js";

// save training pair [umbrae]: every execution asks the shared loop controller
// (umbrae_loop.js) to advance the batch loader. The step happens once per
// finished run, no matter how many iteration nodes the graph has.
app.registerExtension({
    name: "UNP.SaveTrainingPair",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "SaveTrainingPair") return;
        const _oe = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function(message) {
            _oe?.apply(this, arguments);
            requestAdvance();
        };
    },
});

// Hidden ui_state: where this prompt sits in the loader job, so the Python
// side knows when to restart (overwrite on) or continue (off) its numbering.
const _origGTP = app.graphToPrompt.bind(app);
app.graphToPrompt = async function(...args) {
    const result = await _origGTP(...args);
    const out = result?.output;
    if (!out) return result;
    for (const id in out) {
        const entry = out[id];
        if (!entry || entry.class_type !== "SaveTrainingPair") continue;
        entry.inputs = entry.inputs || {};
        entry.inputs.ui_state = JSON.stringify({ job_pos: currentJobPos() });
    }
    return result;
};
