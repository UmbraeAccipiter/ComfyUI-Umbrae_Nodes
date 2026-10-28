// umbrae_nodes/web/clause/wildcard_clause.js — umbrae_nodes v0.8.8
// Port of ComfyUI-WildcardClause web UI: node UmbraeWildcardClauseExpander,
// routes /umbrae/clause/*, picker /umbrae/wildcards/list, event umbrae-clause-feedback.
/**
 * WildcardClauseExpander UI — split layout with live structural preview,
 * wildcard picker (umbrae roots), and pysssss autocomplete on wildcard_text only.
 * Stock widgets stay for widgets_values / API serialization; custom DOM owns visuals.
 */
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { installDomWidgetWidthGuard } from "./dom_widget_width_guard.js";
import {
	DEFAULT_TEXTAREA_HEIGHTS,
	MIN_TEXTAREA_HEIGHT_PX,
} from "./textarea_heights.js";

import {
	ALL_OVERRIDE_KEYS,
	ATOM_FIELD_LABELS,
	ATOM_FIELD_TOOLTIPS,
	ATOM_OVERRIDE_KEYS,
	LEAF_OVERRIDE_KEYS,
	OVERRIDE_EXAMPLES,
	SCENE_FIELD_LABELS,
	SCENE_FIELD_TOOLTIPS,
	SKIP_OVERRIDE_SENTINEL,
} from "./wildcard_contract.js";

const ATOM_SUBGROUPS = [
	{
		title: "Identity",
		keys: ["age_override", "nationality_override", "eye_color_override"],
	},
	{
		title: "Hair",
		keys: ["hair_override", "hair_color_override"],
	},
	{
		title: "Body",
		keys: ["body_override", "breast_size_override", "butt_size_override"],
	},
	{
		title: "Face & skin finish",
		keys: ["face_override", "skin_override", "skin_tone_override"],
	},
	{
		title: "Adornment",
		keys: ["jewelry_override"],
	},
];

function isSkipOverride(value) {
	return value === SKIP_OVERRIDE_SENTINEL;
}

function isActiveOverride(value) {
	return isSkipOverride(value) || isNonEmpty(value);
}

const HIDDEN_WIDGET_NAMES = new Set([
	"wildcard_text",
	"populated_text",
	"mode",
	"seed",
	...ALL_OVERRIDE_KEYS,
]);

const PREVIEW_DEBOUNCE_MS = 300;
const DEFAULT_NODE_SIZE = [1020, 700];
const MIN_NODE_SIZE = [700, 500];
const LAYOUT_TITLE_CHROME = 48;
const STYLE_ID = "umbrae-clause-ui-styles";

let wildcardsList = [];
let wildcardsLoadPromise = null;
let catalogIndex = null;
let catalogLoadPromise = null;

function ensureStyles() {
	if (document.getElementById(STYLE_ID)) {
		return;
	}
	const style = document.createElement("style");
	style.id = STYLE_ID;
	style.textContent = `
.wc-dom-slot {
	width: 100%;
	box-sizing: border-box;
}
.wc-root {
	display: flex;
	flex-direction: row;
	gap: 10px;
	width: 100%;
	height: 100%;
	min-width: 0;
	min-height: 0;
	box-sizing: border-box;
	padding: 4px 2px 8px;
	overflow: auto;
	color: var(--fg-color, #ddd);
	font-size: 12px;
}
.wc-col {
	display: flex;
	flex-direction: column;
	gap: 8px;
	flex: 1 1 0;
	min-width: 0;
	min-height: 0;
}
.wc-label {
	font-weight: 600;
	letter-spacing: 0.02em;
	opacity: 0.9;
	margin: 0;
}
.wc-label-muted {
	font-weight: 500;
	opacity: 0.7;
	font-size: 11px;
}
.wc-row {
	display: flex;
	flex-direction: row;
	gap: 8px;
	align-items: center;
	flex-wrap: wrap;
}
.wc-row label {
	display: flex;
	align-items: center;
	gap: 4px;
}
.wc-textarea,
.wc-input,
.wc-select,
.wc-picker-input {
	width: 100%;
	box-sizing: border-box;
	background: var(--comfy-input-bg, #1e1e1e);
	color: var(--input-text, #ddd);
	border: 1px solid var(--border-color, #444);
	border-radius: 4px;
	padding: 6px 8px;
	font-family: inherit;
	font-size: 12px;
}
.wc-textarea {
	resize: vertical;
	min-height: ${MIN_TEXTAREA_HEIGHT_PX}px;
	line-height: 1.35;
}
.wc-textarea[readonly] {
	opacity: 0.95;
}
.wc-textarea:disabled {
	opacity: 0.65;
	cursor: not-allowed;
}
.wc-picker {
	position: relative;
}
.wc-picker-dropdown {
	position: absolute;
	left: 0;
	right: 0;
	top: 100%;
	z-index: 40;
	max-height: 220px;
	overflow: auto;
	background: var(--comfy-menu-bg, #222);
	border: 1px solid var(--border-color, #555);
	border-radius: 4px;
	box-shadow: 0 6px 18px rgba(0,0,0,0.35);
}
.wc-picker-item {
	padding: 5px 8px;
	cursor: pointer;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}
.wc-picker-item:hover,
.wc-picker-item.active {
	background: var(--comfy-menu-hover, #3a3a3a);
}
.wc-collapse {
	border: 1px solid var(--border-color, #444);
	border-radius: 4px;
	overflow: hidden;
	flex: 0 0 auto;
}
/* Open atom panel fills leftover left-column height (scene stays capped). */
.wc-collapse--grow.open {
	flex: 1 1 auto;
	min-height: 160px;
	display: flex;
	flex-direction: column;
}
.wc-collapse-header {
	display: flex;
	align-items: center;
	gap: 6px;
	width: 100%;
	padding: 6px 8px;
	background: rgba(255,255,255,0.04);
	border: 0;
	color: inherit;
	cursor: pointer;
	text-align: left;
	font: inherit;
	flex: 0 0 auto;
}
.wc-collapse-body {
	display: none;
	padding: 8px;
	min-height: 0;
}
.wc-collapse.open .wc-collapse-body {
	display: block;
}
.wc-collapse--grow.open .wc-collapse-body {
	display: flex;
	flex-direction: column;
	flex: 1 1 auto;
	min-height: 0;
	overflow: hidden;
}
.wc-collapse-scroll {
	display: flex;
	flex-direction: column;
	gap: 6px;
	overflow-x: hidden;
	overflow-y: auto;
	overscroll-behavior: contain;
	scrollbar-gutter: stable;
	padding-right: 2px;
}
.wc-collapse-scroll--scene {
	max-height: 200px;
}
.wc-collapse-scroll--atoms {
	flex: 1 1 auto;
	min-height: 0;
}
.wc-collapse-scroll::-webkit-scrollbar {
	width: 10px;
}
.wc-collapse-scroll::-webkit-scrollbar-track {
	background: rgba(0, 0, 0, 0.2);
	border-radius: 5px;
}
.wc-collapse-scroll::-webkit-scrollbar-thumb {
	background: rgba(255, 255, 255, 0.22);
	border-radius: 5px;
	border: 2px solid transparent;
	background-clip: padding-box;
}
.wc-collapse-scroll::-webkit-scrollbar-thumb:hover {
	background: rgba(255, 255, 255, 0.32);
	border: 2px solid transparent;
	background-clip: padding-box;
}
.wc-collapse-chevron::before {
	content: "▸";
	display: inline-block;
	width: 1em;
}
.wc-collapse.open .wc-collapse-chevron::before {
	content: "▾";
}
.wc-override-field {
	display: flex;
	flex-direction: column;
	gap: 2px;
}
.wc-override-field.dimmed {
	opacity: 0.45;
}
.wc-override-field.dimmed textarea {
	pointer-events: none;
}
.wc-override-label-row {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 6px;
}
.wc-pin-btn {
	flex: 0 0 auto;
	font-size: 10px;
	line-height: 1;
	padding: 2px 6px;
	border-radius: 3px;
	border: 1px solid var(--border-color, #555);
	background: rgba(255, 255, 255, 0.06);
	color: inherit;
	cursor: pointer;
	opacity: 0.85;
}
.wc-pin-btn:hover:not(:disabled) {
	background: rgba(255, 255, 255, 0.12);
}
.wc-pin-btn:disabled {
	opacity: 0.35;
	cursor: default;
}
.wc-reroll-btn {
	flex: 0 0 auto;
	font-size: 10px;
	line-height: 1;
	padding: 2px 6px;
	border-radius: 3px;
	border: 1px solid var(--border-color, #555);
	background: rgba(255, 255, 255, 0.06);
	color: inherit;
	cursor: pointer;
	opacity: 0.85;
}
.wc-reroll-btn:hover:not(:disabled) {
	background: rgba(255, 255, 255, 0.12);
}
.wc-reroll-btn:disabled {
	opacity: 0.35;
	cursor: default;
}
.wc-skip-btn {
	flex: 0 0 auto;
	font-size: 10px;
	line-height: 1;
	padding: 2px 6px;
	border-radius: 3px;
	border: 1px solid var(--border-color, #555);
	background: rgba(255, 255, 255, 0.06);
	color: inherit;
	cursor: pointer;
	opacity: 0.85;
}
.wc-skip-btn:hover:not(:disabled) {
	background: rgba(255, 255, 255, 0.12);
}
.wc-skip-btn:disabled {
	opacity: 0.35;
	cursor: default;
}
.wc-skip-btn.active {
	background: rgba(220, 140, 80, 0.35);
	border-color: rgba(220, 140, 80, 0.55);
	opacity: 1;
}
.wc-override-field.skipped textarea {
	pointer-events: none;
	opacity: 0.55;
}
.wc-override-label-actions {
	display: flex;
	align-items: center;
	gap: 4px;
	flex: 0 0 auto;
}
.wc-override-field.wc-has-ghost textarea::placeholder {
	opacity: 0.72;
	font-style: italic;
}
.wc-override-field.wc-tag-not-found textarea::placeholder {
	color: rgba(255, 196, 128, 0.78);
	font-style: italic;
	opacity: 1;
}
.wc-populated-ghost {
	opacity: 0.92;
}
.wc-hint {
	font-size: 10px;
	opacity: 0.75;
	margin: 0 0 4px;
	color: #c9a227;
}
.wc-presets-col {
	flex: 0 0 auto;
	width: 176px;
	min-width: 132px;
	max-width: 220px;
	display: flex;
	flex-direction: column;
	gap: 8px;
	border-right: 1px solid var(--border-color, #444);
	padding-right: 8px;
	min-height: 0;
}
.wc-presets-col.collapsed {
	width: 30px;
	min-width: 30px;
	padding-right: 4px;
	overflow: hidden;
}
.wc-presets-col.collapsed .wc-presets-body {
	display: none;
}
.wc-presets-toggle {
	align-self: flex-start;
}
.wc-presets-body {
	display: flex;
	flex-direction: column;
	gap: 8px;
	min-height: 0;
	flex: 1 1 auto;
}
.wc-preset-section {
	display: flex;
	flex-direction: column;
	gap: 4px;
	min-height: 0;
}
.wc-preset-header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	gap: 4px;
	min-width: 0;
}
.wc-preset-header .wc-label-muted {
	flex: 1 1 auto;
	min-width: 0;
}
.wc-preset-list {
	max-height: 120px;
	overflow: auto;
	border: 1px solid var(--border-color, #444);
	border-radius: 4px;
}
.wc-preset-item {
	padding: 4px 6px;
	cursor: pointer;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
	font-size: 11px;
}
.wc-preset-item.selected {
	background: rgba(255, 255, 255, 0.12);
}
.wc-preset-item.pack::after {
	content: " pack";
	opacity: 0.5;
	font-size: 9px;
}
.wc-preset-actions {
	display: flex;
	flex-wrap: nowrap;
	gap: 4px;
	flex: 0 0 auto;
}
.wc-header-actions {
	margin-left: auto;
	display: flex;
	gap: 4px;
	flex: 0 0 auto;
}
.wc-header-btn {
	flex: 0 0 auto;
	font-size: 10px;
	line-height: 1;
	padding: 2px 6px;
	border-radius: 3px;
	border: 1px solid var(--border-color, #555);
	background: rgba(255, 255, 255, 0.06);
	color: inherit;
	cursor: pointer;
	opacity: 0.85;
}
.wc-header-btn:hover:not(:disabled) {
	background: rgba(255, 255, 255, 0.12);
}
.wc-header-btn:disabled {
	opacity: 0.35;
	cursor: default;
}
.wc-collapse-header-title {
	flex: 1 1 auto;
	min-width: 0;
}
.wc-subgroup-title {
	font-size: 10px;
	font-weight: 600;
	text-transform: uppercase;
	letter-spacing: 0.06em;
	opacity: 0.55;
	margin: 6px 0 2px;
}
.wc-seed {
	width: 140px;
	max-width: 100%;
}
.wc-seed-control-wrap {
	display: flex;
	align-items: center;
	gap: 4px;
	flex: 0 0 auto;
}
.wc-seed-control-wrap select,
.wc-seed-control {
	width: auto;
	min-width: 88px;
	max-width: 140px;
	flex: 0 0 auto;
}
.wc-grow {
	flex: 1 1 auto;
	min-height: 0;
	display: flex;
	flex-direction: column;
	gap: 4px;
}
.wc-grow .wc-textarea {
	flex: 1 1 auto;
}
.wc-template {
	flex: 0 0 auto;
	min-height: 0;
	display: flex;
	flex-direction: column;
	gap: 4px;
}
.wc-template .wc-textarea {
	flex: 0 0 auto;
}
.wc-btn-primary {
	width: 100%;
	box-sizing: border-box;
	padding: 7px 10px;
	border-radius: 4px;
	border: 1px solid var(--border-color, #555);
	background: rgba(90, 140, 220, 0.35);
	color: inherit;
	font: inherit;
	font-weight: 600;
	cursor: pointer;
}
.wc-btn-primary:hover:not(:disabled) {
	background: rgba(90, 140, 220, 0.5);
}
.wc-btn-secondary {
	width: 100%;
	box-sizing: border-box;
	padding: 6px 10px;
	border-radius: 4px;
	border: 1px solid var(--border-color, #555);
	background: rgba(255, 255, 255, 0.06);
	color: inherit;
	font: inherit;
	font-size: 11px;
	cursor: pointer;
	text-align: left;
}
.wc-btn-secondary:hover:not(:disabled) {
	background: rgba(255, 255, 255, 0.12);
}
.wc-btn-secondary:disabled {
	opacity: 0.45;
	cursor: not-allowed;
}
.wc-picker-hint {
	font-size: 10px;
	opacity: 0.55;
	margin-top: 2px;
}
.wc-picker-item-meta {
	font-size: 10px;
	opacity: 0.55;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}
.wc-catalog-overlay {
	position: fixed;
	inset: 0;
	z-index: 10000;
	display: flex;
	align-items: center;
	justify-content: center;
	background: rgba(0, 0, 0, 0.62);
	padding: 16px;
	box-sizing: border-box;
}
.wc-catalog-modal {
	display: flex;
	flex-direction: column;
	width: min(920px, 100%);
	max-height: min(88vh, 760px);
	background: var(--comfy-menu-bg, #1e1e1e);
	border: 1px solid var(--border-color, #555);
	border-radius: 8px;
	box-shadow: 0 12px 40px rgba(0, 0, 0, 0.45);
	color: var(--fg-color, #ddd);
	font-size: 12px;
	overflow: hidden;
}
.wc-catalog-header {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 10px 12px;
	border-bottom: 1px solid var(--border-color, #444);
	flex-shrink: 0;
}
.wc-catalog-breadcrumbs {
	display: flex;
	align-items: center;
	gap: 4px;
	flex: 1 1 auto;
	min-width: 0;
	flex-wrap: wrap;
}
.wc-catalog-crumb {
	background: none;
	border: 0;
	color: inherit;
	font: inherit;
	padding: 2px 4px;
	border-radius: 3px;
	cursor: pointer;
	opacity: 0.85;
	max-width: 100%;
	overflow: hidden;
	text-overflow: ellipsis;
	white-space: nowrap;
}
.wc-catalog-crumb:hover {
	background: rgba(255, 255, 255, 0.08);
}
.wc-catalog-crumb.current {
	opacity: 1;
	font-weight: 600;
	cursor: default;
}
.wc-catalog-crumb-sep {
	opacity: 0.45;
	user-select: none;
}
.wc-catalog-search {
	flex: 0 1 220px;
	min-width: 120px;
	box-sizing: border-box;
	background: var(--comfy-input-bg, #1e1e1e);
	color: var(--input-text, #ddd);
	border: 1px solid var(--border-color, #444);
	border-radius: 4px;
	padding: 6px 8px;
	font: inherit;
}
.wc-catalog-close {
	flex: 0 0 auto;
	width: 28px;
	height: 28px;
	border-radius: 4px;
	border: 1px solid var(--border-color, #555);
	background: rgba(255, 255, 255, 0.06);
	color: inherit;
	font-size: 16px;
	line-height: 1;
	cursor: pointer;
}
.wc-catalog-close:hover {
	background: rgba(255, 255, 255, 0.12);
}
.wc-catalog-body {
	flex: 1 1 auto;
	min-height: 0;
	overflow: auto;
	padding: 12px;
}
.wc-catalog-grid {
	display: grid;
	gap: 10px;
}
.wc-catalog-grid--products {
	grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
}
.wc-catalog-grid--templates {
	grid-template-columns: repeat(3, minmax(0, 1fr));
}
.wc-catalog-card {
	display: flex;
	flex-direction: column;
	gap: 6px;
	padding: 8px;
	border: 1px solid var(--border-color, #444);
	border-radius: 6px;
	background: rgba(255, 255, 255, 0.03);
	cursor: pointer;
	text-align: left;
	color: inherit;
	font: inherit;
	min-width: 0;
}
.wc-catalog-card--folder .wc-catalog-card-title {
	padding-left: 2px;
}
.wc-catalog-card-title {
	font-weight: 600;
	line-height: 1.25;
	overflow: hidden;
	text-overflow: ellipsis;
	display: -webkit-box;
	-webkit-line-clamp: 2;
	-webkit-box-orient: vertical;
}
.wc-catalog-card-meta {
	font-size: 10px;
	opacity: 0.55;
}
.wc-catalog-thumb {
	width: 100%;
	aspect-ratio: 3 / 4;
	border-radius: 4px;
	overflow: hidden;
	background: rgba(0, 0, 0, 0.25);
	flex-shrink: 0;
}
.wc-catalog-thumb-img {
	width: 100%;
	height: 100%;
	object-fit: cover;
	display: block;
}
.wc-catalog-thumb-missing {
	background: repeating-linear-gradient(
		-45deg,
		rgba(255, 255, 255, 0.06),
		rgba(255, 255, 255, 0.06) 8px,
		rgba(255, 255, 255, 0.02) 8px,
		rgba(255, 255, 255, 0.02) 16px
	);
	border: 1px dashed rgba(255, 255, 255, 0.12);
}
.wc-catalog-router-list {
	display: flex;
	flex-direction: column;
	gap: 6px;
}
.wc-catalog-router-row {
	display: flex;
	align-items: center;
	gap: 10px;
	padding: 8px;
	border: 1px solid var(--border-color, #444);
	border-radius: 6px;
	background: rgba(255, 255, 255, 0.03);
	min-width: 0;
}
.wc-catalog-router-row .wc-catalog-thumb {
	width: 56px;
	aspect-ratio: 1;
}
.wc-catalog-router-main {
	flex: 1 1 auto;
	min-width: 0;
	border: 0;
	background: none;
	color: inherit;
	font: inherit;
	text-align: left;
	cursor: pointer;
	padding: 0;
}
.wc-catalog-router-main:hover .wc-catalog-card-title {
	text-decoration: underline;
}
.wc-catalog-router-drill {
	flex: 0 0 auto;
	width: 32px;
	height: 32px;
	border-radius: 4px;
	border: 1px solid var(--border-color, #555);
	background: rgba(255, 255, 255, 0.06);
	color: inherit;
	font-size: 14px;
	cursor: pointer;
}
.wc-catalog-router-drill:hover {
	background: rgba(255, 255, 255, 0.12);
}
.wc-catalog-search-list {
	display: flex;
	flex-direction: column;
	gap: 4px;
}
.wc-catalog-search-item {
	display: flex;
	flex-direction: column;
	gap: 2px;
	padding: 8px 10px;
	border: 1px solid var(--border-color, #444);
	border-radius: 4px;
	background: rgba(255, 255, 255, 0.03);
	cursor: pointer;
	text-align: left;
	color: inherit;
	font: inherit;
}
.wc-catalog-search-item:hover {
	background: var(--comfy-menu-hover, #3a3a3a);
}
.wc-catalog-empty {
	opacity: 0.6;
	padding: 24px 12px;
	text-align: center;
}
`;
	document.head.appendChild(style);
}

function loadWildcardsList() {
	if (!wildcardsLoadPromise) {
		wildcardsLoadPromise = api
			.fetchApi("/umbrae/wildcards/list")
			.then(async (res) => {
				if (!res.ok) {
					throw new Error(`wildcards list HTTP ${res.status}`);
				}
				const data = await res.json();
				wildcardsList = Array.isArray(data?.data) ? data.data : [];
				return wildcardsList;
			})
			.catch((err) => {
				console.warn("[umbrae clause] Failed to load /umbrae/wildcards/list", err);
				wildcardsList = [];
				wildcardsLoadPromise = null;
				return wildcardsList;
			});
	}
	return wildcardsLoadPromise;
}

function loadCatalogIndex() {
	if (!catalogLoadPromise) {
		catalogLoadPromise = api
			.fetchApi("/umbrae/clause/catalog")
			.then(async (res) => {
				if (!res.ok) {
					throw new Error(`catalog HTTP ${res.status}`);
				}
				const data = await res.json();
				catalogIndex =
					data && Array.isArray(data.products)
						? data
						: { products: [], groups: [] };
				if (!Array.isArray(catalogIndex.groups)) {
					catalogIndex.groups = [];
				}
				return catalogIndex;
			})
			.catch((err) => {
				console.warn("[umbrae clause] Failed to load /umbrae/clause/catalog", err);
				catalogIndex = { products: [], groups: [] };
				catalogLoadPromise = null;
				return catalogIndex;
			});
	}
	return catalogLoadPromise;
}

function resetWildcardClientCaches() {
	wildcardsList = [];
	wildcardsLoadPromise = null;
	catalogIndex = null;
	catalogLoadPromise = null;
}

function showWildcardNotice(summary, detail) {
	try {
		app.extensionManager?.toast?.add?.({
			severity: "info",
			summary,
			detail,
			life: 4000,
		});
	} catch {
		window.alert(detail ? `${summary}\n\n${detail}` : summary);
	}
}

async function reloadWildcardsFromDisk({ onReloading } = {}) {
	const confirmed = window.confirm(
		"Reload all wildcards (umbrae roots) from disk?\n\n" +
			"This re-reads the full wildcard corpus and may take a minute or more. " +
			"The UI will wait until reload finishes."
	);
	if (!confirmed) {
		return false;
	}
	onReloading?.(true);
	try {
		const res = await api.fetchApi("/umbrae/clause/wildcards/reload", {
			method: "POST",
		});
		if (!res.ok) {
			const err = await res.json().catch(() => ({}));
			throw new Error(err.error || `reload HTTP ${res.status}`);
		}
		const data = await res.json();
		resetWildcardClientCaches();
		await Promise.all([loadWildcardsList(), loadCatalogIndex()]);
		const count = Number(data?.count);
		showWildcardNotice(
			"Wildcards reloaded",
			Number.isFinite(count)
				? `${count.toLocaleString()} tags are available.`
				: "Wildcard list was refreshed."
		);
		return true;
	} catch (err) {
		console.warn("[umbrae clause] wildcard reload failed", err);
		window.alert("Wildcard reload failed. See the browser console for details.");
		return false;
	} finally {
		onReloading?.(false);
	}
}

function groupLabelForProduct(product) {
	const gp = product?.group_path || "";
	if (!gp) {
		return "";
	}
	const groups = catalogIndex?.groups || [];
	const group = groups.find((g) => g.path === gp);
	return group?.label || gp.split("/").pop() || "";
}

function childGroupsAt(parentPath) {
	const groups = catalogIndex?.groups || [];
	return groups
		.filter(
			(g) =>
				g.parent_path === parentPath &&
				g.path &&
				(g.child_paths?.length || g.product_ids?.length)
		)
		.sort((a, b) => (a.label || "").localeCompare(b.label || ""));
}

function productsAtGroupPath(groupPath) {
	const products = catalogIndex?.products || [];
	return products
		.filter((p) => (p.group_path || "") === groupPath)
		.sort((a, b) => (a.label || a.id || "").localeCompare(b.label || b.id || ""));
}

function groupCoverUrl(group) {
	const products = catalogIndex?.products || [];
	for (const pid of group?.product_ids || []) {
		const product = products.find((p) => p.id === pid);
		const url = productCoverUrl(product);
		if (url) {
			return url;
		}
	}
	for (const childPath of group?.child_paths || []) {
		const child = (catalogIndex?.groups || []).find((g) => g.path === childPath);
		const url = groupCoverUrl(child);
		if (url) {
			return url;
		}
	}
	return "";
}

function catalogHasFolderGroups() {
	return childGroupsAt("").length > 0;
}

const GROUP_LABEL_OVERRIDES = {
	krea2: "Krea 2",
	ideogram4: "Ideogram 4",
	"minimax-h3": "MiniMax H3",
	flux2: "Flux 2",
	illustrious: "Illustrious",
};

function deriveGroupLabelFromSegment(segment) {
	const key = String(segment || "").toLowerCase();
	if (GROUP_LABEL_OVERRIDES[key]) {
		return GROUP_LABEL_OVERRIDES[key];
	}
	const text = key.replace(/-/g, " ").trim();
	if (!text) {
		return "";
	}
	return text.charAt(0).toUpperCase() + text.slice(1);
}

function catalogSearchEntries(query) {
	const q = String(query || "").trim().toLowerCase();
	const products = catalogIndex?.products || [];
	const out = [];
	for (const product of products) {
		const productLabel = product.label || product.id || "";
		const folderLabel = groupLabelForProduct(product);
		const scopeLabel = folderLabel ? `${folderLabel} · ${productLabel}` : productLabel;
		for (const router of product.routers || []) {
			const hay =
				`${router.name || ""} ${router.label || ""} ${router.tag || ""} ${scopeLabel} ${folderLabel}`.toLowerCase();
			if (!q || hay.includes(q)) {
				out.push({
					tag: router.tag,
					label: router.label || router.name,
					productLabel,
					kind: "router",
					breadcrumb: scopeLabel,
				});
			}
		}
		for (const template of product.templates || []) {
			const hay =
				`${template.name || ""} ${template.label || ""} ${template.tag || ""} ${scopeLabel} ${folderLabel}`.toLowerCase();
			if (!q || hay.includes(q)) {
				let breadcrumb = scopeLabel;
				for (const router of product.routers || []) {
					if ((router.templates || []).includes(template.name)) {
						breadcrumb = `${scopeLabel} › ${router.label || router.name}`;
						break;
					}
				}
				out.push({
					tag: template.tag,
					label: template.label || template.name,
					productLabel,
					kind: "template",
					breadcrumb,
				});
			}
		}
		if (out.length >= 80) {
			break;
		}
	}
	return out.slice(0, 80);
}

let catalogModalState = null;

function createCatalogThumb(url, alt) {
	const wrap = document.createElement("div");
	wrap.className = "wc-catalog-thumb";
	if (url) {
		const img = document.createElement("img");
		img.className = "wc-catalog-thumb-img";
		img.alt = alt || "";
		img.src = url;
		img.onerror = () => {
			img.remove();
			wrap.classList.add("wc-catalog-thumb-missing");
		};
		wrap.appendChild(img);
	} else {
		wrap.classList.add("wc-catalog-thumb-missing");
	}
	return wrap;
}

function productCoverUrl(product) {
	const routers = product?.routers || [];
	return routers[0]?.cover_url || "";
}

function templatesForRouter(product, router) {
	const names = new Set(router?.templates || []);
	return (product?.templates || []).filter((t) => names.has(t.name));
}

function closeCatalogModal() {
	if (!catalogModalState) {
		return;
	}
	const { overlay, onKeyDown } = catalogModalState;
	document.removeEventListener("keydown", onKeyDown);
	overlay.remove();
	catalogModalState = null;
}

function openCatalogModal(onPick) {
	closeCatalogModal();

	const state = {
		level: "groups",
		groupPath: "",
		product: null,
		router: null,
		searchQuery: "",
	};

	const overlay = document.createElement("div");
	overlay.className = "wc-catalog-overlay";
	overlay.addEventListener("mousedown", (ev) => {
		if (ev.target === overlay) {
			closeCatalogModal();
		}
	});

	const modal = document.createElement("div");
	modal.className = "wc-catalog-modal";
	modal.addEventListener("mousedown", (ev) => ev.stopPropagation());

	const header = document.createElement("div");
	header.className = "wc-catalog-header";

	const breadcrumbsEl = document.createElement("div");
	breadcrumbsEl.className = "wc-catalog-breadcrumbs";

	const searchInput = document.createElement("input");
	searchInput.type = "text";
	searchInput.className = "wc-catalog-search";
	searchInput.placeholder = "Search templates & routers…";
	searchInput.autocomplete = "off";

	const closeBtn = document.createElement("button");
	closeBtn.type = "button";
	closeBtn.className = "wc-catalog-close";
	closeBtn.title = "Close";
	closeBtn.textContent = "×";
	closeBtn.addEventListener("click", closeCatalogModal);

	header.appendChild(breadcrumbsEl);
	header.appendChild(searchInput);
	header.appendChild(closeBtn);

	const body = document.createElement("div");
	body.className = "wc-catalog-body";

	modal.appendChild(header);
	modal.appendChild(body);
	overlay.appendChild(modal);
	document.body.appendChild(overlay);

	function pickAndClose(tag) {
		if (!tag) {
			return;
		}
		onPick(tag);
		closeCatalogModal();
	}

	function clearCatalogSearch() {
		state.searchQuery = "";
		searchInput.value = "";
	}

	function goGroups(groupPath = "") {
		clearCatalogSearch();
		state.level = "groups";
		state.groupPath = groupPath;
		state.product = null;
		state.router = null;
		render();
	}

	function goProducts(groupPath) {
		clearCatalogSearch();
		state.level = "products";
		state.groupPath = groupPath || "";
		state.product = null;
		state.router = null;
		render();
	}

	function goProductsLegacy() {
		goProducts("");
	}

	function goRouters(product) {
		clearCatalogSearch();
		state.level = "routers";
		state.product = product;
		state.router = null;
		render();
	}

	function goTemplates(router) {
		clearCatalogSearch();
		state.level = "templates";
		state.router = router;
		render();
	}

	function renderBreadcrumbs() {
		breadcrumbsEl.innerHTML = "";
		const useFolders = catalogHasFolderGroups();
		const crumbs = [];
		if (useFolders) {
			crumbs.push({ label: "Folders", action: () => goGroups("") });
			if (state.groupPath) {
				const parts = state.groupPath.split("/").filter(Boolean);
				let pathSoFar = "";
				for (const part of parts) {
					pathSoFar = pathSoFar ? `${pathSoFar}/${part}` : part;
					const pathCopy = pathSoFar;
					const group = (catalogIndex?.groups || []).find((g) => g.path === pathCopy);
					crumbs.push({
						label: group?.label || deriveGroupLabelFromSegment(part),
						action: () => {
							if (productsAtGroupPath(pathCopy).length > 0) {
								goProducts(pathCopy);
							} else {
								goGroups(pathCopy);
							}
						},
					});
				}
			}
		} else {
			crumbs.push({ label: "Products", action: goProductsLegacy });
		}
		if (state.product) {
			crumbs.push({
				label: state.product.label || state.product.id,
				action: () => goRouters(state.product),
			});
		}
		if (state.router) {
			crumbs.push({
				label: state.router.label || state.router.name,
				action: () => goTemplates(state.router),
			});
		}
		const isSearch = state.searchQuery.length >= 1;
		crumbs.forEach((crumb, i) => {
			if (i > 0) {
				const sep = document.createElement("span");
				sep.className = "wc-catalog-crumb-sep";
				sep.textContent = "›";
				breadcrumbsEl.appendChild(sep);
			}
			const btn = document.createElement("button");
			btn.type = "button";
			btn.className = "wc-catalog-crumb";
			btn.textContent = crumb.label;
			const isLast = i === crumbs.length - 1 && !isSearch;
			if (isLast) {
				btn.classList.add("current");
			} else {
				btn.addEventListener("click", crumb.action);
			}
			breadcrumbsEl.appendChild(btn);
		});
		if (isSearch) {
			if (crumbs.length) {
				const sep = document.createElement("span");
				sep.className = "wc-catalog-crumb-sep";
				sep.textContent = "›";
				breadcrumbsEl.appendChild(sep);
			}
			const searchCrumb = document.createElement("span");
			searchCrumb.className = "wc-catalog-crumb current";
			searchCrumb.textContent = "Search";
			breadcrumbsEl.appendChild(searchCrumb);
		}
	}

	function renderSearch() {
		body.innerHTML = "";
		const items = catalogSearchEntries(state.searchQuery);
		if (!items.length) {
			const empty = document.createElement("div");
			empty.className = "wc-catalog-empty";
			empty.textContent = "No matching templates or routers.";
			body.appendChild(empty);
			return;
		}
		const list = document.createElement("div");
		list.className = "wc-catalog-search-list";
		for (const entry of items) {
			const row = document.createElement("button");
			row.type = "button";
			row.className = "wc-catalog-search-item";
			const title = document.createElement("div");
			title.className = "wc-catalog-card-title";
			title.textContent = entry.label;
			const meta = document.createElement("div");
			meta.className = "wc-catalog-card-meta";
			meta.textContent = `${entry.breadcrumb || entry.productLabel} · ${entry.kind}`;
			row.appendChild(title);
			row.appendChild(meta);
			row.addEventListener("click", () => pickAndClose(entry.tag));
			list.appendChild(row);
		}
		body.appendChild(list);
	}

	function openFolder(group) {
		const childCount = (group?.child_paths || []).length;
		const productCount = (group?.product_ids || []).length;
		if (childCount > 0 && productCount === 0) {
			goGroups(group.path);
			return;
		}
		goProducts(group.path);
	}

	function renderGroups() {
		body.innerHTML = "";
		const folders = childGroupsAt(state.groupPath);
		if (!folders.length) {
			if (productsAtGroupPath(state.groupPath).length > 0) {
				renderProducts();
				return;
			}
			const empty = document.createElement("div");
			empty.className = "wc-catalog-empty";
			empty.textContent = "No template folders found.";
			body.appendChild(empty);
			return;
		}
		const grid = document.createElement("div");
		grid.className = "wc-catalog-grid wc-catalog-grid--products";
		for (const group of folders) {
			const card = document.createElement("button");
			card.type = "button";
			card.className = "wc-catalog-card wc-catalog-card--folder";
			card.appendChild(createCatalogThumb(groupCoverUrl(group), group.label));
			const title = document.createElement("div");
			title.className = "wc-catalog-card-title";
			title.textContent = group.label || group.path || "Folder";
			const meta = document.createElement("div");
			meta.className = "wc-catalog-card-meta";
			const productCount = (group.product_ids || []).length;
			const childCount = (group.child_paths || []).length;
			const parts = [];
			if (productCount) {
				parts.push(`${productCount} product${productCount === 1 ? "" : "s"}`);
			}
			if (childCount) {
				parts.push(`${childCount} subfolder${childCount === 1 ? "" : "s"}`);
			}
			if (!parts.length) {
				parts.push(
					`${group.router_count || 0} router${group.router_count === 1 ? "" : "s"} · ${group.template_count || 0} template${group.template_count === 1 ? "" : "s"}`
				);
			}
			meta.textContent = parts.join(" · ");
			card.appendChild(title);
			card.appendChild(meta);
			card.addEventListener("click", () => openFolder(group));
			grid.appendChild(card);
		}
		body.appendChild(grid);
	}

	function renderProducts() {
		body.innerHTML = "";
		const products = catalogHasFolderGroups()
			? productsAtGroupPath(state.groupPath)
			: catalogIndex?.products || [];
		if (!products.length) {
			const empty = document.createElement("div");
			empty.className = "wc-catalog-empty";
			empty.textContent = "No template products found.";
			body.appendChild(empty);
			return;
		}
		const grid = document.createElement("div");
		grid.className = "wc-catalog-grid wc-catalog-grid--products";
		for (const product of products) {
			const card = document.createElement("button");
			card.type = "button";
			card.className = "wc-catalog-card";
			card.appendChild(createCatalogThumb(productCoverUrl(product), product.label));
			const title = document.createElement("div");
			title.className = "wc-catalog-card-title";
			title.textContent = product.label || product.id;
			const meta = document.createElement("div");
			meta.className = "wc-catalog-card-meta";
			const routerCount = (product.routers || []).length;
			const templateCount = (product.templates || []).length;
			meta.textContent = `${routerCount} router${routerCount === 1 ? "" : "s"} · ${templateCount} template${templateCount === 1 ? "" : "s"}`;
			card.appendChild(title);
			card.appendChild(meta);
			card.addEventListener("click", () => goRouters(product));
			grid.appendChild(card);
		}
		body.appendChild(grid);
	}

	function renderRouters() {
		body.innerHTML = "";
		const routers = state.product?.routers || [];
		if (!routers.length) {
			const empty = document.createElement("div");
			empty.className = "wc-catalog-empty";
			empty.textContent = "No routers in this product.";
			body.appendChild(empty);
			return;
		}
		const list = document.createElement("div");
		list.className = "wc-catalog-router-list";
		for (const router of routers) {
			const row = document.createElement("div");
			row.className = "wc-catalog-router-row";
			row.appendChild(createCatalogThumb(router.cover_url, router.label));

			const main = document.createElement("button");
			main.type = "button";
			main.className = "wc-catalog-router-main";
			const title = document.createElement("div");
			title.className = "wc-catalog-card-title";
			title.textContent = router.label || router.name;
			const meta = document.createElement("div");
			meta.className = "wc-catalog-card-meta";
			const count = router.template_count ?? (router.templates || []).length;
			meta.textContent = `${count} template${count === 1 ? "" : "s"}`;
			main.appendChild(title);
			main.appendChild(meta);
			main.addEventListener("click", () => pickAndClose(router.tag));
			row.appendChild(main);

			const drill = document.createElement("button");
			drill.type = "button";
			drill.className = "wc-catalog-router-drill";
			drill.title = "Browse templates";
			drill.textContent = "›";
			drill.addEventListener("click", (ev) => {
				ev.stopPropagation();
				goTemplates(router);
			});
			row.appendChild(drill);

			list.appendChild(row);
		}
		body.appendChild(list);
	}

	function renderTemplates() {
		body.innerHTML = "";
		const templates = templatesForRouter(state.product, state.router);
		if (!templates.length) {
			const empty = document.createElement("div");
			empty.className = "wc-catalog-empty";
			empty.textContent = "No templates for this router.";
			body.appendChild(empty);
			return;
		}
		const grid = document.createElement("div");
		grid.className = "wc-catalog-grid wc-catalog-grid--templates";
		for (const template of templates) {
			const card = document.createElement("button");
			card.type = "button";
			card.className = "wc-catalog-card";
			card.appendChild(createCatalogThumb(template.thumb_url, template.label));
			const title = document.createElement("div");
			title.className = "wc-catalog-card-title";
			title.textContent = template.label || template.name;
			card.appendChild(title);
			card.addEventListener("click", () => pickAndClose(template.tag));
			grid.appendChild(card);
		}
		body.appendChild(grid);
	}

	function render() {
		renderBreadcrumbs();
		if (state.searchQuery.length >= 1) {
			renderSearch();
			return;
		}
		if (state.level === "templates" && state.product && state.router) {
			renderTemplates();
		} else if (state.level === "routers" && state.product) {
			renderRouters();
		} else if (state.level === "products") {
			renderProducts();
		} else if (catalogHasFolderGroups()) {
			state.level = "groups";
			renderGroups();
		} else {
			state.level = "products";
			state.groupPath = "";
			renderProducts();
		}
	}

	searchInput.addEventListener("input", () => {
		state.searchQuery = searchInput.value.trim();
		render();
	});

	const onKeyDown = (ev) => {
		if (ev.key === "Escape") {
			closeCatalogModal();
		}
	};
	document.addEventListener("keydown", onKeyDown);

	catalogModalState = { overlay, onKeyDown };
	loadCatalogIndex().then(() => {
		if (!catalogModalState) {
			return;
		}
		render();
		searchInput.focus();
	});
}

function hideWidget(widget, { hideLinked = true } = {}) {
	if (!widget) {
		return;
	}
	// Keep widget.type unchanged so widgets_values / API serialization still work.
	widget.origComputeSize = widget.origComputeSize ?? widget.computeSize;
	widget.computeSize = () => [0, -4];
	widget.hidden = true;
	if (widget.element) {
		widget.element.style.display = "none";
	}
	if (widget.inputEl) {
		widget.inputEl.style.display = "none";
	}
	if (hideLinked && widget.linkedWidgets) {
		for (const linked of widget.linkedWidgets) {
			hideWidget(linked);
		}
	}
}

function isSeedControlWidget(widget) {
	return widget?.name === "control_after_generate" || widget?.name?.startsWith("control_after_generate");
}

function findSeedControlWidget(node) {
	const seedWidget = widgetByName(node, "seed");
	if (seedWidget?.linkedWidgets?.length) {
		const linked = seedWidget.linkedWidgets.find((w) => isSeedControlWidget(w));
		if (linked) {
			return linked;
		}
	}
	return node.widgets?.find((w) => isSeedControlWidget(w));
}

function keepWidgetLayoutHidden(widget) {
	if (!widget) {
		return;
	}
	widget.origComputeSize = widget.origComputeSize ?? widget.computeSize;
	widget.computeSize = () => [0, -4];
	widget.hidden = true;
	if (widget.element) {
		widget.element.style.display = "none";
	}
}

function mountSeedControlWidget(node, controlsRow) {
	const controlWidget = findSeedControlWidget(node);
	if (!controlWidget) {
		return null;
	}
	const el = controlWidget.inputEl || controlWidget.element;
	if (!el) {
		keepWidgetLayoutHidden(controlWidget);
		return controlWidget;
	}
	el.classList.add("wc-seed-control");
	const wrap = document.createElement("div");
	wrap.className = "wc-seed-control-wrap";
	wrap.appendChild(el);
	controlsRow.appendChild(wrap);
	el.style.display = "";
	// Remount into custom DOM only — do not restore LiteGraph widget row.
	keepWidgetLayoutHidden(controlWidget);
	return controlWidget;
}

function syncDomLayout(node) {
	const ui = node._wc_ui;
	if (!ui?.root) {
		return;
	}
	let w = node.size?.[0] || DEFAULT_NODE_SIZE[0];
	let h = node.size?.[1] || DEFAULT_NODE_SIZE[1];
	if (w < MIN_NODE_SIZE[0] || h < MIN_NODE_SIZE[1]) {
		w = Math.max(w, MIN_NODE_SIZE[0]);
		h = Math.max(h, MIN_NODE_SIZE[1]);
		if (typeof node.setSize === "function") {
			node.setSize([w, h]);
		} else {
			node.size = [w, h];
		}
	}
	const innerH = Math.max(360, h - LAYOUT_TITLE_CHROME);
	const root = ui.root;
	const slot = ui.domWidget?.element;
	if (slot) {
		slot.classList.add("wc-dom-slot");
		slot.style.boxSizing = "border-box";
	}
	root.style.width = "100%";
	root.style.height = `${innerH}px`;
	root.style.maxWidth = "100%";
}

function scheduleLayoutSync(node) {
	requestAnimationFrame(() => {
		syncDomLayout(node);
		if (node.setDirtyCanvas) {
			node.setDirtyCanvas(true, true);
		} else if (node.graph?.setDirtyCanvas) {
			node.graph.setDirtyCanvas(true, true);
		}
	});
}

function widgetByName(node, name) {
	return node.widgets?.find((w) => w.name === name);
}

function getModeValue(node) {
	if (node._wc_mode_value !== undefined) {
		return node._wc_mode_value;
	}
	const modeWidget = widgetByName(node, "mode");
	const raw = modeWidget?.value;
	if (raw === true) {
		return "populate";
	}
	if (raw === false) {
		return "fixed";
	}
	return raw || "populate";
}

function setWidgetValue(node, name, value, { skipCallback = false } = {}) {
	const w = widgetByName(node, name);
	if (!w) {
		return;
	}
	w.value = value;
	if (w.inputEl && w.inputEl.value !== String(value ?? "")) {
		w.inputEl.value = value ?? "";
	}
	if (!skipCallback && typeof w.callback === "function") {
		w.callback(w.value);
	}
}

function insertAtCursor(textarea, text) {
	const start = textarea.selectionStart ?? textarea.value.length;
	const end = textarea.selectionEnd ?? start;
	const before = textarea.value.slice(0, start);
	const after = textarea.value.slice(end);
	let insert = text;
	if (before && !/[\s,]$/.test(before)) {
		insert = ", " + insert;
	}
	textarea.value = before + insert + after;
	const caret = before.length + insert.length;
	textarea.focus();
	textarea.setSelectionRange(caret, caret);
	textarea.dispatchEvent(new Event("input", { bubbles: true }));
}

function isNonEmpty(value) {
	return String(value ?? "").trim().length > 0;
}

function defaultOverrideTitle(key) {
	return (
		SCENE_FIELD_TOOLTIPS[key] ||
		ATOM_FIELD_TOOLTIPS[key] ||
		(OVERRIDE_EXAMPLES[key] ? `Example: ${OVERRIDE_EXAMPLES[key]}` : "")
	);
}

function ensureHeightMap(node) {
	node.properties = node.properties || {};
	if (!node.properties.wc_heights || typeof node.properties.wc_heights !== "object") {
		node.properties.wc_heights = {};
	}
	return node.properties.wc_heights;
}

function applyPersistedHeight(el, node, key, fallback) {
	const heights = ensureHeightMap(node);
	const h = Number(heights[key]) || fallback;
	el.style.height = `${Math.max(h, MIN_TEXTAREA_HEIGHT_PX)}px`;
}

function persistHeight(el, node, key) {
	const heights = ensureHeightMap(node);
	const h = Math.round(el.offsetHeight || 0);
	if (h >= MIN_TEXTAREA_HEIGHT_PX) {
		heights[key] = h;
	}
}

function attachHeightPersistence(el, node, key) {
	const save = () => persistHeight(el, node, key);
	el.addEventListener("mouseup", save);
	el.addEventListener("pointerup", save);
	if (typeof ResizeObserver !== "undefined") {
		const ro = new ResizeObserver(() => save());
		ro.observe(el);
		el._wc_ro = ro;
	}
}

async function attachPysssssAutocomplete(textarea) {
	try {
		const mod = await import(
			"../../comfyui-custom-scripts/web/js/common/autocomplete.js"
		);
		if (mod?.TextAreaAutoComplete) {
			new mod.TextAreaAutoComplete(textarea);
		}
	} catch (err) {
		console.warn("[umbrae clause] pysssss autocomplete unavailable", err);
	}
}

function createTextarea({
	className = "wc-textarea",
	placeholder = "",
	readOnly = false,
	disabled = false,
	value = "",
}) {
	const el = document.createElement("textarea");
	el.className = className;
	el.placeholder = placeholder;
	el.readOnly = readOnly;
	el.disabled = disabled;
	el.value = value ?? "";
	el.spellcheck = false;
	return el;
}

function createCollapse(title, { scrollClass = "", grow = false } = {}) {
	const wrap = document.createElement("div");
	wrap.className = "wc-collapse";
	if (grow) {
		wrap.classList.add("wc-collapse--grow");
	}

	const header = document.createElement("button");
	header.type = "button";
	header.className = "wc-collapse-header";
	const chevron = document.createElement("span");
	chevron.className = "wc-collapse-chevron";
	const titleSpan = document.createElement("span");
	titleSpan.className = "wc-collapse-header-title";
	titleSpan.textContent = title;
	const headerActions = document.createElement("div");
	headerActions.className = "wc-header-actions";
	header.append(chevron, titleSpan, headerActions);

	const body = document.createElement("div");
	body.className = "wc-collapse-body";

	const scroll = document.createElement("div");
	scroll.className = "wc-collapse-scroll";
	if (scrollClass) {
		scroll.classList.add(scrollClass);
	}

	header.addEventListener("click", () => {
		wrap.classList.toggle("open");
	});

	body.appendChild(scroll);
	wrap.appendChild(header);
	wrap.appendChild(body);
	return {
		wrap,
		header,
		headerActions,
		body,
		scroll,
		setOpen: (open) => wrap.classList.toggle("open", !!open),
	};
}

function addHeaderButton(container, label, title, onClick) {
	const btn = document.createElement("button");
	btn.type = "button";
	btn.className = "wc-header-btn";
	btn.textContent = label;
	if (title) {
		btn.title = title;
	}
	btn.addEventListener("click", (ev) => {
		ev.stopPropagation();
		onClick();
	});
	container.appendChild(btn);
	return btn;
}

function nodeFeedbackHandler(event) {
	const nodes = app.graph?._nodes_by_id;
	const node = nodes?.[event.detail.node_id];
	if (!node || !node.widgets) {
		return;
	}
	const name = event.detail.widget_name;
	const value = event.detail.value;
	const w = node.widgets.find((widget) => widget.name === name);
	if (w) {
		w.value = value;
		if (w.inputEl) {
			w.inputEl.value = value;
		}
	}
	// Queue feedback updates the bottom populated panel only — never live preview.
	if (name === "populated_text" && node._wc_ui?.populatedEl) {
		const populatedEl = node._wc_ui.populatedEl;
		delete populatedEl.dataset.wcGhost;
		populatedEl.classList.remove("wc-populated-ghost");
		populatedEl.value = value ?? "";
		setWidgetValue(node, "populated_text", value ?? "", { skipCallback: true });
	}
}

api.addEventListener("umbrae-clause-feedback", nodeFeedbackHandler);
loadWildcardsList();
loadCatalogIndex();

function buildWildcardClauseUI(node) {
	ensureStyles();

	for (const w of node.widgets || []) {
		if (w.name === "seed" || isSeedControlWidget(w)) {
			hideWidget(w, { hideLinked: false });
		} else if (HIDDEN_WIDGET_NAMES.has(w.name)) {
			hideWidget(w);
		}
	}

	const root = document.createElement("div");
	root.className = "wc-root";

	const left = document.createElement("div");
	left.className = "wc-col";
	const right = document.createElement("div");
	right.className = "wc-col";

	// --- Browse (Phase 2 catalog modal) ---
	const browseBtn = document.createElement("button");
	browseBtn.type = "button";
	browseBtn.className = "wc-btn-primary";
	browseBtn.textContent = "Browse templates & routers…";
	browseBtn.title = "Visual catalog — products, routers, and templates";
	left.appendChild(browseBtn);

	// --- Starter picker (templates & routers) ---
	const starterPickerWrap = document.createElement("div");
	starterPickerWrap.className = "wc-picker";
	const starterPickerInput = document.createElement("input");
	starterPickerInput.type = "text";
	starterPickerInput.className = "wc-picker-input";
	starterPickerInput.placeholder = "Search templates & routers…";
	starterPickerInput.autocomplete = "off";
	const starterPickerDropdown = document.createElement("div");
	starterPickerDropdown.className = "wc-picker-dropdown";
	starterPickerDropdown.hidden = true;
	starterPickerWrap.appendChild(starterPickerInput);
	starterPickerWrap.appendChild(starterPickerDropdown);
	left.appendChild(starterPickerWrap);

	// --- Full catalog picker ---
	const fullCatalogHint = document.createElement("div");
	fullCatalogHint.className = "wc-picker-hint";
	fullCatalogHint.textContent = "Full catalog (insert at cursor)";
	left.appendChild(fullCatalogHint);

	const pickerWrap = document.createElement("div");
	pickerWrap.className = "wc-picker";
	const pickerInput = document.createElement("input");
	pickerInput.type = "text";
	pickerInput.className = "wc-picker-input";
	pickerInput.placeholder = "Select to add Wildcard";
	pickerInput.autocomplete = "off";
	const pickerDropdown = document.createElement("div");
	pickerDropdown.className = "wc-picker-dropdown";
	pickerDropdown.hidden = true;
	pickerWrap.appendChild(pickerInput);
	pickerWrap.appendChild(pickerDropdown);
	left.appendChild(pickerWrap);

	const reloadWildcardsBtn = document.createElement("button");
	reloadWildcardsBtn.type = "button";
	reloadWildcardsBtn.className = "wc-btn-secondary";
	reloadWildcardsBtn.textContent = "Reload wildcards from disk…";
	reloadWildcardsBtn.title =
		"Re-read every umbrae wildcard root from disk";
	reloadWildcardsBtn.addEventListener("click", async () => {
		const ok = await reloadWildcardsFromDisk({
			onReloading: (loading) => {
				reloadWildcardsBtn.disabled = loading;
				reloadWildcardsBtn.textContent = loading
					? "Reloading wildcards…"
					: "Reload wildcards from disk…";
			},
		});
		if (ok) {
			schedulePreview();
		}
	});
	left.appendChild(reloadWildcardsBtn);

	// --- Template ---
	const templateLabel = document.createElement("div");
	templateLabel.className = "wc-label";
	templateLabel.textContent = "wildcard_text";
	const templateBlock = document.createElement("div");
	templateBlock.className = "wc-template";
	const templateEl = createTextarea({
		placeholder: "Wildcard Prompt (User input)",
		value: widgetByName(node, "wildcard_text")?.value ?? "",
	});
	applyPersistedHeight(templateEl, node, "wildcard_text", DEFAULT_TEXTAREA_HEIGHTS.wildcard_text);
	attachHeightPersistence(templateEl, node, "wildcard_text");
	templateBlock.appendChild(templateLabel);
	templateBlock.appendChild(templateEl);
	left.appendChild(templateBlock);

	attachPysssssAutocomplete(templateEl);

	// --- Mode + seed ---
	const controls = document.createElement("div");
	controls.className = "wc-row";
	const modeLabel = document.createElement("label");
	modeLabel.textContent = "mode ";
	const modeSelect = document.createElement("select");
	modeSelect.className = "wc-select";
	for (const opt of ["populate", "fixed"]) {
		const o = document.createElement("option");
		o.value = opt;
		o.textContent = opt;
		modeSelect.appendChild(o);
	}
	modeSelect.value = getModeValue(node);
	modeLabel.appendChild(modeSelect);

	const seedLabel = document.createElement("label");
	seedLabel.textContent = "seed ";
	const seedInput = document.createElement("input");
	seedInput.type = "number";
	seedInput.className = "wc-input wc-seed";
	seedInput.min = "0";
	seedInput.step = "1";
	seedInput.value = String(widgetByName(node, "seed")?.value ?? 0);
	seedLabel.appendChild(seedInput);
	controls.appendChild(modeLabel);
	controls.appendChild(seedLabel);
	mountSeedControlWidget(node, controls);
	left.appendChild(controls);

	// --- Override groups ---
	const leafCollapse = createCollapse("Scene overrides", {
		scrollClass: "wc-collapse-scroll--scene",
	});
	const atomCollapse = createCollapse("Character atom override", {
		scrollClass: "wc-collapse-scroll--atoms",
		grow: true,
	});
	left.appendChild(leafCollapse.wrap);
	left.appendChild(atomCollapse.wrap);

	const overrideEls = {};
	const overrideFields = {};
	const pinBtns = {};
	const rerollBtns = {};
	const skipBtns = {};
	let lastTargets = {};

	function getOverrideWidgetValue(key) {
		const w = widgetByName(node, key);
		return w?.value ?? "";
	}

	function setSkipState(key, enabled, { schedulePreview = true } = {}) {
		const el = overrideEls[key];
		const field = overrideFields[key];
		const pinBtn = pinBtns[key];
		const rerollBtn = rerollBtns[key];
		const skipBtn = skipBtns[key];
		if (!el || !field || !skipBtn) {
			return;
		}
		if (enabled) {
			el.value = "";
			delete el.dataset.wcGhost;
			el.placeholder = "— skipped —";
			el.title = "This clause is skipped and will not appear in populated text.";
			el.disabled = true;
			field.classList.add("skipped");
			field.classList.remove("wc-has-ghost", "wc-tag-not-found");
			skipBtn.classList.add("active");
			skipBtn.title = "Skipped — click to restore seed default";
			if (pinBtn) {
				pinBtn.disabled = true;
			}
			if (rerollBtn) {
				rerollBtn.disabled = true;
			}
			setWidgetValue(node, key, SKIP_OVERRIDE_SENTINEL, { skipCallback: true });
		} else {
			el.disabled = false;
			field.classList.remove("skipped");
			skipBtn.classList.remove("active");
			skipBtn.title = "Skip this clause (remove from populated text)";
			const widgetVal = getOverrideWidgetValue(key);
			if (isSkipOverride(widgetVal)) {
				setWidgetValue(node, key, "", { skipCallback: true });
			}
			if (!isNonEmpty(el.value)) {
				el.placeholder = "Waiting for preview…";
				el.title = defaultOverrideTitle(key);
			}
		}
		if (schedulePreview) {
			onTemplateOrOverrideEdit();
		}
	}

	function isFieldSkipped(key) {
		return skipBtns[key]?.classList.contains("active") ?? false;
	}

	function addOverrideField(parent, key, { labelText, tooltip } = {}) {
		const field = document.createElement("div");
		field.className = "wc-override-field";
		field.dataset.key = key;
		const labelRow = document.createElement("div");
		labelRow.className = "wc-override-label-row";
		const label = document.createElement("div");
		label.className = "wc-label-muted";
		const displayLabel =
			labelText || ATOM_FIELD_LABELS[key] || key.replace(/_override$/, "");
		label.textContent = displayLabel;
		if (tooltip) {
			label.title = tooltip;
		}
		const labelActions = document.createElement("div");
		labelActions.className = "wc-override-label-actions";
		const skipBtn = document.createElement("button");
		skipBtn.type = "button";
		skipBtn.className = "wc-skip-btn";
		skipBtn.textContent = "Skip";
		skipBtn.title = "Skip this clause (remove from populated text)";
		skipBtn.addEventListener("click", () => {
			setSkipState(key, !isFieldSkipped(key));
		});
		const pinBtn = document.createElement("button");
		pinBtn.type = "button";
		pinBtn.className = "wc-pin-btn";
		pinBtn.textContent = "Pin";
		pinBtn.title = "Pin seed suggestion as override";
		pinBtn.disabled = true;
		pinBtn.addEventListener("click", () => pinGhost(key));
		const rerollBtn = document.createElement("button");
		rerollBtn.type = "button";
		rerollBtn.className = "wc-reroll-btn";
		rerollBtn.textContent = "\u21BB";
		rerollBtn.title = "Regenerate this clause from the wildcard pool";
		rerollBtn.disabled = true;
		rerollBtn.addEventListener("click", () => rerollOverride(key));
		labelActions.appendChild(skipBtn);
		labelActions.appendChild(pinBtn);
		labelActions.appendChild(rerollBtn);
		labelRow.appendChild(label);
		labelRow.appendChild(labelActions);
		const initialWidgetValue = widgetByName(node, key)?.value ?? "";
		const ta = createTextarea({
			placeholder: isSkipOverride(initialWidgetValue)
				? "— skipped —"
				: "Waiting for preview…",
			value: isSkipOverride(initialWidgetValue) ? "" : initialWidgetValue,
			disabled: isSkipOverride(initialWidgetValue),
		});
		ta.title =
			tooltip ||
			SCENE_FIELD_TOOLTIPS[key] ||
			(OVERRIDE_EXAMPLES[key] ? `Example: ${OVERRIDE_EXAMPLES[key]}` : "");
		applyPersistedHeight(ta, node, key, DEFAULT_TEXTAREA_HEIGHTS.override);
		attachHeightPersistence(ta, node, key);
		field.appendChild(labelRow);
		field.appendChild(ta);
		parent.appendChild(field);
		overrideEls[key] = ta;
		overrideFields[key] = field;
		pinBtns[key] = pinBtn;
		rerollBtns[key] = rerollBtn;
		skipBtns[key] = skipBtn;
		if (isSkipOverride(initialWidgetValue)) {
			field.classList.add("skipped");
			skipBtn.classList.add("active");
			skipBtn.title = "Skipped — click to restore seed default";
			pinBtn.disabled = true;
			rerollBtn.disabled = true;
			ta.title = "This clause is skipped and will not appear in populated text.";
		}
	}

	for (const key of LEAF_OVERRIDE_KEYS) {
		addOverrideField(leafCollapse.scroll, key, {
			labelText: SCENE_FIELD_LABELS[key],
			tooltip: SCENE_FIELD_TOOLTIPS[key],
		});
	}

	const wardrobeHint = document.createElement("p");
	wardrobeHint.className = "wc-hint";
	wardrobeHint.hidden = true;
	wardrobeHint.textContent =
		"wardrobe_override is set — jewelry_override is ignored (wardrobe leaf wins).";
	atomCollapse.scroll.appendChild(wardrobeHint);

	for (const subgroup of ATOM_SUBGROUPS) {
		const header = document.createElement("div");
		header.className = "wc-subgroup-title";
		header.textContent = subgroup.title;
		atomCollapse.scroll.appendChild(header);
		for (const key of subgroup.keys) {
			addOverrideField(atomCollapse.scroll, key, {
				labelText: ATOM_FIELD_LABELS[key],
				tooltip: ATOM_FIELD_TOOLTIPS[key],
			});
		}
	}

	const presetSelection = {
		scene: { id: null, source: null },
		character: { id: null, source: null },
	};

	function collectDomainOverrides(domain) {
		const keys = domain === "scene" ? LEAF_OVERRIDE_KEYS : ATOM_OVERRIDE_KEYS;
		const out = {};
		for (const key of keys) {
			if (isFieldSkipped(key)) {
				out[key] = SKIP_OVERRIDE_SENTINEL;
				continue;
			}
			const v = (overrideEls[key]?.value || "").trim();
			if (v) {
				out[key] = v;
			}
		}
		return out;
	}

	function clearDomainOverrides(domain) {
		const keys = domain === "scene" ? LEAF_OVERRIDE_KEYS : ATOM_OVERRIDE_KEYS;
		const any = keys.some((k) => isNonEmpty(overrideEls[k]?.value));
		if (any && !confirm(`Clear all ${domain} overrides?`)) {
			return;
		}
		for (const key of keys) {
			const el = overrideEls[key];
			if (!el) {
				continue;
			}
			setSkipState(key, false, { schedulePreview: false });
			el.value = "";
			delete el.dataset.wcGhost;
			overrideFields[key]?.classList.remove("wc-has-ghost", "wc-tag-not-found");
			if (pinBtns[key]) {
				pinBtns[key].disabled = true;
			}
			if (rerollBtns[key]) {
				rerollBtns[key].disabled = true;
			}
			el.placeholder = "Waiting for preview…";
			el.title = defaultOverrideTitle(key);
		}
		onTemplateOrOverrideEdit();
	}

	async function saveDomainPreset(domain) {
		const overrides = collectDomainOverrides(domain);
		if (!Object.keys(overrides).length) {
			alert(`No non-empty ${domain} overrides to save.`);
			return;
		}
		const name = prompt(`Save ${domain} preset as:`);
		if (!name?.trim()) {
			return;
		}
		const res = await api.fetchApi(`/umbrae/clause/presets/${domain}`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ name: name.trim(), overrides }),
		});
		if (!res.ok) {
			const err = await res.json().catch(() => ({}));
			alert(err.error || "Save failed");
			return;
		}
		await refreshPresetList(domain);
	}

	async function applyPreset(domain, presetId) {
		if (!presetId) {
			return;
		}
		const res = await api.fetchApi(
			`/umbrae/clause/presets/${domain}/${encodeURIComponent(presetId)}`
		);
		if (!res.ok) {
			alert("Load failed");
			return;
		}
		const doc = await res.json();
		const keys = domain === "scene" ? LEAF_OVERRIDE_KEYS : ATOM_OVERRIDE_KEYS;
		for (const key of keys) {
			if (!(key in (doc.overrides || {}))) {
				continue;
			}
			const el = overrideEls[key];
			if (!el) {
				continue;
			}
			const presetValue = doc.overrides[key];
			if (isSkipOverride(presetValue)) {
				setSkipState(key, true, { schedulePreview: false });
				continue;
			}
			setSkipState(key, false, { schedulePreview: false });
			el.value = presetValue;
			delete el.dataset.wcGhost;
			overrideFields[key]?.classList.remove("wc-has-ghost", "wc-tag-not-found");
			if (pinBtns[key]) {
				pinBtns[key].disabled = true;
			}
			if (rerollBtns[key]) {
				rerollBtns[key].disabled = true;
			}
			el.placeholder = "Waiting for preview…";
			el.title = defaultOverrideTitle(key);
		}
		onTemplateOrOverrideEdit();
	}

	function renderPresetList(domain, listEl, items) {
		listEl.replaceChildren();
		for (const item of items) {
			const row = document.createElement("div");
			row.className =
				"wc-preset-item" + (item.source === "pack" ? " pack" : "");
			row.textContent = item.name;
			row.title = item.id;
			row.dataset.id = item.id;
			row.dataset.source = item.source || "pack";
			if (presetSelection[domain].id === item.id) {
				row.classList.add("selected");
			}
			row.addEventListener("click", () => {
				listEl
					.querySelectorAll(".wc-preset-item")
					.forEach((n) => n.classList.remove("selected"));
				row.classList.add("selected");
				presetSelection[domain].id = item.id;
				presetSelection[domain].source = item.source;
				if (presetDeleteBtns[domain]) {
					presetDeleteBtns[domain].disabled = item.source !== "user";
				}
			});
			listEl.appendChild(row);
		}
	}

	async function refreshPresetList(domain) {
		const listEl = presetLists[domain];
		if (!listEl) {
			return;
		}
		try {
			const res = await api.fetchApi(
				`/umbrae/clause/presets?domain=${encodeURIComponent(domain)}`
			);
			const data = await res.json();
			const items = Array.isArray(data?.presets) ? data.presets : [];
			renderPresetList(domain, listEl, items);
			const sel = presetSelection[domain];
			if (
				sel.id &&
				!items.some((item) => item.id === sel.id)
			) {
				sel.id = null;
				sel.source = null;
				if (presetDeleteBtns[domain]) {
					presetDeleteBtns[domain].disabled = true;
				}
			}
		} catch (err) {
			console.warn("[umbrae clause] preset list failed", err);
		}
	}

	async function deleteSelectedPreset(domain) {
		const sel = presetSelection[domain];
		if (!sel.id || sel.source !== "user") {
			return;
		}
		if (!confirm("Delete this preset file?")) {
			return;
		}
		const res = await api.fetchApi(
			`/umbrae/clause/presets/${domain}/${encodeURIComponent(sel.id)}`,
			{ method: "DELETE" }
		);
		if (!res.ok) {
			alert("Delete failed");
			return;
		}
		sel.id = null;
		sel.source = null;
		if (presetDeleteBtns[domain]) {
			presetDeleteBtns[domain].disabled = true;
		}
		await refreshPresetList(domain);
	}

	addHeaderButton(
		leafCollapse.headerActions,
		"Save",
		"Save non-empty scene overrides as a preset",
		() => saveDomainPreset("scene")
	);
	addHeaderButton(
		leafCollapse.headerActions,
		"Clear",
		"Clear all scene override fields",
		() => clearDomainOverrides("scene")
	);
	addHeaderButton(
		atomCollapse.headerActions,
		"Save",
		"Save non-empty character overrides as a preset",
		() => saveDomainPreset("character")
	);
	addHeaderButton(
		atomCollapse.headerActions,
		"Clear",
		"Clear all character override fields",
		() => clearDomainOverrides("character")
	);

	const presetsCol = document.createElement("div");
	presetsCol.className = "wc-presets-col";
	node.properties = node.properties || {};
	const presetsOpen = node.properties.wc_presets_panel_open !== false;
	if (!presetsOpen) {
		presetsCol.classList.add("collapsed");
	}
	const presetsToggle = document.createElement("button");
	presetsToggle.type = "button";
	presetsToggle.className = "wc-presets-toggle wc-pin-btn";
	presetsToggle.textContent = presetsOpen ? "◀" : "▶";
	presetsToggle.title = "Toggle presets panel";
	const presetsBody = document.createElement("div");
	presetsBody.className = "wc-presets-body";
	if (!presetsOpen) {
		presetsBody.style.display = "none";
	}
	const presetsTitle = document.createElement("div");
	presetsTitle.className = "wc-label";
	presetsTitle.textContent = "PRESETS";
	presetsBody.appendChild(presetsTitle);

	const presetLists = {};
	const presetDeleteBtns = {};

	function buildPresetSection(title, domain) {
		const sec = document.createElement("div");
		sec.className = "wc-preset-section";
		const header = document.createElement("div");
		header.className = "wc-preset-header";
		const lab = document.createElement("div");
		lab.className = "wc-label-muted";
		lab.textContent = title;
		const list = document.createElement("div");
		list.className = "wc-preset-list";
		presetLists[domain] = list;
		const actions = document.createElement("div");
		actions.className = "wc-preset-actions";
		const loadBtn = document.createElement("button");
		loadBtn.type = "button";
		loadBtn.className = "wc-pin-btn";
		loadBtn.textContent = "Load";
		loadBtn.addEventListener("click", () =>
			applyPreset(domain, presetSelection[domain].id)
		);
		const delBtn = document.createElement("button");
		delBtn.type = "button";
		delBtn.className = "wc-pin-btn";
		delBtn.textContent = "Delete";
		delBtn.disabled = true;
		delBtn.addEventListener("click", () => deleteSelectedPreset(domain));
		presetDeleteBtns[domain] = delBtn;
		actions.append(loadBtn, delBtn);
		header.append(lab, actions);
		sec.append(header, list);
		return sec;
	}

	presetsBody.append(
		buildPresetSection("Scene", "scene"),
		buildPresetSection("Character", "character")
	);
	presetsCol.append(presetsToggle, presetsBody);
	presetsToggle.addEventListener("click", () => {
		const collapsed = presetsCol.classList.toggle("collapsed");
		presetsBody.style.display = collapsed ? "none" : "";
		presetsToggle.textContent = collapsed ? "▶" : "◀";
		node.properties.wc_presets_panel_open = !collapsed;
		if (!collapsed) {
			refreshPresetList("scene");
			refreshPresetList("character");
		}
	});

	root.appendChild(presetsCol);
	root.appendChild(left);
	root.appendChild(right);
	refreshPresetList("scene");
	refreshPresetList("character");

	// --- Right: live preview ---
	const previewGrow = document.createElement("div");
	previewGrow.className = "wc-grow";
	const previewLabel = document.createElement("div");
	previewLabel.className = "wc-label";
	previewLabel.textContent = "LIVE PREVIEW";
	const previewEl = createTextarea({
		placeholder: "Structural preview (caption tags stay as __key__)",
		readOnly: true,
		value: "",
	});
	applyPersistedHeight(previewEl, node, "live_preview", DEFAULT_TEXTAREA_HEIGHTS.live_preview);
	attachHeightPersistence(previewEl, node, "live_preview");
	previewGrow.appendChild(previewLabel);
	previewGrow.appendChild(previewEl);
	right.appendChild(previewGrow);

	// --- Right: populated (queue) ---
	const populatedGrow = document.createElement("div");
	populatedGrow.className = "wc-grow";
	const populatedLabel = document.createElement("div");
	populatedLabel.className = "wc-label";
	populatedLabel.textContent = "populated_text (live in populate mode)";
	const populatedEl = createTextarea({
		placeholder: "Full expand for current seed (not saved until queue)",
		value: widgetByName(node, "populated_text")?.value ?? "",
		disabled: getModeValue(node) === "populate",
	});
	applyPersistedHeight(populatedEl, node, "populated_text", DEFAULT_TEXTAREA_HEIGHTS.populated_text);
	attachHeightPersistence(populatedEl, node, "populated_text");
	populatedGrow.appendChild(populatedLabel);
	populatedGrow.appendChild(populatedEl);
	right.appendChild(populatedGrow);

	let previewTimer = null;
	let previewSeq = 0;
	let syncingFromWidgets = false;

	function applyModeToPopulated(mode) {
		const locked = mode === "populate";
		populatedEl.disabled = locked;
	}

	function applyPrecedenceDimming() {
		const wardrobeOn = isNonEmpty(overrideEls.wardrobe_override?.value);
		wardrobeHint.hidden = !wardrobeOn;
		const jewelryField = overrideFields.jewelry_override;
		if (jewelryField) {
			jewelryField.classList.toggle("dimmed", wardrobeOn);
			if (overrideEls.jewelry_override) {
				overrideEls.jewelry_override.disabled = wardrobeOn;
			}
		}
	}

	function autoExpandOverrides() {
		const leafFilled = LEAF_OVERRIDE_KEYS.some(
			(k) => isFieldSkipped(k) || isNonEmpty(overrideEls[k]?.value)
		);
		const atomFilled = ATOM_OVERRIDE_KEYS.some(
			(k) => isFieldSkipped(k) || isNonEmpty(overrideEls[k]?.value)
		);
		if (leafFilled) {
			leafCollapse.setOpen(true);
		}
		if (atomFilled) {
			atomCollapse.setOpen(true);
		}
	}

	function applyOverrideReport(leaves, matches, targets) {
		if (targets && typeof targets === "object") {
			lastTargets = { ...targets };
		}
		for (const key of ALL_OVERRIDE_KEYS) {
			const el = overrideEls[key];
			const field = overrideFields[key];
			const pinBtn = pinBtns[key];
			const rerollBtn = rerollBtns[key];
			if (!el) {
				continue;
			}

			if (isFieldSkipped(key)) {
				if (rerollBtn) {
					rerollBtn.disabled = true;
				}
				continue;
			}

			field?.classList.remove("wc-has-ghost", "wc-tag-not-found");
			delete el.dataset.wcGhost;

			if (isNonEmpty(el.value)) {
				el.placeholder = "";
				el.title = defaultOverrideTitle(key);
				if (pinBtn) {
					pinBtn.disabled = true;
				}
				updateRerollBtnState(key);
				continue;
			}

			const ghost = leaves?.[key] ? String(leaves[key]) : "";
			if (ghost) {
				el.placeholder = ghost;
				el.title = ghost;
				el.dataset.wcGhost = "1";
				field?.classList.add("wc-has-ghost");
				if (pinBtn) {
					pinBtn.disabled = false;
				}
				updateRerollBtnState(key);
				continue;
			}

			if (matches?.[key] === false) {
				el.placeholder = "TAG NOT FOUND";
				el.title =
					"No matching wildcard target was visited in the current seed expansion.";
				field?.classList.add("wc-tag-not-found");
			} else {
				el.placeholder = "Preview unavailable";
				el.title = defaultOverrideTitle(key);
			}
			if (pinBtn) {
				pinBtn.disabled = true;
			}
			if (rerollBtn) {
				rerollBtn.disabled = true;
			}
		}
	}

	function canRerollOverride(key) {
		if (isFieldSkipped(key)) {
			return false;
		}
		const field = overrideFields[key];
		if (field?.classList.contains("dimmed")) {
			return false;
		}
		const el = overrideEls[key];
		if (!el) {
			return false;
		}
		if (field?.classList.contains("wc-tag-not-found")) {
			return false;
		}
		if (el.placeholder === "Preview unavailable") {
			return false;
		}
		const hasGhost = el.dataset.wcGhost === "1" || field?.classList.contains("wc-has-ghost");
		const isPinned = isNonEmpty(el.value);
		if (hasGhost) {
			return true;
		}
		return isPinned && Boolean(lastTargets[key]);
	}

	function updateRerollBtnState(key) {
		const rerollBtn = rerollBtns[key];
		if (!rerollBtn) {
			return;
		}
		rerollBtn.disabled = !canRerollOverride(key);
	}

	function pinGhost(key) {
		const el = overrideEls[key];
		if (isFieldSkipped(key)) {
			return;
		}
		if (!el || !isNonEmpty(el.placeholder) || isNonEmpty(el.value)) {
			return;
		}
		if (el.dataset.wcGhost !== "1") {
			return;
		}
		el.value = el.placeholder;
		delete el.dataset.wcGhost;
		overrideFields[key]?.classList.remove("wc-has-ghost", "wc-tag-not-found");
		if (pinBtns[key]) {
			pinBtns[key].disabled = true;
		}
		updateRerollBtnState(key);
		el.placeholder = "Waiting for preview…";
		el.title = defaultOverrideTitle(key);
		onTemplateOrOverrideEdit();
	}

	async function rerollOverride(key) {
		const el = overrideEls[key];
		if (!el || !canRerollOverride(key)) {
			return;
		}
		syncDomToWidgets();
		const body = {
			text: templateEl.value ?? "",
			seed: Number(seedInput.value) || 0,
			key,
		};
		for (const k of ALL_OVERRIDE_KEYS) {
			body[k] = isFieldSkipped(k)
				? SKIP_OVERRIDE_SENTINEL
				: (overrideEls[k]?.value ?? "");
		}
		try {
			const res = await api.fetchApi("/umbrae/clause/reroll", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(body),
			});
			if (!res.ok) {
				const err = await res.json().catch(() => ({}));
				throw new Error(err.error || `reroll HTTP ${res.status}`);
			}
			const data = await res.json();
			if (!data?.value) {
				return;
			}
			el.value = String(data.value);
			delete el.dataset.wcGhost;
			overrideFields[key]?.classList.remove("wc-has-ghost", "wc-tag-not-found");
			if (pinBtns[key]) {
				pinBtns[key].disabled = true;
			}
			updateRerollBtnState(key);
			el.placeholder = "Waiting for preview…";
			el.title = defaultOverrideTitle(key);
			onTemplateOrOverrideEdit();
		} catch (err) {
			console.warn("[umbrae clause] reroll failed", err);
		}
	}

	function applyPopulatedGhost(populated) {
		if (getModeValue(node) !== "populate") {
			return;
		}
		if (typeof populated !== "string") {
			return;
		}
		populatedEl.value = populated;
		populatedEl.dataset.wcGhost = "1";
		populatedEl.classList.add("wc-populated-ghost");
	}

	function syncDomToWidgets() {
		if (syncingFromWidgets) {
			return;
		}
		setWidgetValue(node, "wildcard_text", templateEl.value, { skipCallback: true });
		if (!populatedEl.dataset.wcGhost) {
			setWidgetValue(node, "populated_text", populatedEl.value, { skipCallback: true });
		}
		setWidgetValue(node, "seed", Number(seedInput.value) || 0, { skipCallback: true });
		const mode = modeSelect.value === "fixed" ? "fixed" : "populate";
		node._wc_mode_value = mode;
		const modeWidget = widgetByName(node, "mode");
		if (modeWidget) {
			// Write through our setter when present; else assign raw.
			modeWidget.value = mode;
		}
		for (const key of ALL_OVERRIDE_KEYS) {
			if (isFieldSkipped(key)) {
				setWidgetValue(node, key, SKIP_OVERRIDE_SENTINEL, { skipCallback: true });
			} else {
				setWidgetValue(node, key, overrideEls[key]?.value ?? "", { skipCallback: true });
			}
		}
		applyModeToPopulated(mode);
		applyPrecedenceDimming();
		for (const key of ALL_OVERRIDE_KEYS) {
			updateRerollBtnState(key);
		}
	}

	function syncFromWidgets() {
		syncingFromWidgets = true;
		try {
			templateEl.value = widgetByName(node, "wildcard_text")?.value ?? "";
			populatedEl.value = widgetByName(node, "populated_text")?.value ?? "";
			delete populatedEl.dataset.wcGhost;
			populatedEl.classList.remove("wc-populated-ghost");
			seedInput.value = String(widgetByName(node, "seed")?.value ?? 0);
			const mode = getModeValue(node);
			modeSelect.value = mode === "fixed" ? "fixed" : "populate";
			for (const key of ALL_OVERRIDE_KEYS) {
				if (overrideEls[key]) {
					const widgetVal = widgetByName(node, key)?.value ?? "";
					if (isSkipOverride(widgetVal)) {
						setSkipState(key, true, { schedulePreview: false });
					} else {
						setSkipState(key, false, { schedulePreview: false });
						overrideEls[key].value = widgetVal;
						delete overrideEls[key].dataset.wcGhost;
						overrideFields[key]?.classList.remove("wc-has-ghost", "wc-tag-not-found");
						if (pinBtns[key]) {
							pinBtns[key].disabled = true;
						}
						if (!isNonEmpty(overrideEls[key].value)) {
							overrideEls[key].placeholder = "Waiting for preview…";
							overrideEls[key].title = defaultOverrideTitle(key);
						}
					}
				}
			}
			applyModeToPopulated(mode);
			applyPrecedenceDimming();
			autoExpandOverrides();
		} finally {
			syncingFromWidgets = false;
		}
		schedulePreview();
	}

	async function runPreview() {
		const seq = ++previewSeq;
		syncDomToWidgets();
		const body = {
			text: templateEl.value ?? "",
			seed: Number(seedInput.value) || 0,
		};
		for (const key of ALL_OVERRIDE_KEYS) {
			body[key] = isFieldSkipped(key)
				? SKIP_OVERRIDE_SENTINEL
				: (overrideEls[key]?.value ?? "");
		}
		try {
			const res = await api.fetchApi("/umbrae/clause/preview", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify(body),
			});
			if (!res.ok) {
				throw new Error(`preview HTTP ${res.status}`);
			}
			const data = await res.json();
			if (seq !== previewSeq) {
				return;
			}
			previewEl.value = data?.text ?? "";
			applyOverrideReport(data?.leaves, data?.matches, data?.targets);
			applyPopulatedGhost(data?.populated);
		} catch (err) {
			if (seq !== previewSeq) {
				return;
			}
			console.warn("[umbrae clause] preview failed", err);
			for (const key of ALL_OVERRIDE_KEYS) {
				const el = overrideEls[key];
				if (!el || isNonEmpty(el.value)) {
					continue;
				}
				el.placeholder = "Preview unavailable";
				overrideFields[key]?.classList.remove("wc-has-ghost", "wc-tag-not-found");
				delete el.dataset.wcGhost;
				if (pinBtns[key]) {
					pinBtns[key].disabled = true;
				}
				if (rerollBtns[key]) {
					rerollBtns[key].disabled = true;
				}
			}
		}
	}

	function schedulePreview() {
		clearTimeout(previewTimer);
		previewTimer = setTimeout(runPreview, PREVIEW_DEBOUNCE_MS);
	}

	const seedWidget = widgetByName(node, "seed");
	if (seedWidget) {
		const origSeedCallback = seedWidget.callback;
		seedWidget.callback = function (value, ...args) {
			const result = origSeedCallback?.apply(this, [value, ...args]);
			if (!syncingFromWidgets) {
				seedInput.value = String(value ?? 0);
				schedulePreview();
			}
			return result;
		};
	}

	function onTemplateOrOverrideEdit() {
		syncDomToWidgets();
		autoExpandOverrides();
		schedulePreview();
	}

	templateEl.addEventListener("input", onTemplateOrOverrideEdit);
	seedInput.addEventListener("input", onTemplateOrOverrideEdit);
	seedInput.addEventListener("change", onTemplateOrOverrideEdit);
	modeSelect.addEventListener("change", () => {
		syncDomToWidgets();
		if (getModeValue(node) === "fixed") {
			delete populatedEl.dataset.wcGhost;
			populatedEl.classList.remove("wc-populated-ghost");
		} else {
			schedulePreview();
		}
	});
	populatedEl.addEventListener("input", () => {
		delete populatedEl.dataset.wcGhost;
		populatedEl.classList.remove("wc-populated-ghost");
		if (getModeValue(node) === "fixed") {
			setWidgetValue(node, "populated_text", populatedEl.value, { skipCallback: true });
		}
	});
	for (const key of ALL_OVERRIDE_KEYS) {
		overrideEls[key]?.addEventListener("input", () => {
			if (isFieldSkipped(key)) {
				setSkipState(key, false, { schedulePreview: false });
			}
			onTemplateOrOverrideEdit();
		});
	}

	function applyStarterTag(tag) {
		if (!tag) {
			return;
		}
		templateEl.value = tag;
		setWidgetValue(node, "wildcard_text", tag, { skipCallback: true });
		autoExpandOverrides();
		schedulePreview();
	}

	browseBtn.addEventListener("click", async () => {
		await loadCatalogIndex();
		openCatalogModal(applyStarterTag);
	});

	// --- Starter picker behavior ---
	let starterActiveIndex = -1;

	function renderStarterDropdown(query) {
		const items = catalogSearchEntries(query);
		starterPickerDropdown.innerHTML = "";
		starterActiveIndex = -1;
		if (!items.length) {
			starterPickerDropdown.hidden = true;
			return;
		}
		for (let i = 0; i < items.length; i++) {
			const entry = items[i];
			const item = document.createElement("div");
			item.className = "wc-picker-item";
			const labelLine = document.createElement("div");
			labelLine.textContent = entry.label;
			const metaLine = document.createElement("div");
			metaLine.className = "wc-picker-item-meta";
			metaLine.textContent = `${entry.breadcrumb || entry.productLabel} · ${entry.kind}`;
			item.appendChild(labelLine);
			item.appendChild(metaLine);
			item.dataset.value = entry.tag;
			item.addEventListener("mousedown", (ev) => {
				ev.preventDefault();
				applyStarterTag(entry.tag);
				starterPickerInput.value = "";
				starterPickerDropdown.hidden = true;
				starterPickerDropdown.innerHTML = "";
			});
			starterPickerDropdown.appendChild(item);
		}
		starterPickerDropdown.hidden = false;
	}

	function highlightStarterPicker(index) {
		const kids = [...starterPickerDropdown.children];
		starterActiveIndex = index;
		kids.forEach((el, i) => el.classList.toggle("active", i === index));
		kids[index]?.scrollIntoView({ block: "nearest" });
	}

	function selectStarter(tag) {
		applyStarterTag(tag);
		starterPickerInput.value = "";
		starterPickerDropdown.hidden = true;
		starterPickerDropdown.innerHTML = "";
	}

	starterPickerInput.addEventListener("focus", async () => {
		await loadCatalogIndex();
		renderStarterDropdown(starterPickerInput.value);
	});
	starterPickerInput.addEventListener("input", async () => {
		await loadCatalogIndex();
		renderStarterDropdown(starterPickerInput.value);
	});
	starterPickerInput.addEventListener("keydown", (ev) => {
		const kids = [...starterPickerDropdown.children];
		if (ev.key === "ArrowDown" && kids.length) {
			ev.preventDefault();
			highlightStarterPicker(Math.min(kids.length - 1, starterActiveIndex + 1));
		} else if (ev.key === "ArrowUp" && kids.length) {
			ev.preventDefault();
			highlightStarterPicker(Math.max(0, starterActiveIndex - 1));
		} else if (ev.key === "Enter") {
			const chosen =
				(starterActiveIndex >= 0 && kids[starterActiveIndex]?.dataset.value) ||
				kids[0]?.dataset.value;
			if (chosen && !starterPickerDropdown.hidden) {
				ev.preventDefault();
				selectStarter(chosen);
			}
		} else if (ev.key === "Escape") {
			starterPickerDropdown.hidden = true;
		}
	});
	starterPickerInput.addEventListener("blur", () => {
		setTimeout(() => {
			starterPickerDropdown.hidden = true;
		}, 150);
	});

	// --- Full catalog picker behavior ---
	let activeIndex = -1;

	function filteredWildcards(query) {
		const q = String(query || "").trim().toLowerCase();
		const list = wildcardsList;
		if (!q) {
			return list.slice(0, 80);
		}
		const out = [];
		for (const tag of list) {
			if (String(tag).toLowerCase().includes(q)) {
				out.push(tag);
				if (out.length >= 80) break;
			}
		}
		return out;
	}

	function renderPickerDropdown(query) {
		const items = filteredWildcards(query);
		pickerDropdown.innerHTML = "";
		activeIndex = -1;
		if (!items.length) {
			pickerDropdown.hidden = true;
			return;
		}
		for (let i = 0; i < items.length; i++) {
			const item = document.createElement("div");
			item.className = "wc-picker-item";
			item.textContent = items[i];
			item.dataset.value = items[i];
			item.addEventListener("mousedown", (ev) => {
				ev.preventDefault();
				selectWildcard(items[i]);
			});
			pickerDropdown.appendChild(item);
		}
		pickerDropdown.hidden = false;
	}

	function highlightPicker(index) {
		const kids = [...pickerDropdown.children];
		activeIndex = index;
		kids.forEach((el, i) => el.classList.toggle("active", i === index));
		kids[index]?.scrollIntoView({ block: "nearest" });
	}

	function selectWildcard(tag) {
		if (!tag) return;
		// List already includes __tag__; insert as-is.
		insertAtCursor(templateEl, tag);
		pickerInput.value = "";
		pickerDropdown.hidden = true;
		pickerDropdown.innerHTML = "";
		onTemplateOrOverrideEdit();
	}

	pickerInput.addEventListener("focus", async () => {
		await loadWildcardsList();
		renderPickerDropdown(pickerInput.value);
	});
	pickerInput.addEventListener("input", async () => {
		await loadWildcardsList();
		renderPickerDropdown(pickerInput.value);
	});
	pickerInput.addEventListener("keydown", (ev) => {
		const kids = [...pickerDropdown.children];
		if (ev.key === "ArrowDown" && kids.length) {
			ev.preventDefault();
			highlightPicker(Math.min(kids.length - 1, activeIndex + 1));
		} else if (ev.key === "ArrowUp" && kids.length) {
			ev.preventDefault();
			highlightPicker(Math.max(0, activeIndex - 1));
		} else if (ev.key === "Enter") {
			const chosen =
				(activeIndex >= 0 && kids[activeIndex]?.dataset.value) ||
				kids[0]?.dataset.value;
			if (chosen && !pickerDropdown.hidden) {
				ev.preventDefault();
				selectWildcard(chosen);
			}
		} else if (ev.key === "Escape") {
			pickerDropdown.hidden = true;
		}
	});
	pickerInput.addEventListener("blur", () => {
		setTimeout(() => {
			pickerDropdown.hidden = true;
		}, 150);
	});

	// Mode widget getter/setter — preserve populate lock on bottom box.
	const modeWidget = widgetByName(node, "mode");
	const populatedWidget = widgetByName(node, "populated_text");
	if (modeWidget) {
		Object.defineProperty(modeWidget, "value", {
			configurable: true,
			set: (value) => {
				if (value === true) {
					node._wc_mode_value = "populate";
				} else if (value === false) {
					node._wc_mode_value = "fixed";
				} else {
					node._wc_mode_value = value;
				}
				const mode = node._wc_mode_value === "fixed" ? "fixed" : "populate";
				if (modeSelect.value !== mode) {
					modeSelect.value = mode;
				}
				applyModeToPopulated(mode);
				if (populatedWidget?.inputEl) {
					populatedWidget.inputEl.disabled = mode === "populate";
				}
			},
			get: () => {
				if (node._wc_mode_value !== undefined) {
					return node._wc_mode_value;
				}
				return "populate";
			},
		});
		// Re-apply current value through setter for initial lock state.
		modeWidget.value = modeSelect.value;
	}

	const domWidget = node.addDOMWidget("wc_ui", "div", root, {
		serialize: false,
		getValue() {
			return null;
		},
		setValue() {},
		computeSize(width) {
			const w = width ?? node.size?.[0] ?? DEFAULT_NODE_SIZE[0];
			const h = Math.max(node.size?.[1] ?? DEFAULT_NODE_SIZE[1], MIN_NODE_SIZE[1]) - 40;
			return [w, h];
		},
	});
	installDomWidgetWidthGuard(domWidget);

	node._wc_ui = {
		root,
		templateEl,
		previewEl,
		populatedEl,
		overrideEls,
		presetsCol,
		refreshPresets: () => {
			refreshPresetList("scene");
			refreshPresetList("character");
		},
		syncFromWidgets,
		syncDomToWidgets,
		schedulePreview,
		syncDomLayout: () => syncDomLayout(node),
		domWidget,
	};

	if (!node.size || node.size[0] < MIN_NODE_SIZE[0] || node.size[1] < MIN_NODE_SIZE[1]) {
		if (typeof node.setSize === "function") {
			node.setSize([...DEFAULT_NODE_SIZE]);
		} else {
			node.size = [...DEFAULT_NODE_SIZE];
		}
	}

	syncDomLayout(node);
	syncFromWidgets();
	scheduleLayoutSync(node);
	return root;
}

app.registerExtension({
	name: "umbrae.WildcardClause",
	async beforeRegisterNodeDef(nodeType, nodeData) {
		if (nodeData.name !== "UmbraeWildcardClauseExpander") {
			return;
		}

		const onNodeCreated = nodeType.prototype.onNodeCreated;
		nodeType.prototype.onNodeCreated = function () {
			const result = onNodeCreated?.apply(this, arguments);

			// Stock placeholders still useful if someone unhides widgets.
			const wildcard = widgetByName(this, "wildcard_text");
			const populated = widgetByName(this, "populated_text");
			if (wildcard?.inputEl) {
				wildcard.inputEl.placeholder = "Wildcard Prompt (User input)";
			}
			if (populated?.inputEl) {
				populated.inputEl.placeholder =
					"Populated Prompt (Will be generated automatically)";
				populated.inputEl.disabled = true;
			}
			for (const [name, example] of Object.entries(OVERRIDE_EXAMPLES)) {
				const w = widgetByName(this, name);
				if (w?.inputEl) {
					w.inputEl.placeholder = "";
					w.inputEl.title = `Example: ${example}`;
				}
			}

			buildWildcardClauseUI(this);
			scheduleLayoutSync(this);
			return result;
		};

		const onConfigure = nodeType.prototype.onConfigure;
		nodeType.prototype.onConfigure = function (info) {
			const result = onConfigure?.apply(this, arguments);
			queueMicrotask(() => {
				installDomWidgetWidthGuard(this._wc_ui?.domWidget);
				this._wc_ui?.syncFromWidgets?.();
				scheduleLayoutSync(this);
			});
			return result;
		};

		const onResize = nodeType.prototype.onResize;
		nodeType.prototype.onResize = function (size) {
			const result = onResize?.apply(this, arguments);
			if (Array.isArray(size) && size.length >= 2) {
				size[0] = Math.max(size[0], MIN_NODE_SIZE[0]);
				size[1] = Math.max(size[1], MIN_NODE_SIZE[1]);
			}
			syncDomLayout(this);
			return result;
		};

		const onSerialize = nodeType.prototype.onSerialize;
		nodeType.prototype.onSerialize = function (info) {
			this._wc_ui?.syncDomToWidgets?.();
			return onSerialize?.apply(this, arguments);
		};
	},
});
