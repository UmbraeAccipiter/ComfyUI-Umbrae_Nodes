"""
quant.py — umbrae_nodes v0.9.1 (modules/vlm)
On-the-fly weight-only quantization for Hugging Face language models.

Mirrors what ComfyUI does for diffusion models: weights are STORED in a small
dtype and UPCAST at compute time, so it works on any GPU that can hold the
tensors (no FP8 matmul kernels needed). Scaling is per output channel, which
is what keeps FP8 usable for LLM weights (plain casting would push most
weights into the subnormal range and wreck quality).

Supported modes: "fp8_e4m3fn" (1 byte/weight) and "int8" (1 byte/weight).
Both roughly halve the VRAM of a bf16 checkpoint.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F

HAS_FP8 = hasattr(torch, "float8_e4m3fn")
FP8_MAX = float(torch.finfo(torch.float8_e4m3fn).max) if HAS_FP8 else 448.0
INT8_MAX = 127.0

MODES = ("fp8_e4m3fn", "int8")

# Module-name fragments that are never quantized on the fly. lm_head and the
# embeddings are tied in most Llama-family models, and quantizing either
# measurably hurts output; the vision side is small and quality-sensitive.
ALWAYS_FLOAT = ("lm_head", "embed")
VISION_FLOAT = ("vision", "visual", "projector", "merger", "image_newline")


class QuantLinear(nn.Module):
    """nn.Linear replacement: quantized weight + per-channel scale, dequantized per forward."""

    def __init__(self, weight_q, scale, bias, mode):
        super().__init__()
        self.weight = nn.Parameter(weight_q, requires_grad=False)
        self.scale = nn.Parameter(scale, requires_grad=False)          # [out, 1], float32
        self.bias = nn.Parameter(bias, requires_grad=False) if bias is not None else None
        self.out_features, self.in_features = weight_q.shape
        self.quant_mode = mode

    def forward(self, x):
        w = self.weight.to(x.dtype) * self.scale.to(x.dtype)
        b = self.bias.to(x.dtype) if self.bias is not None else None
        return F.linear(x, w, b)

    def extra_repr(self):
        return f"in_features={self.in_features}, out_features={self.out_features}, bias={self.bias is not None}, mode={self.quant_mode}"


@torch.no_grad()
def quantize_weight(weight, mode, work_device=None):
    """Per-output-channel absmax quantization. Returns (q, scale) on work_device."""
    if mode not in MODES:
        raise ValueError(f"unknown quant mode {mode!r}; expected one of {MODES}")
    if mode == "fp8_e4m3fn" and not HAS_FP8:
        raise RuntimeError("this torch build has no float8_e4m3fn dtype; use int8 instead")
    w32 = weight.to(device=work_device or weight.device, dtype=torch.float32)
    amax = w32.abs().amax(dim=1, keepdim=True).clamp_(min=1e-8)
    if mode == "fp8_e4m3fn":
        scale = amax / FP8_MAX
        q = (w32 / scale).clamp_(-FP8_MAX, FP8_MAX).to(torch.float8_e4m3fn)
    else:
        scale = amax / INT8_MAX
        q = torch.round(w32 / scale).clamp_(-INT8_MAX, INT8_MAX).to(torch.int8)
    return q, scale


def should_quantize(name, module, keep_vision_float=True):
    if not isinstance(module, nn.Linear):
        return False
    lname = name.lower()
    if any(k in lname for k in ALWAYS_FLOAT):
        return False
    if keep_vision_float and any(k in lname for k in VISION_FLOAT):
        return False
    return True


@torch.no_grad()
def convert_linears(model, mode, keep_vision_float=True, work_device=None, target_device=None):
    """Replace eligible nn.Linear modules in-place with QuantLinear.

    work_device: where the math runs (GPU if available, it is much faster);
    target_device: where the quantized weights end up (the offload device, so
    ComfyUI's model management can move the whole model as one unit).
    Returns (replaced, kept, bytes_before, bytes_after) for the converted layers."""
    replaced = kept = 0
    before = after = 0
    for parent_name, parent in list(model.named_modules()):
        for child_name, child in list(parent.named_children()):
            if not isinstance(child, nn.Linear):
                continue
            full = f"{parent_name}.{child_name}" if parent_name else child_name
            if not should_quantize(full, child, keep_vision_float):
                kept += 1
                continue
            tgt = target_device or child.weight.device
            q, scale = quantize_weight(child.weight.data, mode, work_device)
            bias = child.bias.data.to(tgt) if child.bias is not None else None
            before += child.weight.numel() * child.weight.element_size()
            q = q.to(tgt)
            scale = scale.to(tgt)
            after += q.numel() * q.element_size() + scale.numel() * scale.element_size()
            setattr(parent, child_name, QuantLinear(q, scale, bias, mode))
            del child
            replaced += 1
    return replaced, kept, before, after
