import { app } from "/scripts/app.js";
import { api } from "/scripts/api.js";
import { ComfyWidgets } from "/scripts/widgets.js";

app.registerExtension({
    name: "Umbrae.LoadAudioFromVideo",
    async beforeRegisterNodeDef(nodeType, nodeData, app) {
        if (nodeData.name !== "LoadAudioFromVideo") return;

        const orig_onNodeCreated = nodeType.prototype.onNodeCreated;

        nodeType.prototype.onNodeCreated = function() {
            if (orig_onNodeCreated) orig_onNodeCreated.apply(this, arguments);

            // Find the video_file widget
            const videoWidget = this.widgets.find(w => w.name === "video_file");
            if (!videoWidget) return;

            // Add Load button
            this.addWidget("button", "Load", "Load", () => {
                api.selectFile(["mp4", "mkv", "avi", "wmv", "mov"]).then(file => {
                    if (file) {
                        videoWidget.value = file.name;
                        this.setDirtyCanvas(true);
                    }
                });
            });

            // Add refresh button to update dropdown
            this.addWidget("button", "Refresh List", "Refresh", async () => {
                const res = await api.getInputFiles();
                if (res && res.input && Array.isArray(res.input)) {
                    const files = res.input.filter(f =>
                        f.match(/\.(mp4|mkv|avi|wmv|mov)$/i)
                    );
                    videoWidget.options.choices = files;
                    if (!files.includes(videoWidget.value) && files.length > 0)
                        videoWidget.value = files[0];
                    this.setDirtyCanvas(true);
                }
            });
        };
    },
});
