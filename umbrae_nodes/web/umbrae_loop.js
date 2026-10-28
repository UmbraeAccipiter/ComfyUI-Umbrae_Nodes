// umbrae_loop.js — the ONE owner of the batch-loader iteration loop.
//
// Before this file, every node that could drive the loop (save training pair,
// training prep, crop image region, save image smart) advanced the loader's
// image_index and queued the next prompt from its own onExecuted hook. Two of
// them in one graph meant two prompts queued per run, each of which queued two
// more — the queue grew on its own and images repeated out of order.
//
// Now a node only *asks* for an advance (requestAdvance()). The step itself
// happens once, after ComfyUI reports the whole prompt finished, however many
// nodes asked. A node that is muted / bypassed never executes, so it never
// asks; a node whose "Counts Toward Completion" / "Auto Advance" toggle is off
// doesn't ask either. If nobody asks, the loop does not advance.

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const LOADER_TYPE = "LoadImagesUniformBatch";
const QUEUE_DELAY_MS = 300;

let _armed = false;   // an iteration node executed in the current run

export function findLoader() {
    return (app.graph?._nodes ?? []).find(n =>
        n.type === LOADER_TYPE || n.comfyClass === LOADER_TYPE ||
        n.properties?.lbuState !== undefined);
}

/** Called from a node's onExecuted. Cheap and idempotent. */
export function requestAdvance() {
    _armed = true;
}

/** Position of the prompt being built inside a loader job: 0 = first image,
 *  k = k-th image, -1 = no batch loader in the graph (every queue press is its
 *  own job). Save nodes put this into their ui_state so numbering can restart
 *  or continue per job. Safe to call from any graphToPrompt hook, whichever
 *  order the hooks run in. */
export function currentJobPos() {
    const loader = findLoader();
    if (!loader) return -1;
    if (app._unpNextImageIndex !== undefined) return app._unpNextImageIndex;
    const w = loader.widgets?.find(w => w.name === "image_index");
    return w ? (parseInt(w.value) || 0) : -1;
}

function advance() {
    if (!_armed) return;
    _armed = false;

    const count = app._unpBatchFileCount ?? 0;
    if (count <= 0) return;
    const loader = findLoader();
    if (!loader) return;
    const idxWidget = loader.widgets?.find(w => w.name === "image_index");
    if (!idxWidget) return;

    // App-level counter, re-synced from the widget if the user edited it.
    const widgetVal = parseInt(idxWidget.value) || 0;
    if (app._unpCurrentIndex === undefined || widgetVal !== app._unpCurrentIndex)
        app._unpCurrentIndex = widgetVal;
    const current = app._unpCurrentIndex;

    if (current >= count - 1) {
        // Last image done: rewind and stop.
        app._unpCurrentIndex = 0;
        idxWidget.value = 0;
        app._unpNextImageIndex = 0;
        app._unpBatchFileCount = 0;
        return;
    }
    app._unpCurrentIndex = current + 1;
    app._unpNextImageIndex = current + 1;   // consumed by the loader's graphToPrompt hook
    idxWidget.value = current + 1;
    setTimeout(() => app.queuePrompt(0, 1), QUEUE_DELAY_MS);
}

// A new run starts: forget any stale request.
api.addEventListener("execution_start", () => { _armed = false; });
// The run finished cleanly: step once.
api.addEventListener("execution_success", advance);
// Older frontends signal completion as executing(node = null).
api.addEventListener("executing", e => {
    const d = e?.detail;
    if (d === null || (d && typeof d === "object" && d.node === null)) advance();
});
// Errors / interrupts: do not keep looping.
api.addEventListener("execution_error", () => { _armed = false; });
api.addEventListener("execution_interrupted", () => { _armed = false; });
