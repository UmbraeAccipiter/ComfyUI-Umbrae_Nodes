/**
 * LiteGraph DOM widget width guard — prevents WidgetLegacy.vue from
 * persisting a narrow container width on widget.width in classic mode.
 */

function resolveLiteGraph(getLiteGraph) {
	if (typeof getLiteGraph === "function") {
		return getLiteGraph();
	}
	return typeof LiteGraph !== "undefined" ? LiteGraph : undefined;
}

export function isVueNodesMode(getLiteGraph) {
	const LG = resolveLiteGraph(getLiteGraph);
	return !!(LG && LG.vueNodesMode);
}

export function installDomWidgetWidthGuard(widget, { getLiteGraph } = {}) {
	if (!widget || widget._wc_width_guard) {
		return;
	}
	let backingWidth;
	Object.defineProperty(widget, "width", {
		configurable: true,
		enumerable: true,
		get() {
			if (isVueNodesMode(getLiteGraph)) {
				return backingWidth;
			}
			return undefined;
		},
		set(v) {
			if (isVueNodesMode(getLiteGraph)) {
				backingWidth = v;
			}
		},
	});
	widget._wc_width_guard = true;
}
