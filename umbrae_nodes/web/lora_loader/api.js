// web/lora_loader/api.js — umbrae_nodes v0.9.3
// Thin fetch wrappers over modules/lora_loader/server.py. The file list is cached
// for the session (refetched on every picker open); info is cached per LoRA.
import { api } from "../../../scripts/api.js";

const BASE = "/umbrae/lora";

async function getJSON(path, params) {
    const qs = params ? "?" + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")).toString() : "";
    try {
        const r = await api.fetchApi(BASE + path + qs, { cache: "no-store" });
        return await r.json();
    } catch (e) {
        return { ok: false, message: "Could not reach the server." };
    }
}
async function postJSON(path, body) {
    try {
        const r = await api.fetchApi(BASE + path, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}),
        });
        return await r.json();
    } catch (e) {
        return { ok: false, message: "Could not reach the server." };
    }
}

// ── local files ──────────────────────────────────────────────────────────────
let _list = null, _listPromise = null;

export async function listLoras(force = false) {
    if (!force && _list) return _list;
    if (!force && _listPromise) return _listPromise;
    const p = (async () => {
        const j = await getJSON("/list");
        if (j?.ok && Array.isArray(j.loras)) _list = j.loras;
        if (_listPromise === p) _listPromise = null;
        return _list || [];
    })();
    _listPromise = p;
    return p;
}
export function cachedList() { return _list; }
export function hasLora(name) { return _list ? _list.includes(name) : null; }
export function invalidateList() { _list = null; }

// ── info ─────────────────────────────────────────────────────────────────────
const _info = new Map();

export async function loraInfo(name, force = false) {
    if (!name) return { ok: false, message: "No LoRA selected." };
    if (!force && _info.has(name)) return _info.get(name);
    const j = await getJSON("/info", { name });
    if (j?.ok) _info.set(name, j);
    return j;
}
export function invalidateInfo(name) { if (name) _info.delete(name); else _info.clear(); }

export function thumbUrl(name, v) {
    return api.apiURL(BASE + "/thumb?name=" + encodeURIComponent(name) + (v ? "&v=" + v : ""));
}

// ── Civitai ──────────────────────────────────────────────────────────────────
export async function civitaiLookup(name, force = false) {
    const j = await getJSON("/civitai", { name, force: force ? 1 : "" });
    if (j?.ok) _info.delete(name);
    return j;
}
export function civitaiSearch(params) { return getJSON("/civitai/search", params); }
export async function deleteCivitai(name) {
    const j = await postJSON("/civitai_delete", { name });
    if (j?.ok) _info.delete(name);
    return j;
}

// ── Hugging Face ─────────────────────────────────────────────────────────────
export function hfSearch(params) { return getJSON("/hf/search", params); }
export function hfRepo(repo) { return getJSON("/hf/repo", { repo }); }

// ── downloads ────────────────────────────────────────────────────────────────
export function startDownload(body) { return postJSON("/download", body); }
export function downloadStatus(job) { return getJSON("/download/status", { job }); }
export function cancelDownload(job) { return postJSON("/download/cancel", { job }); }

// ── account / stores ─────────────────────────────────────────────────────────
export function getAccount() { return getJSON("/account"); }
export function setAccount(patch) { return postJSON("/account", patch); }

export async function saveCustomTriggers(name, words) {
    const j = await postJSON("/custom_triggers", { name, words });
    if (j?.ok) _info.delete(name);
    return j;
}
export async function savePreview(name, { dataUrl, url }) {
    const j = await postJSON("/preview", { name, dataUrl, url });
    if (j?.ok) _info.delete(name);
    return j;
}
export async function deletePreview(name) {
    const j = await postJSON("/preview_delete", { name });
    if (j?.ok) _info.delete(name);
    return j;
}
