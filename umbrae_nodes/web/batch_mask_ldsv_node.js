/**
 * batch_mask_ldsv_node.js
 * Adds two action buttons to the Load Mask Batch node.
 */

import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "umbrae.MaskBatchButtons",

    async beforeRegisterNodeDef(nodeType, nodeData, appInstance) {
        if (nodeData.name !== "LoadMaskBatch") return;

        const origOnNodeCreated = nodeType.prototype.onNodeCreated;

        nodeType.prototype.onNodeCreated = function () {
            if (origOnNodeCreated) {
                origOnNodeCreated.apply(this, arguments);
            }

            const node = this;

            // Helper: find the load_folder widget
            const getFolderWidget = () =>
                node.widgets?.find(w => w.name === "load_folder");

            // -----------------------------------------------------------
            // Button 1 — Load Last Folder
            // -----------------------------------------------------------
            const btnLoad = node.addWidget(
                "button",
                "📂 Load Last Folder",
                "load_last_folder",
                async () => {
                    try {
                        const resp = await fetch("/umbrae/mask_batch/last_folder");
                        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                        const data = await resp.json();
                        const folder = data.last_folder || "";

                        if (!folder) {
                            alert("No folder recorded yet. Run Save Mask Batch first.");
                            return;
                        }

                        const widget = getFolderWidget();
                        if (widget) {
                            widget.value = folder;
                            node.setDirtyCanvas(true, true);
                        }
                    } catch (err) {
                        alert(`Load Last Folder failed: ${err.message}`);
                    }
                }
            );
            btnLoad.serialize = false;

            // -----------------------------------------------------------
            // Button 2 — Clear Folder
            // -----------------------------------------------------------
            const btnClear = node.addWidget(
                "button",
                "🗑️ Clear Folder",
                "clear_folder",
                async () => {
                    const widget = getFolderWidget();
                    const folder = widget?.value?.trim() || "";
                    const target = folder || "(entire mask_edit root)";

                    const confirmed = confirm(
                        `Permanently delete:\n\n  ${target}\n\nAre you sure?`
                    );
                    if (!confirmed) return;

                    try {
                        const resp = await fetch("/umbrae/mask_batch/clear_folder", {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({ folder }),
                        });

                        const data = await resp.json();

                        if (!resp.ok) {
                            alert(`Clear failed: ${data.error || resp.status}`);
                            return;
                        }

                        alert(`Cleared: ${data.cleared}`);

                        if (widget && folder && widget.value.trim() === folder) {
                            widget.value = "";
                            node.setDirtyCanvas(true, true);
                        }
                    } catch (err) {
                        alert(`Clear Folder failed: ${err.message}`);
                    }
                }
            );
            btnClear.serialize = false;
        };
    },
});
