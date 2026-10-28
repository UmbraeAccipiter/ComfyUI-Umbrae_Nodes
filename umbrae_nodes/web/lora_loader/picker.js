// web/lora_loader/picker.js — umbrae_nodes v0.9.3
// The LoRA picker: Local files (search + browse by folder), Civitai search and
// Hugging Face search, with downloads straight into models/loras.
import { h, btn, toast, fmtBytes, fmtCount, baseName, folderOf, stripExt, openOverlay, openLightbox } from "./ui.js";
import { listLoras, invalidateList, hasLora, civitaiSearch, hfSearch, hfRepo, startDownload, downloadStatus,
         cancelDownload, getAccount, thumbUrl, loraInfo } from "./api.js";

const BASE_MODELS = ["", "SD 1.5", "SD 2.1", "SDXL 1.0", "Pony", "Illustrious", "NoobAI", "Flux.1 D", "Flux.1 S",
    "Flux.1 Krea", "SD 3.5", "SD 3.5 Large", "SD 3.5 Medium", "Hunyuan Video", "Wan Video", "Wan Video 2.2 T2V-A14B",
    "Qwen", "Lumina", "Kolors", "Other"];
const SORTS = ["Most Downloaded", "Highest Rated", "Newest"];
const PERIODS = ["AllTime", "Year", "Month", "Week", "Day"];
const HF_SORTS = [["downloads", "Most downloads"], ["likes", "Most likes"], ["lastModified", "Recently updated"], ["trendingScore", "Trending"]];

let _lastTab = "local";
let _civ = { q: "", base: "", sort: "Most Downloaded", period: "AllTime", nsfw: "false" };
let _hf = { q: "", sort: "downloads" };

export function openPicker({ current = "", onPick }) {
    const { pop, close } = openOverlay("picker", { width: 820 });
    const title = h("h3", { class: "ull-h3", text: "Pick a LoRA" }, h("span", { class: "sub", text: current ? "current: " + current : "" }));
    const tabs = h("div", { class: "ull-tabs" });
    const body = h("div", { style: { display: "flex", flexDirection: "column", gap: "6px", flex: "1", minHeight: "0" } });
    pop.append(title, tabs, body);
    pop.style.height = "min(640px, 88vh)";

    const pick = (name) => { onPick?.(name); close(); };
    const views = { local: () => localTab(body, current, pick), civitai: () => civitaiTab(body, pick), hf: () => hfTab(body, pick) };
    const tabEls = {};
    for (const [k, label] of [["local", "Local files"], ["civitai", "Civitai"], ["hf", "Hugging Face"]]) {
        tabEls[k] = h("div", { class: "ull-tab", text: label, onclick: () => show(k) });
        tabs.append(tabEls[k]);
    }
    function show(k) {
        _lastTab = k;
        for (const [kk, el] of Object.entries(tabEls)) el.classList.toggle("on", kk === k);
        body.replaceChildren();
        views[k]();
    }
    show(_lastTab);
}

// ── Local ────────────────────────────────────────────────────────────────────
function localTab(body, current, pick) {
    const search = h("input", { class: "ull-in grow", placeholder: "search your LoRAs… (every word must match)" });
    const refresh = btn("↻", "Rescan the loras folder", async () => { refresh.disabled = true; await listLoras(true); refresh.disabled = false; render(); });
    const crumb = h("div", { class: "ull-crumb" });
    const list = h("div", { class: "ull-scroll" });
    const status = h("span", { class: "ull-dim" });
    body.append(h("div", { class: "ull-bar" }, search, refresh, status), crumb, list);
    let folder = folderOf(current);
    let timer = null;

    async function render() {
        const all = await listLoras();
        const q = search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
        list.replaceChildren();
        crumb.replaceChildren();
        if (q.length) {
            crumb.append(h("span", { class: "here", text: "search results" }));
            const hits = all.filter((n) => { const s = n.toLowerCase(); return q.every((w) => s.includes(w)); });
            status.textContent = `${hits.length} of ${all.length}`;
            for (const n of hits.slice(0, 400)) list.append(fileItem(n, true));
            if (!hits.length) list.append(h("div", { class: "ull-dim", text: "nothing matches", style: { padding: "8px" } }));
            return;
        }
        status.textContent = `${all.length} files`;
        const parts = folder ? folder.replace(/\\/g, "/").split("/") : [];
        crumb.append(h("span", { class: "c" + (parts.length ? "" : " here"), text: "loras", onclick: () => { folder = ""; render(); } }));
        parts.forEach((p, i) => {
            crumb.append(h("span", { text: " / " }));
            crumb.append(h("span", { class: "c" + (i === parts.length - 1 ? " here" : ""), text: p, onclick: () => { folder = parts.slice(0, i + 1).join("/"); render(); } }));
        });
        const subs = new Set(), files = [];
        for (const n of all) {
            const nn = n.replace(/\\/g, "/");
            if (folder && !nn.startsWith(folder + "/")) continue;
            const rest = folder ? nn.slice(folder.length + 1) : nn;
            const i = rest.indexOf("/");
            if (i >= 0) subs.add(rest.slice(0, i)); else files.push(n);
        }
        if (folder) list.append(h("div", { class: "ull-item", onclick: () => { folder = folderOf(folder); render(); } }, h("span", { class: "ic", text: "↑" }), h("span", { class: "nm ull-dim", text: ".." })));
        for (const s of [...subs].sort((a, b) => a.localeCompare(b))) {
            list.append(h("div", { class: "ull-item", onclick: () => { folder = folder ? folder + "/" + s : s; render(); } }, h("span", { class: "ic", text: "📁" }), h("span", { class: "nm", text: s })));
        }
        for (const n of files.sort((a, b) => baseName(a).localeCompare(baseName(b)))) list.append(fileItem(n, false));
        if (!files.length && !subs.size) list.append(h("div", { class: "ull-dim", text: "no LoRAs here", style: { padding: "8px" } }));
        const cur = list.querySelector(".cur"); if (cur) cur.scrollIntoView({ block: "center" });
    }
    function fileItem(n, showFolder) {
        const img = h("img", { class: "thumb", loading: "lazy", src: thumbUrl(n), onerror: (e) => { e.target.style.visibility = "hidden"; } });
        return h("div", { class: "ull-item" + (n === current ? " cur" : ""), title: n, onclick: () => pick(n) },
            img, h("span", { class: "nm", text: stripExt(baseName(n)) }),
            showFolder && folderOf(n) ? h("span", { class: "fld", text: folderOf(n) }) : null);
    }
    search.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(render, 120); });
    search.addEventListener("keydown", (e) => { if (e.key === "Enter") { const f = list.querySelector(".ull-item .thumb"); f?.parentElement?.click(); } });
    render();
    search.focus();
}

// ── download runner (shared by both remote tabs) ─────────────────────────────
function downloadBox({ source, url, filename, sidecar, subdirInput, onDone }) {
    const bar = h("div", { class: "ull-prog" }, h("div"));
    const txt = h("span", { class: "ull-dim", text: "" });
    const cancel = btn("cancel", "", async () => { if (job) await cancelDownload(job); }, "tiny");
    const box = h("div", { class: "ull-sect", style: { display: "none" } }, bar, h("div", { class: "ull-bar" }, txt, cancel));
    let job = null, timer = null;
    async function start(overwrite = false) {
        box.style.display = "";
        txt.textContent = "starting…";
        const r = await startDownload({ source, url, filename, subdir: subdirInput.value, overwrite, sidecar });
        if (!r.ok) {
            if (r.exists) {
                txt.replaceChildren("already there: ", h("span", { text: r.name }), " ",
                    btn("use it", "", () => { onDone(r.name); }, "tiny primary"), " ",
                    btn("overwrite", "", () => start(true), "tiny danger"));
                return;
            }
            txt.textContent = r.message || "download failed";
            txt.className = "ull-err";
            return;
        }
        txt.className = "ull-dim";
        job = r.job;
        poll();
    }
    async function poll() {
        const st = await downloadStatus(job);
        if (!st.ok) { txt.textContent = "lost track of the download"; return; }
        const pct = st.total ? Math.round(st.bytes / st.total * 100) : null;
        bar.firstChild.style.width = (pct ?? 20) + "%";
        txt.textContent = `${fmtBytes(st.bytes)}${st.total ? " / " + fmtBytes(st.total) : ""}${pct != null ? " · " + pct + "%" : ""}`;
        if (st.state === "running") { timer = setTimeout(poll, 700); return; }
        if (st.state === "done") {
            bar.firstChild.style.width = "100%";
            txt.textContent = "done: " + st.name;
            invalidateList();
            await listLoras(true);
            toast("success", "LoRA downloaded", st.name);
            onDone(st.name);
            return;
        }
        txt.textContent = st.state === "cancelled" ? "cancelled" : "failed: " + (st.error || "unknown error");
        txt.className = st.state === "cancelled" ? "ull-dim" : "ull-err";
    }
    box.start = start;
    box.stop = () => clearTimeout(timer);
    return box;
}

function subdirRow(acc) {
    const input = h("input", { class: "ull-in", placeholder: "subfolder (optional)", value: acc?.download_dir || "", style: { width: "180px" } });
    return { input, row: h("div", { class: "ull-bar" }, h("span", { class: "ull-label", text: "save to loras /" }), input) };
}

// ── Civitai ──────────────────────────────────────────────────────────────────
function civitaiTab(body, pick) {
    const q = h("input", { class: "ull-in grow", placeholder: "search Civitai for LoRAs…", value: _civ.q });
    const base = sel(BASE_MODELS.map((b) => [b, b || "any base model"]), _civ.base);
    const sort = sel(SORTS.map((s) => [s, s]), _civ.sort);
    const period = sel(PERIODS.map((p) => [p, p === "AllTime" ? "all time" : "this " + p.toLowerCase()]), _civ.period);
    const nsfw = sel([["false", "hide adult"], ["true", "include adult"]], _civ.nsfw);
    const go = btn("Search", "", () => search(true), "primary");
    const status = h("span", { class: "ull-dim" });
    const grid = h("div", { class: "ull-grid" });
    const scroll = h("div", { class: "ull-scroll" }, grid);
    const more = btn("Load more", "", () => search(false));
    const detailHost = h("div", { style: { display: "none", flex: "1", minHeight: "0", flexDirection: "column", gap: "6px" } });
    body.append(h("div", { class: "ull-bar" }, q, base, sort, period, nsfw, go), h("div", { class: "ull-bar" }, status), scroll, detailHost);
    let cursor = "", acc = null;
    getAccount().then((a) => { acc = a; if (a?.ok && !a.civitai) status.textContent = "tip: add a Civitai API key in the settings to see models hidden from anonymous searches."; });
    q.addEventListener("keydown", (e) => { if (e.key === "Enter") search(true); });

    async function search(reset) {
        Object.assign(_civ, { q: q.value.trim(), base: base.value, sort: sort.value, period: period.value, nsfw: nsfw.value });
        if (reset) { cursor = ""; grid.replaceChildren(); more.remove(); }
        go.disabled = true; status.textContent = "searching…"; status.className = "ull-dim";
        const r = await civitaiSearch({ q: _civ.q, base: _civ.base, sort: _civ.sort, period: _civ.period, nsfw: _civ.nsfw, cursor, limit: 24 });
        go.disabled = false;
        if (!r.ok) { status.textContent = r.message || "search failed"; status.className = "ull-err"; return; }
        cursor = r.next || "";
        for (const it of r.items) grid.append(card(it));
        status.textContent = grid.children.length ? `${grid.children.length} results` : "nothing found";
        more.remove();
        if (cursor && r.items.length) scroll.append(more);
    }
    function card(it) {
        const img = h("div", { class: "img" + (it.thumb ? "" : " none"), text: it.thumb ? "" : "no picture" });
        if (it.thumb) img.style.backgroundImage = `url("${it.thumb}")`;
        return h("div", { class: "ull-card", title: it.name, onclick: () => detail(it) }, img,
            h("div", { class: "body" }, h("div", { class: "nm", text: it.name }),
                h("div", { class: "meta" }, ...it.base_models.slice(0, 2).map((b) => h("span", { class: "ull-tag base", text: b })),
                    it.nsfw ? h("span", { class: "ull-tag", text: "adult" }) : null),
                h("div", { class: "meta" }, h("span", { text: "↓ " + fmtCount(it.downloads) }), h("span", { text: "♥ " + fmtCount(it.likes) }), h("span", { text: it.creator }))));
    }
    function detail(it) {
        scroll.style.display = "none"; status.parentElement.style.display = "none";
        detailHost.style.display = "flex"; detailHost.replaceChildren();
        const back = btn("‹ results", "", () => { detailHost.style.display = "none"; scroll.style.display = ""; status.parentElement.style.display = ""; });
        const link = h("a", { class: "ull-link", href: it.url, target: "_blank", text: "open on Civitai ↗" });
        let vi = 0;
        const verSel = sel(it.versions.map((v, i) => [String(i), `${v.version_name || "version"} · ${v.base_model}`]), "0");
        verSel.addEventListener("change", () => { vi = Number(verSel.value); renderVersion(); });
        const left = h("div", { class: "left" }), right = h("div", { class: "right" });
        detailHost.append(h("div", { class: "ull-bar" }, back, h("span", { class: "ull-title", text: it.name, style: { flex: "1", minWidth: "0", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }), link),
            h("div", { class: "ull-detail" }, left, right));
        const sub = subdirRow(acc);
        function renderVersion() {
            const v = it.versions[vi] || {};
            left.replaceChildren(gallery(v.images || []));
            right.replaceChildren();
            right.append(h("div", { class: "ull-bar" }, h("span", { class: "ull-label", text: "version" }), verSel));
            right.append(h("div", { class: "ull-kv" },
                kv("base model", v.base_model), kv("creator", it.creator), kv("published", v.published),
                kv("downloads", fmtCount(it.downloads)), kv("likes", fmtCount(it.likes)),
                kv("tags", it.tags.join(", "))));
            if (v.triggers?.length) right.append(h("div", { class: "ull-sect" }, h("span", { class: "ull-label", text: "trigger words" }),
                h("div", { class: "ull-chips" }, ...v.triggers.map((w) => h("span", { class: "ull-chip sel", text: w })))));
            if (it.description) right.append(descBlock(it.description));
            if (v.version_notes) right.append(h("div", { class: "ull-sect" }, h("span", { class: "ull-label", text: "version notes" }), h("div", { class: "ull-desc", text: v.version_notes })));
            right.append(h("div", { class: "ull-sect" }, h("span", { class: "ull-label", text: "files" }), sub.row,
                ...(v.files || []).map((f) => fileRow(f, v))));
            if (!(v.files || []).length) right.append(h("div", { class: "ull-dim", text: "no downloadable file on this version" }));
        }
        function fileRow(f, v) {
            const row = h("div", { class: "ull-sect" });
            const box = downloadBox({ source: "civitai", url: f.url, filename: f.name, sidecar: toSidecar(it, v), subdirInput: sub.input, onDone: (name) => pick(name) });
            const dl = btn("Download", "Download into models/loras" + (f.sha256 ? "" : ""), () => { dl.disabled = true; box.start(); }, "primary tiny");
            row.append(h("div", { class: "ull-file" }, h("span", { class: "nm", text: f.name, title: f.name }),
                h("span", { class: "sz", text: [f.fp, f.format, fmtBytes((f.sizeKB || 0) * 1024)].filter(Boolean).join(" · ") }), dl), box);
            return row;
        }
        renderVersion();
    }
}

// a sidecar in Civitai's own shape, so the info panel (and other tools) read it
function toSidecar(card, v) {
    return {
        id: v.version_id, modelId: card.id || v.model_id, name: v.version_name, baseModel: v.base_model,
        trainedWords: v.triggers || [], description: v.version_notes || "", publishedAt: v.published,
        downloadUrl: v.download_url,
        model: { name: card.name, type: card.type || "LORA", nsfw: !!card.nsfw },
        images: (v.images || []).map((im) => ({ url: im.url, nsfwLevel: im.nsfw, width: im.w, height: im.h, type: im.type, meta: im.prompt ? { prompt: im.prompt } : undefined })),
        files: (v.files || []).map((f) => ({ id: f.id, name: f.name, sizeKB: f.sizeKB, primary: f.primary, downloadUrl: f.url, hashes: f.sha256 ? { SHA256: f.sha256.toUpperCase() } : {} })),
        stats: { downloadCount: v.downloads, thumbsUpCount: v.likes },
        umbrae_model: { name: card.name, type: card.type, description: card.description, tags: card.tags, creator: { username: card.creator }, nsfw: !!card.nsfw, stats: { downloadCount: card.downloads, thumbsUpCount: card.likes } },
    };
}

// ── Hugging Face ─────────────────────────────────────────────────────────────
function hfTab(body, pick) {
    const q = h("input", { class: "ull-in grow", placeholder: "search Hugging Face for LoRA repos…", value: _hf.q });
    const sort = sel(HF_SORTS, _hf.sort);
    const go = btn("Search", "", () => search(), "primary");
    const status = h("span", { class: "ull-dim" });
    const list = h("div", { class: "ull-scroll" });
    const detailHost = h("div", { style: { display: "none", flex: "1", minHeight: "0", flexDirection: "column", gap: "6px" } });
    body.append(h("div", { class: "ull-bar" }, q, sort, go), h("div", { class: "ull-bar" }, status), list, detailHost);
    let acc = null;
    getAccount().then((a) => { acc = a; });
    q.addEventListener("keydown", (e) => { if (e.key === "Enter") search(); });

    async function search() {
        Object.assign(_hf, { q: q.value.trim(), sort: sort.value });
        go.disabled = true; status.textContent = "searching…"; status.className = "ull-dim";
        const r = await hfSearch({ q: _hf.q, sort: _hf.sort, limit: 40 });
        go.disabled = false;
        list.replaceChildren();
        if (!r.ok) { status.textContent = r.message || "search failed"; status.className = "ull-err"; return; }
        status.textContent = r.items.length ? `${r.items.length} repos (only repos tagged "lora" are listed)` : "nothing found";
        for (const it of r.items) {
            list.append(h("div", { class: "ull-item", onclick: () => detail(it) },
                h("span", { class: "ic", text: "🤗" }),
                h("div", { class: "nm" }, h("div", { text: it.id }),
                    h("div", { class: "ull-dim" }, ...it.base_models.slice(0, 2).map((b) => h("span", { class: "ull-tag base", text: b.split("/").pop(), style: { marginRight: "4px" } })),
                        h("span", { text: `${it.files.length} file${it.files.length === 1 ? "" : "s"} · ↓ ${fmtCount(it.downloads)} · ♥ ${fmtCount(it.likes)} · ${it.updated}` + (it.gated ? " · gated" : "") })))));
        }
    }
    async function detail(it) {
        list.style.display = "none"; status.parentElement.style.display = "none";
        detailHost.style.display = "flex"; detailHost.replaceChildren();
        const back = btn("‹ results", "", () => { detailHost.style.display = "none"; list.style.display = ""; status.parentElement.style.display = ""; });
        detailHost.append(h("div", { class: "ull-bar" }, back, h("span", { class: "ull-title", text: it.id, style: { flex: "1" } }),
            h("a", { class: "ull-link", href: it.url, target: "_blank", text: "open on Hugging Face ↗" })),
            h("div", { class: "ull-dim", text: "loading files…" }));
        const r = await hfRepo(it.id);
        if (!r.ok) { detailHost.append(h("div", { class: "ull-err", text: r.message || "could not read the repo" })); return; }
        const repo = r.repo;
        const left = h("div", { class: "left" }, gallery(repo.images || []));
        const right = h("div", { class: "right" });
        const sub = subdirRow(acc);
        right.append(h("div", { class: "ull-kv" }, kv("base model", repo.base_models.map((b) => b.split("/").pop()).join(", ")), kv("author", it.author),
            kv("license", repo.license), kv("downloads", fmtCount(it.downloads)), kv("likes", fmtCount(it.likes)), kv("tags", it.tags.join(", "))));
        if (repo.gated) right.append(h("div", { class: "ull-dim", text: "This repo is gated: accept its terms on huggingface.co and add your HF token in the settings before downloading." }));
        if (repo.triggers?.length) right.append(h("div", { class: "ull-sect" }, h("span", { class: "ull-label", text: "trigger words (from the model card)" }),
            h("div", { class: "ull-chips" }, ...repo.triggers.map((w) => h("span", { class: "ull-chip sel", text: w })))));
        right.append(h("div", { class: "ull-sect" }, h("span", { class: "ull-label", text: "files" }), sub.row));
        for (const f of repo.files) {
            const row = h("div", { class: "ull-sect" });
            const sidecar = {
                name: stripExt(baseName(f.name)), baseModel: repo.base_models[0] ? repo.base_models[0].split("/").pop() : "",
                trainedWords: repo.triggers || [], model: { name: it.id.split("/").pop(), type: "LORA" },
                images: (repo.images || []).map((im) => ({ url: im.url, nsfwLevel: 1 })),
                umbrae_model: { name: it.id, description: "", tags: it.tags, creator: { username: it.author }, stats: { downloadCount: it.downloads, thumbsUpCount: it.likes } },
                umbrae_url: repo.url, umbrae_source: "hf",
            };
            const box = downloadBox({ source: "hf", url: f.url, filename: baseName(f.name), sidecar, subdirInput: sub.input, onDone: (name) => pick(name) });
            const dl = btn("Download", "Download into models/loras", () => { dl.disabled = true; box.start(); }, "primary tiny");
            row.append(h("div", { class: "ull-file" }, h("span", { class: "nm", text: f.name, title: f.name }), h("span", { class: "sz", text: fmtBytes(f.size) }), dl), box);
            right.append(row);
        }
        if (!repo.files.length) right.append(h("div", { class: "ull-dim", text: "no LoRA weights file in this repo" }));
        detailHost.lastChild.remove();
        detailHost.append(h("div", { class: "ull-detail" }, left, right));
    }
    if (_hf.q) search(); else q.focus();
}

// ── bits ─────────────────────────────────────────────────────────────────────
function sel(options, value) {
    const s = h("select", { class: "ull-sel" });
    for (const [v, label] of options) s.append(h("option", { value: v, text: label }));
    s.value = value;
    return s;
}
function kv(k, v) { return v ? [h("span", { class: "k", text: k }), h("span", { text: String(v) })] : []; }
function descBlock(text) {
    const d = h("div", { class: "ull-desc" + (text.length > 500 ? " long" : ""), text });
    const t = text.length > 500 ? btn("more", "", () => { d.classList.toggle("open"); t.textContent = d.classList.contains("open") ? "less" : "more"; }, "tiny") : null;
    return h("div", { class: "ull-sect" }, h("div", { class: "ull-bar" }, h("span", { class: "ull-label", text: "description" }), t), d);
}
export function gallery(images, { onUse } = {}) {
    const wrap = h("div", { class: "ull-sect" });
    if (!images.length) { wrap.append(h("div", { class: "ull-main", text: "no pictures" })); return wrap; }
    let i = 0;
    const main = h("div", { class: "ull-main", title: "Click to view full size", onclick: () => openLightbox(images, i, { onUse }) });
    const strip = h("div", { class: "ull-strip" });
    const show = (k) => { i = k; main.style.backgroundImage = `url("${images[i].medium || images[i].url}")`; [...strip.children].forEach((c, j) => c.classList.toggle("on", j === i)); };
    images.forEach((im, k) => strip.append(h("img", { src: im.thumb || im.url, loading: "lazy", onclick: () => show(k), title: im.nsfw >= 4 ? "adult" : "" })));
    wrap.append(main, strip);
    if (onUse) wrap.append(h("div", { class: "ull-bar" }, btn("Use this picture as preview", "", () => onUse(images[i]), "tiny")));
    show(0);
    return wrap;
}
