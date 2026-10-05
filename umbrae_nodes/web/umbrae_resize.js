// umbrae_resize.js
// DOM-widget mount helpers, built to ComfyUI's actual contract (verified
// against a working reference pack). Replaces the per-node copies.

import { app } from "../../scripts/app.js";

export function isVueNodes() { return !!window.LiteGraph?.vueNodesMode; }

// Sum visible children + row gaps + vertical padding. NOT scrollHeight (the
// layout stretches it, creating a feedback loop).
export function measureRootContent(root) {
    if (!root) return 0;
    let h = 0, count = 0;
    for (const child of root.children) {
        if (child.offsetParent === null) continue;
        h += child.offsetHeight;
        count += 1;
    }
    const cs = getComputedStyle(root);
    const gap = parseFloat(cs.rowGap || cs.gap) || 0;
    if (count > 1) h += gap * (count - 1);
    h += (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0);
    return h;
}

// REQUIRED for a DOM widget to render INSIDE the node body. In Nodes 2.0 the
// renderer uses `shouldRenderAsVue = !options.canvasOnly`; a static
// canvasOnly:true drops the widget out of the Vue body entirely (it renders
// detached / beside the node). A live getter gives the correct value per
// renderer, re-evaluated every frame: true in legacy (keeps it out of the
// Parameters sidebar), false in Nodes 2.0 (renders in the node body).
export function applyAdaptiveCanvasOnly(widget) {
    if (!widget || !widget.options) return widget;
    try {
        Object.defineProperty(widget.options, "canvasOnly", {
            configurable: true, enumerable: true,
            get() { return !window.LiteGraph?.vueNodesMode; },
        });
    } catch (_) {
        widget.options.canvasOnly = !window.LiteGraph?.vueNodesMode;
    }
    return widget;
}

// While a resize handle is actively dragged in Nodes 2.0, pin a hard
// min-height = content height so the node can't be dragged below its content.
// Armed only for the gesture. Returns an uninstall fn.
export function installResizeFloor(root, measureFn) {
    if (!root || typeof measureFn !== "function") return () => {};
    let armed = false;
    const clear = () => { if (!armed) return; armed = false; try { root.style.minHeight = ""; } catch (_) {} };
    const onDown = (e) => {
        if (!isVueNodes() || !root.isConnected) return;
        let cur = "";
        try { cur = (e.target && getComputedStyle(e.target).cursor) || ""; } catch (_) {}
        if (cur.indexOf("resize") === -1) return;
        const myNode = root.closest(".lg-node");
        const downNode = e.target.closest && e.target.closest(".lg-node");
        if (myNode && downNode && myNode !== downNode) return;
        let h = 0;
        try { h = measureFn(root); } catch (_) { return; }
        if (!(h > 0)) return;
        try { root.style.minHeight = Math.round(h) + "px"; armed = true; } catch (_) {}
    };
    window.addEventListener("pointerdown", onDown, true);
    window.addEventListener("pointerup", clear, true);
    window.addEventListener("pointercancel", clear, true);
    return () => {
        window.removeEventListener("pointerdown", onDown, true);
        window.removeEventListener("pointerup", clear, true);
        window.removeEventListener("pointercancel", clear, true);
        clear();
    };
}

// Grow/shrink the node to fit its DOM content, in BOTH renderers, via
// LiteGraph's official setSize() path (a bare node.size[1] write desyncs the
// Vue layout). Returns { scheduleRelayout, relayout, dispose }.
export function attachAutoHeight(node, root, widget) {
    let raf = null;

    function chromeHeight() {
        const SH = (window.LiteGraph?.NODE_SLOT_HEIGHT) || 20;
        const slots = Math.max(node.inputs?.length ?? 0, node.outputs?.length ?? 0);
        return slots * SH + 6;
    }
    function relayout() {
        if (!root.isConnected) return;
        const desired = chromeHeight() + measureRootContent(root);
        const w = node.size?.[0] ?? 0;
        if (Math.abs((node.size?.[1] ?? 0) - desired) > 1) {
            if (typeof node.setSize === "function") node.setSize([w, desired]);
            else if (node.size) node.size[1] = desired;
        }
        node.setDirtyCanvas?.(true, true);
        // Classic renderer: a dirty flag alone often won't repaint until the
        // next input event (mouse move / keypress). Force the redraw so the
        // node frame follows the content immediately.
        try { app?.canvas?.draw?.(true, true); } catch (_) {}
    }
    function scheduleRelayout() {
        if (raf) cancelAnimationFrame(raf);
        raf = requestAnimationFrame(() => { raf = null; relayout(); });
    }

    if (widget && isVueNodes()) widget.computeLayoutSize = undefined;
    const removeFloor = installResizeFloor(root, measureRootContent);
    const ro = new ResizeObserver(scheduleRelayout);
    ro.observe(root);

    // Re-clamp if LiteGraph tries to shrink the node below its content.
    const _origResize = node.onResize;
    node.onResize = function (size) {
        const min = chromeHeight() + measureRootContent(root);
        if (size && size[1] < min) size[1] = min;
        return _origResize?.apply(this, arguments);
    };

    scheduleRelayout();
    return {
        scheduleRelayout, relayout,
        dispose() {
            if (raf) cancelAnimationFrame(raf);
            ro.disconnect();
            removeFloor();
        },
    };
}
