# number_tools.py — umbrae_nodes
# MathTranslation: two-input math + type conversion node.
# Data flow: A → [input fn] → math op ← [input fn] ← B → output conditioning → outputs

import math
import json


class AnyType(str):
    def __ne__(self, __value):
        return False

_ANY = AnyType("*")


class MathTranslation:

    BINARY_OPS = {"ADD", "SUB", "MUL", "DIV", "MOD", "PCT", "POW", "MIN", "MAX"}

    DEFAULT_STATE = {
        # A input
        "a_type": "OFF", "a_int_val": 0, "a_float_val": 0.0, "a_str_val": "0",
        # A input function (applied before math op)
        "a_fn": "none",
        "a_fn_round_by": 1.0, "a_fn_rounding_mode": "NEAREST",
        "a_fn_tie_break": "HALF_AWAY_FROM_ZERO",
        "a_fn_clamp_min": 0.0, "a_fn_clamp_max": 100.0,
        # B input
        "b_type": "OFF", "b_int_val": 1, "b_float_val": 1.0, "b_str_val": "1",
        # B input function
        "b_fn": "none",
        "b_fn_round_by": 1.0, "b_fn_rounding_mode": "NEAREST",
        "b_fn_tie_break": "HALF_AWAY_FROM_ZERO",
        "b_fn_clamp_min": 0.0, "b_fn_clamp_max": 100.0,
        # Math operation
        "op": "NONE",
        # Output conditioning (applied to math result)
        "out_cond": "none",
        "rounding_mode": "NEAREST", "tie_break": "HALF_AWAY_FROM_ZERO", "round_by": 1.0,
        "clamp_min": 0.0, "clamp_max": 100.0,
        # Advanced output formatting
        "out_clamp_enabled": False, "out_clamp_min": 0.0, "out_clamp_max": 100.0,
        "int_rounding": "off",
        "decimals": 3, "decimals_off": False,
    }

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {},
            "optional": { "A": (_ANY, {}), "B": (_ANY, {}) },
            "hidden":   { "ui_state": ("STRING", {"default": "{}"}) },
        }

    @classmethod
    def VALIDATE_INPUTS(cls, input_types):
        return True

    RETURN_TYPES  = ("INT", "FLOAT", "STRING")
    RETURN_NAMES  = ("int", "float", "string")
    FUNCTION      = "compute"
    CATEGORY      = "umbrae/workflow"

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_state(self, ui_state):
        state = dict(self.DEFAULT_STATE)
        try:
            state.update(json.loads(ui_state or "{}"))
        except Exception:
            pass
        return state

    def _to_float(self, v):
        if v is None: return None
        try:
            if isinstance(v, (int, float)): return float(v)
            s = str(v).replace(",", "").strip()
            return float(s) if s else 0.0
        except Exception:
            return 0.0

    def _get_side(self, wired, state, side):
        """Return float value for A or B; wired value always wins."""
        if wired is not None:
            return self._to_float(wired)
        t = str(state.get(f"{side}_type", "OFF")).upper()
        if t == "OFF":    return None
        if t == "INT":    return float(int(state.get(f"{side}_int_val", 0)))
        if t == "FLOAT":  return float(state.get(f"{side}_float_val", 0.0))
        if t in ("STRING", "STR"):
            s = str(state.get(f"{side}_str_val", "0")).replace(",", "").strip()
            try:    return float(s) if s else 0.0
            except: return 0.0
        return None

    def _nearest_idx(self, q, tie_break, sign):
        lo, hi = math.floor(q), math.floor(q) + 1
        dl, dh = q - lo, hi - q
        eps = 1e-12
        if dl + eps < dh: return lo
        if dh + eps < dl: return hi
        tb = str(tie_break).upper()
        if tb == "HALF_UP":             return hi
        if tb == "HALF_DOWN":           return lo
        if tb == "HALF_TO_EVEN":        return lo if lo % 2 == 0 else hi
        if tb == "HALF_AWAY_FROM_ZERO": return hi if sign >= 0 else lo
        if tb == "HALF_TOWARD_ZERO":    return lo if sign >= 0 else hi
        return hi

    def _round_step(self, v, mode, step, tie_break):
        s = max(float(step), 1e-9)
        q = v / s
        m = str(mode).upper()
        if m == "OFF":      return v
        if m == "NEAREST":  return self._nearest_idx(q, tie_break, 1 if v >= 0 else -1) * s
        if m == "DOWN":     return math.floor(q) * s
        if m == "UP":       return math.ceil(q) * s
        if m == "FURTHEST": return (math.ceil(q) if v >= 0 else math.floor(q)) * s
        return v

    def _apply_fn(self, v, fn_name, state, prefix):
        """Apply an input function (abs/neg/floor/ceil/round/clamp) to a value."""
        fn = str(fn_name).upper()
        if fn == "ABS":   return abs(v)
        if fn == "NEG":   return -v
        if fn == "FLOOR": return float(math.floor(v))
        if fn == "CEIL":  return float(math.ceil(v))
        if fn == "ROUND":
            return self._round_step(
                v,
                state.get(f"{prefix}rounding_mode", "NEAREST"),
                state.get(f"{prefix}round_by",      1.0),
                state.get(f"{prefix}tie_break",      "HALF_AWAY_FROM_ZERO"),
            )
        if fn == "CLAMP":
            lo = float(state.get(f"{prefix}clamp_min", 0.0))
            hi = float(state.get(f"{prefix}clamp_max", 100.0))
            if lo > hi: lo, hi = hi, lo
            return max(lo, min(hi, v))
        return v   # "none" or unknown

    def _bin_op(self, x, y, op):
        if op == "ADD": return x + y
        if op == "SUB": return x - y
        if op == "MUL": return x * y
        if op == "DIV": return (x / y) if y != 0 else 0.0
        if op == "MOD": return (x % y) if y != 0 else 0.0
        if op == "PCT": return (x / y * 100.0) if y != 0 else 0.0
        if op == "MIN": return min(x, y)
        if op == "MAX": return max(x, y)
        if op == "POW":
            try:    return math.pow(x, y)
            except: return 0.0
        return x

    def _to_int(self, v, mode):
        m = str(mode).lower()
        if m == "nearest": return int(round(float(v)))
        if m == "floor":   return math.floor(float(v))
        if m == "ceil":    return math.ceil(float(v))
        return int(float(v))   # "off" or unknown → truncate

    # ── Main ─────────────────────────────────────────────────────────────────

    def compute(self, A=None, B=None, ui_state="{}"):
        state = self._parse_state(ui_state)

        # 1. Get raw input values
        ax = self._get_side(A, state, "a")
        bx = self._get_side(B, state, "b")

        # 2. Apply per-input functions
        a_fn = str(state.get("a_fn", "none")).upper()
        if ax is not None and a_fn != "NONE":
            ax = self._apply_fn(ax, a_fn, state, "a_fn_")

        b_fn = str(state.get("b_fn", "none")).upper()
        if bx is not None and b_fn != "NONE":
            bx = self._apply_fn(bx, b_fn, state, "b_fn_")

        # 3. Math operation
        op = str(state.get("op", "NONE")).upper()

        if op == "NONE":
            res = ax if ax is not None else (bx if bx is not None else 0.0)
        elif op in self.BINARY_OPS:
            d = 0.0 if op in ("ADD", "SUB", "MIN", "MAX") else 1.0
            x = float(ax) if ax is not None else d
            y = float(bx) if bx is not None else d
            res = self._bin_op(x, y, op)
        else:
            res = ax if ax is not None else (bx if bx is not None else 0.0)

        res = float(res) if res is not None else 0.0

        # 4. Output conditioning (clamp / round / floor / ceil applied to result)
        out_cond = str(state.get("out_cond", "none")).upper()
        if out_cond not in ("NONE", ""):
            res = self._apply_fn(res, out_cond, state, "")

        # 5. Advanced output clamp
        if state.get("out_clamp_enabled", False):
            lo = float(state.get("out_clamp_min", 0.0))
            hi = float(state.get("out_clamp_max", 100.0))
            if lo > hi: lo, hi = hi, lo
            res = max(lo, min(hi, res))

        # 6. Format outputs
        out_int   = self._to_int(res, state.get("int_rounding", "off"))
        out_float = res

        if state.get("decimals_off", False):
            out_str = str(int(res)) if res == int(res) else repr(float(res))
        else:
            decimals = max(0, int(state.get("decimals", 3)))
            out_str  = str(int(res)) if res == int(res) else f"{res:.{decimals}f}"

        return (int(out_int), float(out_float), out_str)


NODE_CLASS_MAPPINGS       = { "MathTranslation": MathTranslation }
NODE_DISPLAY_NAME_MAPPINGS = { "MathTranslation": "Math Translation [umbrae]" }
