import { app } from "../../scripts/app.js";

const MARKER_TYPE = "UmbraeFrameMarker";
const CTRL_TYPE   = "UmbraeFrameToggleController";
const STYLE_ID    = "umbrae-frame-toggle-styles";

// ---------------------------------------------------------------------------
// CSS
// ---------------------------------------------------------------------------

function ensureStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const s = document.createElement("style");
    s.id = STYLE_ID;
    s.textContent = `
        .uft-header {
            color: #888;
            font-size: 10px;
            font-family: sans-serif;
            text-transform: uppercase;
            letter-spacing: .06em;
            padding-bottom: 4px;
            margin-bottom: 3px;
            border-bottom: 1px solid #444;
        }
        .uft-empty {
            color: #666;
            font-size: 11px;
            font-family: sans-serif;
            padding: 4px 2px;
        }
        .uft-row {
            display: flex;
            align-items: center;
            gap: 7px;
            padding: 4px 0;
            border-bottom: 1px solid #2a2a2a;
            font-family: sans-serif;
            font-size: 12px;
        }
        .uft-row:last-child { border-bottom: none; }
        .uft-switch {
            position: relative;
            display: inline-block;
            width: 34px;
            height: 18px;
            flex-shrink: 0;
        }
        .uft-switch input {
            opacity: 0;
            width: 0;
            height: 0;
            position: absolute;
        }
        .uft-slider {
            position: absolute;
            cursor: pointer;
            inset: 0;
            background: #555;
            border-radius: 18px;
            transition: background .2s;
        }
        .uft-slider::before {
            content: '';
            position: absolute;
            height: 14px;
            width: 14px;
            left: 2px;
            bottom: 2px;
            background: #fff;
            border-radius: 50%;
            transition: transform .2s;
        }
        input:checked + .uft-slider           { background: #4a9; }
        input:checked + .uft-slider::before   { transform: translateX(16px); }
        .uft-name {
            flex: 1;
            color: #ccc;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            cursor: default;
        }
        .uft-name.muted { color: #666; text-decoration: line-through; }
        .uft-nav {
            background: #2a2a2a;
            border: 1px solid #555;
            color: #8cf;
            cursor: pointer;
            padding: 2px 7px;
            border-radius: 3px;
            font-size: 13px;
            flex-shrink: 0;
            line-height: 1;
        }
        .uft-nav:hover { background: #3a3a3a; border-color: #8cf; }
        .uft-count {
            background: #2a2a2a;
            border: 1px solid #555;
            color: #888;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 11px;
            flex-shrink: 0;
            font-family: sans-serif;
            line-height: 1;
        }
    `;
    document.head.appendChild(s);
}

// ---------------------------------------------------------------------------
// Recursive marker discovery
// ---------------------------------------------------------------------------

/**
 * Walks the graph and all subgraph nodes recursively, collecting every
 * UmbraeFrameMarker. Returns [{marker, graph}] so callers always know
 * which graph context the marker lives in — needed for correct group
 * detection and node toggling inside subgraphs.
 *
 * Tries the known LiteGraph subgraph property (node.subgraph) plus common
 * variant names in case a custom implementation uses a different key.
 */
function findAllMarkers(graph, depth = 0) {
    if (!graph || depth > 20) return [];
    const results = [];

    for (const node of (graph._nodes || [])) {
        if (node.type === MARKER_TYPE) {
            results.push({ marker: node, graph });
        }

        // Traverse into subgraph nodes
        const inner = node.subgraph
            || node.inner_graph
            || (typeof node.getInnerGraph === "function" ? node.getInnerGraph() : null);

        if (inner?._nodes) {
            results.push(...findAllMarkers(inner, depth + 1));
        }
    }

    return results;
}

// ---------------------------------------------------------------------------
// Geometry helpers — accept explicit graph context
// ---------------------------------------------------------------------------

function getGroups(graph) {
    return graph?._groups || graph?.groups || [];
}

/**
 * Smallest group by area that contains the node, searched within the
 * provided graph context (not necessarily the top-level graph).
 */
function smallestContainingGroup(node, graph) {
    const groups = getGroups(graph);
    if (!groups.length) return null;

    const [nx, ny] = node.pos;
    const hits = groups.filter(g => {
        const [gx, gy] = g._pos;
        const [gw, gh] = g._size;
        return nx >= gx && nx <= gx + gw && ny >= gy && ny <= gy + gh;
    });
    if (!hits.length) return null;

    hits.sort((a, b) => (a._size[0] * a._size[1]) - (b._size[0] * b._size[1]));
    return hits[0];
}

/**
 * All nodes within the group's bounding box in the given graph context,
 * excluding any IDs in excludeIds.
 */
function nodesInGroup(group, graph, excludeIds = []) {
    const [gx, gy] = group._pos;
    const [gw, gh] = group._size;
    return (graph?._nodes || []).filter(n => {
        if (excludeIds.includes(n.id)) return false;
        const [nx, ny] = n.pos;
        return nx >= gx && nx <= gx + gw && ny >= gy && ny <= gy + gh;
    });
}

function flyToGroup(group) {
    const [gx, gy] = group._pos;
    const [gw, gh] = group._size;
    const cv  = app.canvas;
    const dpr = window.devicePixelRatio || 1;
    const cw  = cv.canvas.width  / dpr;
    const ch  = cv.canvas.height / dpr;
    const pad = 80;

    const scale = Math.min(
        (cw - pad * 2) / Math.max(gw, 1),
        (ch - pad * 2) / Math.max(gh, 1),
        2.5
    );

    cv.ds.scale     = scale;
    cv.ds.offset[0] = cw / 2 - (gx + gw / 2) * scale;
    cv.ds.offset[1] = ch / 2 - (gy + gh / 2) * scale;
    cv.setDirty(true, true);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Shared height calculation used by both onNodeCreated and _applySize
function calcNodeHeight(rowCount) {
    const PAD    = 12;
    const HDR    = 22;
    const ROW    = 30;
    const EMPTY  = 22;
    const CHROME = 42;
    return (rowCount > 0 ? PAD + HDR + rowCount * ROW : PAD + EMPTY) + CHROME;
}

function allControllers() {
    return (app.graph?._nodes || []).filter(n => n.type === CTRL_TYPE);
}

function refreshAllControllers() {
    allControllers().forEach(c => c._buildUI?.());
}

/**
 * Groups [{marker, graph}] entries by marker title.
 * Returns a Map: title → [{marker, graph}, ...]
 */
function groupByTitle(entries) {
    const map = new Map();
    for (const entry of entries) {
        const title = entry.marker.title || "Unnamed Marker";
        if (!map.has(title)) map.set(title, []);
        map.get(title).push(entry);
    }
    return map;
}

// ---------------------------------------------------------------------------
// Extension
// ---------------------------------------------------------------------------

app.registerExtension({
    name: "umbrae.frameToggle",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== CTRL_TYPE) return;

        const proto = nodeType.prototype;

        const origCreated = proto.onNodeCreated;
        proto.onNodeCreated = function () {
            origCreated?.apply(this, arguments);
            ensureStyles();
            this._toggleStates = {};
            this._lastSig      = "";
            this._lastPoll     = 0;
            // Start sized for exactly 1 row — _buildUI resizes to actual count
            const initH        = calcNodeHeight(1);
            this._computedSize = [300, initH];
            this.size          = [300, initH];
            this._initDOMWidget();
        };

        proto._initDOMWidget = function () {
            const container = document.createElement("div");
            container.style.cssText = "padding:6px; width:100%; box-sizing:border-box;";

            ["mousedown", "pointerdown", "touchstart"].forEach(ev =>
                container.addEventListener(ev, e => e.stopPropagation(), { passive: false })
            );

            this._container = container;

            const _ftWidget = this.addDOMWidget("frameToggles", "toggle_ui", container, {
                getValue: () => JSON.stringify(this._toggleStates),
                setValue: (raw) => {
                    try { this._toggleStates = JSON.parse(raw) || {}; }
                    catch { this._toggleStates = {}; }
                    setTimeout(() => {
                        this._applyAll();
                        this._buildUI();
                    }, 600);
                },
            });
            if (_ftWidget?.element) {
                _ftWidget.element.style.width = "100%";
                _ftWidget.element.style.boxSizing = "border-box";
            }

            setTimeout(() => this._buildUI(), 120);
        };

        proto._buildUI = function () {
            const c = this._container;
            if (!c) return;
            c.innerHTML = "";

            const allEntries = findAllMarkers(app.graph);

            if (!allEntries.length) {
                const msg = document.createElement("div");
                msg.className = "uft-empty";
                msg.textContent = "No frame markers in workflow";
                c.appendChild(msg);
                this._applySize(0);
                return;
            }

            const hdr = document.createElement("div");
            hdr.className = "uft-header";
            hdr.textContent = "Frame Toggles";
            c.appendChild(hdr);

            const titleGroups = groupByTitle(allEntries);

            for (const [title, entries] of titleGroups) {
                const multi = entries.length > 1;

                if (!(title in this._toggleStates)) {
                    this._toggleStates[title] = true;
                }
                const isOn = this._toggleStates[title] !== false;

                const row = document.createElement("div");
                row.className = "uft-row";

                // Toggle switch
                const lbl = document.createElement("label");
                lbl.className = "uft-switch";
                lbl.title = isOn ? "Enabled — click to disable" : "Disabled — click to enable";

                const cb = document.createElement("input");
                cb.type    = "checkbox";
                cb.checked = isOn;

                const slider = document.createElement("span");
                slider.className = "uft-slider";

                lbl.appendChild(cb);
                lbl.appendChild(slider);

                // Name
                const nameEl = document.createElement("span");
                nameEl.className = "uft-name" + (isOn ? "" : " muted");
                nameEl.textContent = title;
                nameEl.title = title;

                cb.addEventListener("change", e => {
                    const on = e.target.checked;
                    this._toggleStates[title] = on;
                    nameEl.className = "uft-name" + (on ? "" : " muted");
                    lbl.title = on ? "Enabled — click to disable" : "Disabled — click to enable";
                    this._applyToggleGroup(entries, on);
                });

                // Right-side indicator: count badge for multiples, arrow for single
                if (multi) {
                    const badge = document.createElement("span");
                    badge.className = "uft-count";
                    badge.textContent = `×${entries.length}`;
                    badge.title = `${entries.length} markers with this name`;
                    row.appendChild(lbl);
                    row.appendChild(nameEl);
                    row.appendChild(badge);
                } else {
                    const nav = document.createElement("button");
                    nav.className = "uft-nav";
                    nav.textContent = "⇒";
                    nav.title = `Go to "${title}"`;
                    nav.addEventListener("click", () => {
                        const { marker, graph } = entries[0];
                        const grp = smallestContainingGroup(marker, graph);
                        if (grp) flyToGroup(grp);
                    });
                    row.appendChild(lbl);
                    row.appendChild(nameEl);
                    row.appendChild(nav);
                }

                c.appendChild(row);
            }

            this._applySize(titleGroups.size);
        };

        /**
         * Toggle all markers in an entries group on or off.
         * Each entry carries its own graph context so subgraph markers
         * toggle nodes within the correct inner graph.
         */
        proto._applyToggleGroup = function (entries, enabled) {
            for (const { marker, graph } of entries) {
                const grp = smallestContainingGroup(marker, graph);
                if (!grp) continue;

                // Never mute markers or controllers — searched in same graph context
                const safeIds = (graph?._nodes || [])
                    .filter(n => n.type === MARKER_TYPE || n.type === CTRL_TYPE)
                    .map(n => n.id);

                nodesInGroup(grp, graph, safeIds).forEach(n => {
                    n.mode = enabled ? 0 : 4;
                });
            }
            app.graph.setDirtyCanvas(true, true);
        };

        proto._applyAll = function () {
            const titleGroups = groupByTitle(findAllMarkers(app.graph));
            for (const [title, entries] of titleGroups) {
                const on = this._toggleStates[title] !== false;
                this._applyToggleGroup(entries, on);
            }
        };

        // LiteGraph calls computeSize() during node interaction (move, resize, etc.)
        // and can snap the node back to a smaller size if we don't override it.
        proto.computeSize = function () {
            return [
                this._computedSize?.[0] ?? 300,
                this._computedSize?.[1] ?? 150,
            ];
        };

        /**
         * Calculate and apply node height from row count — avoids DOM
         * measurement which is unreliable because ComfyUI stretches the
         * container to fill the node before we can measure it.
         * Width is only set if smaller than the minimum; user can resize wider.
         */
        proto._applySize = function (rowCount) {
            const newH = calcNodeHeight(rowCount);
            const newW = Math.max(this.size[0] || 300, 300);
            this._computedSize = [newW, newH];
            this.size[0] = newW;
            this.size[1] = newH;
            app.graph?.setDirtyCanvas(true);
        };

        // Poll once per second; rebuild only when something actually changed.
        // Signature covers markers at all depths via findAllMarkers.
        proto.onDrawForeground = function () {
            const now = Date.now();
            if (now - this._lastPoll < 1000) return;
            this._lastPoll = now;

            const sig = findAllMarkers(app.graph)
                .map(({ marker }) => `${marker.id}:${marker.title || ""}`)
                .join("|");

            if (sig !== this._lastSig) {
                this._lastSig = sig;
                this._buildUI();
            }
        };
    },

    nodeCreated(node) {
        if (node.type === MARKER_TYPE) {
            setTimeout(refreshAllControllers, 120);
        }
    },

    async setup() {
        const origRemoved = app.graph.onNodeRemoved;
        app.graph.onNodeRemoved = function (node) {
            origRemoved?.call(this, node);
            if (node.type === MARKER_TYPE) {
                setTimeout(refreshAllControllers, 120);
            }
        };

        const origConfigure = app.graph.onConfigure;
        app.graph.onConfigure = function (...args) {
            origConfigure?.apply(this, args);
            setTimeout(() => {
                allControllers().forEach(c => {
                    c._applyAll?.();
                    c._buildUI?.();
                });
            }, 400);
        };
    },
});
