// web/lora_loader/info.js — umbrae_nodes v0.9.3
// The info panel for one row: gallery + facts + description from Civitai (or
// the file), trigger words to tick for the triggers output, your own words,
// and the preview picture.
import { h, btn, toast, copyText, fmtBytes, fmtCount, openOverlay, closeOverlay, openLightbox } from "./ui.js";
import { loraInfo, civitaiLookup, deleteCivitai, saveCustomTriggers, savePreview, deletePreview, thumbUrl, invalidateInfo } from "./api.js";
import { readState, patchRow, rowOf } from "./state.js";
import { gallery } from "./picker.js";

export function closeInfo() { closeOverlay("info"); }

// Tick the authoritative words once per LoRA: Civitai's trainedWords when
// known, else the author's declared phrase. Never the training tags.
export function autoTick(node, id, info) {
    const row = rowOf(node, id);
    if (!row || row.at || !info) return false;
    const words = (info.civitai?.triggers?.length ? info.civitai.triggers : info.explicit_triggers || []).filter((w) => String(w).trim());
    patchRow(node, id, { triggers: words, at: true });
    return words.length > 0;
}

export async function openInfo(node, id, refresh) {
    const row = rowOf(node, id);
    if (!row?.name) return;
    const name = row.name;
    const { pop } = openOverlay("info", { width: 900 });
    pop.style.height = "min(680px, 88vh)";
    const head = h("div", { class: "ull-bar" });
    const bodyEl = h("div", { class: "ull-info" });
    const left = h("div", { class: "left" }), right = h("div", { class: "right" });
    bodyEl.append(left, right);
    pop.append(head, bodyEl);
    let info = null, msg = "", busy = false, view = null;   // view: "civitai" | "file"

    async function load(force) {
        const r = await loraInfo(name, force);
        if (!r.ok) { msg = r.message || "could not read"; info = null; }
        else { info = r.info; }
        render();
    }
    function civ() { return info?.civitai || null; }
    function fileWords() { return info?.file_triggers || []; }
    function civWords() { return civ()?.triggers || []; }
    function source() { if (view) return view; return civWords().length ? "civitai" : "file"; }
    function words() { return source() === "civitai" ? civWords() : fileWords(); }
    function picked() { return new Set((rowOf(node, id)?.triggers || []).map((w) => w.toLowerCase())); }
    function setPicked(list) { patchRow(node, id, { triggers: list, at: true }); refresh?.(); }
    function toggleWord(w) {
        const cur = rowOf(node, id)?.triggers || [];
        const i = cur.findIndex((x) => x.toLowerCase() === w.toLowerCase());
        setPicked(i >= 0 ? cur.filter((_, k) => k !== i) : [...cur, w]);
        render();
    }
    function imagesFor() {
        const ims = civ()?.images || [];
        if (ims.length) return ims;
        if (info?.has_preview) return [{ url: thumbUrl(name, info.preview_v), medium: thumbUrl(name, info.preview_v), thumb: thumbUrl(name, info.preview_v), nsfw: 1 }];
        return [];
    }
    async function usePreview(im) {
        if (!im?.url) return;
        busy = true; render();
        const r = im.url.startsWith("http") ? await savePreview(name, { url: im.url }) : { ok: false, message: "already the preview" };
        busy = false;
        if (!r.ok) toast("warn", "Preview not saved", r.message);
        else toast("success", "Preview saved");
        await load(true);
    }
    function pickFile() {
        const input = h("input", { type: "file", accept: "image/*" });
        input.addEventListener("change", () => { const f = input.files?.[0]; if (f) fileToPreview(f); });
        input.click();
    }
    async function fileToPreview(file) {
        const dataUrl = await downscale(file, 768);
        if (!dataUrl) { toast("warn", "That picture could not be read"); return; }
        const r = await savePreview(name, { dataUrl });
        if (!r.ok) toast("warn", "Preview not saved", r.message); else toast("success", "Preview saved");
        await load(true);
    }
    pop.addEventListener("paste", (e) => {
        for (const it of e.clipboardData?.items || []) {
            if (it.type.startsWith("image/")) { e.preventDefault(); const f = it.getAsFile(); if (f) fileToPreview(f); return; }
        }
    });
    pop.addEventListener("dragover", (e) => { e.preventDefault(); });
    pop.addEventListener("drop", (e) => { e.preventDefault(); const f = e.dataTransfer?.files?.[0]; if (f && f.type.startsWith("image/")) fileToPreview(f); });

    async function lookup(force) {
        busy = true; msg = force ? "asking Civitai again…" : "hashing the file and asking Civitai…"; render();
        const r = await civitaiLookup(name, force);
        busy = false;
        if (!r.ok) { msg = r.message || "lookup failed"; render(); return; }
        if (!r.found) { msg = "Not on Civitai (no model has this exact file). If it is an adult-rated model, add an API key or ask civitai.red first in the settings."; render(); return; }
        msg = r.cached ? "" : "found on Civitai";
        view = "civitai";
        await load(true);
        if (!rowOf(node, id)?.at) { autoTick(node, id, info); refresh?.(); render(); }
    }
    async function forget() {
        const r = await deleteCivitai(name);
        if (!r.ok) { toast("warn", "Could not remove", r.message); return; }
        view = "file"; msg = "";
        await load(true);
    }
    async function addCustom(word) {
        const w = String(word || "").trim();
        if (!w) return;
        const cur = info?.custom_triggers || [];
        if (cur.some((x) => x.toLowerCase() === w.toLowerCase())) { toggleWord(w); return; }
        const r = await saveCustomTriggers(name, [...cur, w]);
        if (!r.ok) { toast("warn", "Could not save the word", r.message); return; }
        const pk = rowOf(node, id)?.triggers || [];
        setPicked([...pk, w]);
        await load(true);
    }
    async function removeCustom(word) {
        const cur = (info?.custom_triggers || []).filter((x) => x.toLowerCase() !== word.toLowerCase());
        const r = await saveCustomTriggers(name, cur);
        if (!r.ok) { toast("warn", "Could not remove the word", r.message); return; }
        const pk = (rowOf(node, id)?.triggers || []).filter((x) => x.toLowerCase() !== word.toLowerCase());
        setPicked(pk);
        await load(true);
    }

    function render() {
        const c = civ();
        const title = c?.name || info?.title || name;
        head.replaceChildren(...[
            h("div", { style: { flex: "1", minWidth: "0" } },
                h("div", { class: "ull-title", text: title }),
                h("div", { class: "ull-dim", text: name + (c?.version_name ? " · " + c.version_name : "") })),
            c?.url ? h("a", { class: "ull-link", href: c.url, target: "_blank", text: c.source === "hf" ? "open on Hugging Face ↗" : "open on Civitai ↗" }) : null,
            btn("✕", "Close", closeInfo)].filter(Boolean));

        // left: pictures
        left.replaceChildren();
        const ims = imagesFor();
        const thumbsOn = readState(node).thumbs !== false;
        if (thumbsOn) left.append(gallery(ims, { onUse: (im) => usePreview(im) }));
        else left.append(h("div", { class: "ull-dim", text: "thumbnails are off in the settings" }));
        const picRow = h("div", { class: "ull-pic-row" },
            btn("Choose picture…", "Use a picture from your computer (or paste / drop one on this panel)", pickFile, "tiny"),
            info?.custom_preview ? btn("Remove own picture", "Go back to the automatic picture", async () => { await deletePreview(name); await load(true); }, "tiny danger") : null);
        left.append(picRow);
        if (info?.custom_preview) left.append(h("img", { src: thumbUrl(name, info.preview_v), style: { width: "64px", height: "64px", objectFit: "cover", borderRadius: "4px", border: "1px solid var(--ud-border)" }, title: "your own preview" }));

        // right: facts, words, description
        right.replaceChildren();
        if (!info) { right.append(h("div", { class: "ull-err", text: msg || "loading…" })); return; }
        const kv = [];
        const add = (k, v) => { if (v) kv.push(h("span", { class: "k", text: k }), h("span", { text: String(v) })); };
        add("base model", c?.base_model || info.base_model);
        add("type", c?.type);
        add("creator", c?.creator);
        add("published", c?.published);
        add("downloads", c?.downloads != null ? fmtCount(c.downloads) : "");
        add("likes", c?.likes != null ? fmtCount(c.likes) : "");
        add("file", [fmtBytes(info.size), info.rank ? "rank " + info.rank : "", info.alpha ? "alpha " + info.alpha : "",
            info.num_images ? info.num_images + " training images" : "", info.date].filter(Boolean).join(" · "));
        if (c?.tags?.length) add("tags", c.tags.join(", "));
        right.append(h("div", { class: "ull-kv" }, ...kv));

        // civitai row
        const civRow = h("div", { class: "ull-bar" });
        civRow.append(btn(c && c.source !== "hf" ? "↻ Refresh from Civitai" : "Look up on Civitai", "Hash the file and fetch the model's gallery, words and description (saved next to the file)", () => lookup(!!c), busy ? "" : (c ? "" : "primary")));
        if (c) civRow.append(btn("Remove saved data", "Delete the .civitai.info file next to the LoRA", forget, "tiny danger"));
        if (msg) civRow.append(h("span", { class: busy ? "ull-dim" : "ull-dim", text: msg }));
        right.append(civRow);

        // trigger words
        const pk = picked();
        const sect = h("div", { class: "ull-sect" });
        const headRow = h("div", { class: "ull-bar" }, h("span", { class: "ull-label", text: "trigger words" }));
        if (civWords().length && fileWords().length) {
            const seg = h("div", { class: "ull-seg" },
                h("span", { class: source() === "civitai" ? "on" : "", text: "Civitai", onclick: () => { view = "civitai"; render(); } }),
                h("span", { class: source() === "file" ? "on" : "", text: "file", onclick: () => { view = "file"; render(); } }));
            headRow.append(seg);
        } else headRow.append(h("span", { class: "ull-dim", text: civWords().length ? (c?.source === "hf" ? "from Hugging Face" : "from Civitai") : (fileWords().length ? "from the file" : "") }));
        headRow.append(h("span", { style: { flex: "1" } }),
            btn("all", "", () => setPickedAll(true), "tiny"), btn("none", "", () => setPickedAll(false), "tiny"),
            btn("copy ticked", "Copy the ticked words", (e) => copyText((rowOf(node, id)?.triggers || []).join(readState(node).sep), e.currentTarget), "tiny"));
        sect.append(headRow);
        const chips = h("div", { class: "ull-chips" });
        const ws = words();
        for (const w of ws) chips.append(h("span", { class: "ull-chip" + (pk.has(w.toLowerCase()) ? " sel" : ""), onclick: () => toggleWord(w) }, h("span", { class: "ct", text: w })));
        for (const w of info.custom_triggers || []) {
            chips.append(h("span", { class: "ull-chip custom" + (pk.has(w.toLowerCase()) ? " sel" : ""), onclick: () => toggleWord(w), title: "your own word (click the × to forget it)" },
                h("span", { class: "ct", text: w }), h("span", { class: "cx", text: "✕", onclick: (e) => { e.stopPropagation(); removeCustom(w); } })));
        }
        // ticked words that belong to neither list (e.g. from a previous source)
        for (const w of rowOf(node, id)?.triggers || []) {
            if (!ws.some((x) => x.toLowerCase() === w.toLowerCase()) && !(info.custom_triggers || []).some((x) => x.toLowerCase() === w.toLowerCase()))
                chips.append(h("span", { class: "ull-chip sel", onclick: () => toggleWord(w), title: "ticked on this row" }, h("span", { class: "ct", text: w })));
        }
        if (!chips.children.length) chips.append(h("span", { class: "ull-dim", text: "no trigger words known for this file — type your own below" + (c ? "" : ", or look it up on Civitai") }));
        sect.append(chips);
        const inp = h("input", { class: "ull-in grow", placeholder: "add your own trigger word… (Enter)" });
        inp.addEventListener("keydown", (e) => { if (e.key === "Enter") { addCustom(inp.value); inp.value = ""; } });
        sect.append(h("div", { class: "ull-bar" }, inp, btn("add", "", () => { addCustom(inp.value); inp.value = ""; }, "tiny")));
        right.append(sect);
        function setPickedAll(on) { setPicked(on ? [...new Set([...ws, ...(info.custom_triggers || [])])] : []); render(); }

        if (c?.description) {
            const d = h("div", { class: "ull-desc" + (c.description.length > 500 ? " long" : ""), text: c.description });
            const t = c.description.length > 500 ? btn("more", "", () => { d.classList.toggle("open"); t.textContent = d.classList.contains("open") ? "less" : "more"; }, "tiny") : null;
            right.append(h("div", { class: "ull-sect" }, h("div", { class: "ull-bar" }, h("span", { class: "ull-label", text: "description" }), t), d));
        }
        if (c?.version_notes) right.append(h("div", { class: "ull-sect" }, h("span", { class: "ull-label", text: "version notes" }), h("div", { class: "ull-desc", text: c.version_notes })));
        if (c?.files?.length) right.append(h("div", { class: "ull-kv" }, h("span", { class: "k", text: "civitai file" }), h("span", { text: c.files.map((f) => f.name).join(", ") })));
    }

    render();
    await load(false);
    if (info && !rowOf(node, id)?.at) { if (autoTick(node, id, info)) { refresh?.(); render(); } }
}

async function downscale(file, max) {
    try {
        const bmp = await createImageBitmap(file);
        const s = Math.min(1, max / Math.max(bmp.width, bmp.height));
        const cv = document.createElement("canvas");
        cv.width = Math.round(bmp.width * s); cv.height = Math.round(bmp.height * s);
        cv.getContext("2d").drawImage(bmp, 0, 0, cv.width, cv.height);
        return cv.toDataURL("image/jpeg", 0.9);
    } catch (_) { return null; }
}
