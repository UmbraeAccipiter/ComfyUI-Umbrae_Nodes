// web/lora_loader/settings.js — umbrae_nodes v0.9.3
// The gear panel: per-node preferences (with "use for new nodes"), and the
// machine-wide account section (Civitai / Hugging Face keys, host, adult
// pictures, download folder) that lives on the server, never in a workflow.
import { h, btn, toast, openOverlay, closeOverlay } from "./ui.js";
import { readState, setPrefs, saveDefaults, DEFAULT_PREFS, roundStrength } from "./state.js";
import { getAccount, setAccount } from "./api.js";

export function closeSettings() { closeOverlay("settings"); }

export function openSettings(node, refresh) {
    const { pop } = openOverlay("settings", { width: 460 });
    const st = readState(node);
    const prefs = {};
    for (const k of Object.keys(DEFAULT_PREFS)) prefs[k] = st[k];
    const apply = () => { setPrefs(node, prefs); refresh?.(true); };

    const numIn = (key, step, min, max) => {
        const i = h("input", { class: "ull-in", type: "number", step: String(step), min: String(min), max: String(max), value: String(prefs[key]), style: { width: "80px" } });
        i.addEventListener("change", () => { let v = parseFloat(i.value); if (!Number.isFinite(v)) v = DEFAULT_PREFS[key]; v = Math.max(min, Math.min(max, v)); prefs[key] = key === "defStrength" ? roundStrength(v) : v; i.value = String(prefs[key]); apply(); });
        return i;
    };
    const toggle = (key) => {
        const t = h("div", { class: "ull-toggle" + (prefs[key] ? " on" : ""), onclick: () => { prefs[key] = !prefs[key]; t.classList.toggle("on", prefs[key]); apply(); } });
        return t;
    };
    const sepIn = h("input", { class: "ull-in", value: prefs.sep, style: { width: "80px" }, placeholder: ", " });
    sepIn.addEventListener("change", () => { prefs.sep = sepIn.value; apply(); });
    const cache = h("select", { class: "ull-sel" });
    for (const [v, l] of [["last", "keep the last file (default)"], ["all", "keep every file in the stack (fast, uses RAM)"], ["none", "keep nothing (lowest memory)"]]) cache.append(h("option", { value: v, text: l }));
    cache.value = prefs.cacheMode;
    cache.addEventListener("change", () => { prefs.cacheMode = cache.value; apply(); });

    const grid = h("div", { class: "ull-grid2" },
        h("span", { text: "default strength" }), numIn("defStrength", 0.05, -10, 10),
        h("span", { text: "arrow step" }), numIn("step", 0.01, 0.01, 1),
        h("span", { text: "one strength for model + clip" }), toggle("linkStrength"),
        h("span", { text: "trigger separator" }), sepIn,
        h("span", { text: "hide file extension" }), toggle("hideExt"),
        h("span", { text: "show pictures" }), toggle("thumbs"),
        h("span", { text: "LoRA memory between runs" }), cache,
    );
    const useDefault = btn("Use these for new nodes", "Remember this node's preferences as the default for new lora loader nodes", () => {
        toast(saveDefaults(prefs) ? "success" : "warn", saveDefaults(prefs) ? "Saved as default" : "Could not save");
    }, "tiny");

    // account
    const accSect = h("div", { class: "ull-sect" }, h("span", { class: "ull-dim", text: "loading…" }));
    (async () => {
        const acc = await getAccount();
        renderAccount(acc);
    })();
    function keyRow(label, field, acc, configured, hint) {
        const inp = h("input", { class: "ull-in wide", type: "password", placeholder: configured ? "key saved (" + hint + ") — paste a new one to replace" : "paste the key", autocomplete: "off" });
        const save = btn("save", "", async () => {
            if (!inp.value.trim()) return;
            const r = await setAccount({ [field]: inp.value.trim() });
            if (!r.ok) { toast("warn", "Not saved", r.message); return; }
            inp.value = ""; toast("success", label + " saved"); renderAccount(r);
        }, "tiny primary");
        const clear = configured ? btn("remove", "", async () => { const r = await setAccount({ [field]: "" }); if (r.ok) renderAccount(r); }, "tiny danger") : null;
        return [h("span", { text: label }), h("div", { class: "ull-bar" }, inp, save, clear)];
    }
    function renderAccount(acc) {
        accSect.replaceChildren();
        if (!acc?.ok) { accSect.append(h("span", { class: "ull-err", text: acc?.message || "could not read the settings" })); return; }
        const host = h("select", { class: "ull-sel" });
        for (const [v, l] of [["com", "civitai.com first"], ["red", "civitai.red first (unrestricted)"]]) host.append(h("option", { value: v, text: l }));
        host.value = acc.host;
        host.addEventListener("change", async () => { const r = await setAccount({ host: host.value }); if (r.ok) renderAccount(r); });
        const adult = h("div", { class: "ull-toggle" + (acc.adult ? " on" : ""), onclick: async () => { const r = await setAccount({ adult: !acc.adult }); if (r.ok) renderAccount(r); } });
        const dir = h("input", { class: "ull-in", value: acc.download_dir || "", placeholder: "e.g. downloaded", style: { width: "160px" } });
        dir.addEventListener("change", async () => { const r = await setAccount({ download_dir: dir.value }); if (r.ok) { dir.value = r.download_dir; } });
        accSect.append(h("div", { class: "ull-grid2" },
            ...keyRow("Civitai API key", "civitai_key", acc, acc.civitai, acc.civitai_hint),
            h("span", { text: "ask first" }), host,
            h("span", { text: "allow adult pictures" }), adult,
            ...keyRow("Hugging Face token", "hf_key", acc, acc.hf, acc.hf_hint),
            h("span", { text: "download subfolder" }), dir,
        ));
        accSect.append(h("div", { class: "ull-dim", text: "Keys are kept on this computer in ComfyUI's user folder and are never written into a workflow. A Civitai key lets the search and lookup see models hidden from anonymous visitors and download ones that need a sign-in; civitai.red is the unrestricted address, asked as a backup either way. A Hugging Face token is only needed for gated repos." }));
    }

    pop.append(
        h("div", { class: "ull-bar" }, h("h3", { class: "ull-h3", text: "lora loader settings", style: { flex: "1" } }), btn("✕", "Close", closeSettings)),
        h("span", { class: "ull-label", text: "this node" }), grid, h("div", { class: "ull-bar" }, useDefault),
        h("hr", { class: "ull-divider" }),
        h("span", { class: "ull-label", text: "Civitai / Hugging Face (this computer)" }), accSect,
    );
}
