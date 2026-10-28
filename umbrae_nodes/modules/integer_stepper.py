# integer_stepper.py — Integer Stepper with post-iteration (umbrae_nodes)
import random

class IntegerStepper:
    """
    Integer generator with optional post-iteration.

    Modes:
      - FIXED:      value = base
      - INCREMENT:  value = base + iteration * step
      - DECREMENT:  value = base - iteration * step
      - RANDOM:     value ~ randint[min_value, max_value] (seeded with seed + iteration if iteration provided)

    Features:
      - 'advance_after_emit' -> when True, iteration_out = iteration + 1 (value still uses current iteration)
      - Optional clamping for INCREMENT/DECREMENT to [min_value, max_value]
      - Zero-pad the string mirror for filenames (e.g., width=3 -> "007")
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mode": (["FIXED", "INCREMENT", "DECREMENT", "RANDOM"], {"default": "FIXED"}),
                "base": ("INT", {"default": 0, "min": -2_147_483_648, "max": 2_147_483_647}),
                "step": ("INT", {"default": 1, "min": -2_147_483_648, "max": 2_147_483_647}),
                "min_value": ("INT", {"default": 0, "min": -2_147_483_648, "max": 2_147_483_647}),
                "max_value": ("INT", {"default": 999999, "min": -2_147_483_648, "max": 2_147_483_647}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 2_147_483_647}),
                "advance_after_emit": ("BOOLEAN", {"default": False}),
                "clamp_range": ("BOOLEAN", {"default": True}),
                "zero_pad_width": ("INT", {"default": 0, "min": 0, "max": 12}),
            },
            "optional": {
                # Wire your loop counter (0,1,2,...) if you want per-iteration behavior.
                "iteration": ("INT", {"default": 0, "min": -2_147_483_648, "max": 2_147_483_647}),
            },
        }

    RETURN_TYPES = ("INT", "STRING", "INT")
    RETURN_NAMES = ("value_int", "value_str", "iteration_out")
    FUNCTION = "generate"
    CATEGORY = "umbrae/workflow"

    def _clamp(self, v: int, lo: int, hi: int, enable: bool) -> int:
        if not enable: 
            return v
        if lo > hi:
            lo, hi = hi, lo
        if v < lo: return lo
        if v > hi: return hi
        return v

    def _zpad(self, n: int, w: int) -> str:
        sgn = "-" if n < 0 else ""
        return sgn + str(abs(int(n))).zfill(max(0, int(w)))

    def generate(self, mode, base, step, min_value, max_value, seed,
                 advance_after_emit, clamp_range, zero_pad_width, iteration=0):
        it = int(iteration) if iteration is not None else 0
        m = str(mode).upper().strip()

        if m == "FIXED":
            val = int(base)

        elif m == "INCREMENT":
            val = int(base) + int(step) * it
            val = self._clamp(val, int(min_value), int(max_value), bool(clamp_range))

        elif m == "DECREMENT":
            val = int(base) - int(step) * it
            val = self._clamp(val, int(min_value), int(max_value), bool(clamp_range))

        else:  # RANDOM
            lo = int(min_value); hi = int(max_value)
            if lo > hi: lo, hi = hi, lo
            rng = random.Random(int(seed) + it)
            val = rng.randint(lo, hi)

        # String mirror (optionally zero-padded)
        if int(zero_pad_width) > 0:
            s_val = self._zpad(int(val), int(zero_pad_width))
        else:
            s_val = str(int(val))

        # Post-iteration: expose the next iteration number if requested
        next_it = it + 1 if bool(advance_after_emit) else it

        return (int(val), s_val, int(next_it))


# Register
NODE_CLASS_MAPPINGS = {
    "IntegerStepper": IntegerStepper,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "IntegerStepper": "Integer Stepper [umbrae]",
}
