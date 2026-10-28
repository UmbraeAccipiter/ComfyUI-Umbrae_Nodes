// tokens.js — wildcard processor [umbrae] syntax highlighting: the tokenizer.
//
// Pure functions (no DOM, no ComfyUI imports) so they can be tested in node.
//
//   tokenize(text, { tagState })  -> { spans, pairs }
//     spans: [{ s, e, c, key?, closer?, opt? }] sorted, non-overlapping
//       c = category (tag tagd var varo sw swo pin repl prot aspect ctl weight sep
//           esc comment br0-br3 bad opt); closer = a closing brace (c = its opener's category)
//       opt = option index inside a group (c "opt", only index >= 1 is emitted)
//     pairs: Map  brace index -> index of its partner (matched braces only)
//     tagState(name) -> true | false | undefined   known / unknown / not checked yet
//   markSpans(spans, pairs, caret, { pair, same }) -> Set of spans to emphasise
//   toHtml(text, spans, marked, cfg) -> escaped HTML for the backdrop layer
//     cfg: { optMode: none|alternate|cycle|tint, closeColor: bool }
//
// Mirrors the engine's regexes (modules/umbrae_wildcards.py): tags
// __[\w.\-+/*\\]+?__, names [A-Za-z_][A-Za-z0-9_.-]*, backslash escapes, '#'
// comment lines, aspect tokens. It colours text only; it never changes it.

const NAME = "[A-Za-z_][A-Za-z0-9_.-]*";

const RE = {
    esc:     /\\[\s\S]/y,
    comment: /[ \t]*#[^\n]*/y,
    aspReq:  /\[\[\s*(?:\d+\s*:\s*\d+|aspect)\s*\]\]/iy,
    aspTok:  /\[(?:orientation|ratio|width|height)\]|\[\s*\d+\s*:\s*\d+\s*\]/iy,
    quant:   /\d+#(?=__)/y,
    tag:     /__([\w.\-+/*\\]+?)__/y,
    protOpen:/-=/y,
    protEnd: /=-(?=\})/y,
    varHead: new RegExp(`@(!?)(${NAME})`, "y"),
    swPin:   /&=[^:{}\n]*:/y,
    swHead:  new RegExp(`&(!?)(${NAME})`, "y"),
    repHead: /!{1,4}(?=[^!=])[^={}|\n]*/y,
    varRef:  new RegExp(`(?<![\\w@])@(${NAME})`, "y"),
    prefix:  /(?:\d*\+|-)::/y,
    count:   /(?:\d+(?:-\d+)?|-\d+)?\$\$/y,
    dollars: /\$\$/y,
    weight:  /\d+(?:\.\d+)?::/y,
};

function sticky(re, text, i) {
    re.lastIndex = i;
    return re.exec(text);
}

export function tagKey(raw) {
    return raw.replace(/\.(txt|ya?ml)$/i, "").toLowerCase();
}

export function tokenize(text, opts = {}) {
    const tagState = opts.tagState || (() => undefined);
    const spans = [];
    const pairs = new Map();
    const stack = [];            // open-brace spans, innermost last; .cnt = current option index
    const n = text.length;
    let i = 0;

    const push = (s, e, c, key) => {
        const sp = { s, e, c };
        if (key) sp.key = key;
        spans.push(sp);
        return sp;
    };

    while (i < n) {
        const ch = text[i];
        let m;

        if ((i === 0 || text[i - 1] === "\n") && (m = sticky(RE.comment, text, i))) {
            push(i, i + m[0].length, "comment");
            i += m[0].length;
            continue;
        }
        if (ch === "\\" && (m = sticky(RE.esc, text, i))) {
            push(i, i + 2, "esc");
            i += 2;
            continue;
        }
        if (ch === "[") {
            if ((m = sticky(RE.aspReq, text, i)) || (m = sticky(RE.aspTok, text, i))) {
                push(i, i + m[0].length, "aspect");
                i += m[0].length;
                continue;
            }
            if (text[i + 1] === "[") {                                 // [[ that never closes on its line
                const eol = text.indexOf("\n", i);
                const close = text.indexOf("]]", i + 2);
                if (close < 0 || (eol >= 0 && close > eol)) {
                    push(i, i + 2, "bad");
                    i += 2;
                    continue;
                }
            }
        }
        if (ch === "]" && text[i + 1] === "]") {                      // ]] with no [[ before it
            const sol = text.lastIndexOf("\n", i - 1) + 1;
            if (text.slice(sol, i).indexOf("[[") < 0) {
                push(i, i + 2, "bad");
                i += 2;
                continue;
            }
        }
        if (ch === "_" && (m = sticky(RE.tag, text, i))) {
            const raw = m[1];
            const name = tagKey(raw);
            const unknown = !/[*]/.test(name) && tagState(name) === false;
            const cls = unknown ? "bad" : "tag";
            push(i, i + 2, unknown ? "bad" : "tagd");
            push(i + 2, i + m[0].length - 2, cls, "tag:" + name);
            push(i + m[0].length - 2, i + m[0].length, unknown ? "bad" : "tagd");
            i += m[0].length;
            continue;
        }
        if (/\d/.test(ch)) {
            if ((m = sticky(RE.quant, text, i))) {                    // 3#__name__
                push(i, i + m[0].length, "ctl");
                i += m[0].length;
                continue;
            }
            if (stack.length) {
                if ((m = sticky(RE.prefix, text, i)) || (m = sticky(RE.count, text, i))
                    || (m = sticky(RE.weight, text, i))) {
                    push(i, i + m[0].length, m[0].endsWith("$$") || /[+-]::$/.test(m[0]) ? "ctl" : "weight");
                    i += m[0].length;
                    continue;
                }
            }
        }
        if (stack.length) {
            if (ch === "-" && (m = sticky(RE.prefix, text, i))) {     // -:: group prefix
                push(i, i + m[0].length, "ctl");
                i += m[0].length;
                continue;
            }
            if (ch === "$" && (m = sticky(RE.dollars, text, i))) {
                push(i, i + 2, "ctl");
                i += 2;
                continue;
            }
            if (ch === "|" || ch === "^") {
                push(i, i + 1, "sep");
                stack[stack.length - 1].cnt += 1;
                i += 1;
                continue;
            }
            if (ch === "=" && (m = sticky(RE.protEnd, text, i))) {   // =-} closes {-= ... =-}
                push(i, i + 2, "prot");
                i += 2;
                continue;
            }
        }
        if (ch === "{") {
            const sp = push(i, i + 1, "br" + (stack.length % 4));
            sp.cnt = 0;
            stack.push(sp);
            i += 1;
            // what kind of group is this? colour its header and the braces to match
            if ((m = sticky(RE.protOpen, text, i))) {
                sp.c = "prot";
                push(i, i + 2, "prot");
                i += 2;
            } else if (text[i] === "@" && (m = sticky(RE.varHead, text, i))) {
                sp.c = m[1] ? "varo" : "var";
                push(i, i + m[0].length, sp.c, "var:" + m[2].toLowerCase());
                i += m[0].length;
            } else if (text[i] === "&" && (m = sticky(RE.swPin, text, i))) {
                sp.c = "pin";
                push(i, i + m[0].length, "pin");
                i += m[0].length;
            } else if (text[i] === "&" && (m = sticky(RE.swHead, text, i))) {
                sp.c = m[1] ? "swo" : "sw";
                push(i, i + m[0].length, sp.c, "sw:" + m[2].toLowerCase());
                i += m[0].length;
            } else if (text[i] === "!" && (m = sticky(RE.repHead, text, i))) {
                sp.c = "repl";
                push(i, i + m[0].length, "repl");
                i += m[0].length;
            }
            continue;
        }
        if (ch === "}") {
            const sp = push(i, i + 1, "bad");
            const open = stack.pop();
            if (open) {
                sp.c = open.c;
                sp.closer = true;
                pairs.set(open.s, i);
                pairs.set(i, open.s);
            }
            i += 1;
            continue;
        }
        if (ch === "@" && (m = sticky(RE.varRef, text, i))) {
            push(i, i + m[0].length, "var", "var:" + m[1].toLowerCase());
            i += m[0].length;
            continue;
        }
        // plain text: belongs to the option currently being written (odd/higher options get a colour)
        if (stack.length) {
            const top = stack[stack.length - 1];
            if (top.cnt > 0) {
                const last = spans[spans.length - 1];
                if (last && last.c === "opt" && last.opt === top.cnt && last.e === i) last.e = i + 1;
                else { const o = push(i, i + 1, "opt"); o.opt = top.cnt; }
            }
        }
        i += 1;
    }
    for (const open of stack) open.c = "bad";                          // never closed
    return { spans, pairs };
}

// Spans to emphasise for the caret: the brace pair touching it, and/or every
// use of the tag / variable / switch the caret sits in.
export function markSpans(spans, pairs, caret, flags = { pair: true, same: true }) {
    const marked = new Set();
    if (caret == null || caret < 0) return marked;
    const byStart = new Map();
    for (const sp of spans) byStart.set(sp.s, sp);
    if (flags.pair) {
        for (const at of [caret - 1, caret]) {
            const sp = byStart.get(at);
            if (sp && sp.e - sp.s === 1 && pairs.has(at) || (sp && sp.c === "bad" && sp.e - sp.s === 1)) {
                marked.add(sp);
                const other = pairs.get(at);
                if (other != null) marked.add(byStart.get(other));
                return marked;
            }
        }
    }
    if (flags.same) {
        const here = spans.find((sp) => sp.key && caret >= sp.s && caret <= sp.e);
        if (here) for (const sp of spans) if (sp.key === here.key) marked.add(sp);
    }
    return marked;
}

const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;" };
const esc = (s) => s.replace(/[&<>]/g, (c) => ESC[c]);

// class suffix for one span under the current settings ("" = no span needed)
function classFor(sp, cfg) {
    if (sp.c === "opt") {
        const k = sp.opt;
        switch (cfg.optMode) {
            case "none": return "";
            case "cycle": return "opt" + (k % 4);
            case "tint": return "tint" + (k % 2 ? 1 : 2);
            default: return k % 2 ? "opt1" : "";          // alternate (default)
        }
    }
    if (sp.closer && !cfg.closeColor) return "plain";
    return sp.c;
}

export function toHtml(text, spans, marked, cfg = {}) {
    cfg = { optMode: "alternate", closeColor: true, ...cfg };
    let out = "";
    let pos = 0;
    for (const sp of spans) {
        if (sp.s > pos) out += esc(text.slice(pos, sp.s));
        const c = classFor(sp, cfg);
        const hit = marked && marked.has(sp);
        const body = esc(text.slice(sp.s, sp.e));
        if (c || hit) out += `<span class="${c ? "uwh-" + c : ""}${hit ? " uwh-hit" : ""}">${body}</span>`;
        else out += body;
        pos = sp.e;
    }
    if (pos < text.length) out += esc(text.slice(pos));
    if (text.endsWith("\n") || text === "") out += " ";               // keep the last empty line's height
    return out;
}
