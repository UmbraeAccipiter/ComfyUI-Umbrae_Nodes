import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "UNP.SaveTrainingPair",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "SaveTrainingPair") return;
        const _oe = nodeType.prototype.onExecuted;
        nodeType.prototype.onExecuted = function(message) {
            _oe?.apply(this, arguments);

            const count = app._unpBatchFileCount ?? 0;
            if (count <= 0) return;

            const loader = app.graph?._nodes?.find(n =>
                n.type === "LoadImagesUniformBatch" ||
                n.comfyClass === "LoadImagesUniformBatch" ||
                n.properties?.lbuState !== undefined
            );
            if (!loader) return;

            const idxWidget = loader.widgets?.find(w => w.name === "image_index");
            if (!idxWidget) return;

            // Use app-level counter, but sync from widget if user changed it manually
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
