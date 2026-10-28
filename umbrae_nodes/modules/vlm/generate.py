"""
generate.py — umbrae_nodes v0.9.1 (modules/vlm)
Chat-template rendering and text generation for an UmbraeVLM.

Image placement differs per model family, so the user turn is rendered in two
ways and the first one that actually contains the image token wins:
  1. plain-string content   -> JoyCaption-style templates insert the image
                               token themselves (and would crash on a list)
  2. structured content     -> Qwen-VL / standard LLaVA templates expect
     [{"type":"image"},{"type":"text"}]
If neither produces the token it is prepended to the user text as a last resort.
"""

import re
import logging

import torch

log = logging.getLogger("umbrae.vlm")

THINK_RE = re.compile(r"<think>.*?</think>\s*", re.S)


def render_chat(vlm, system_prompt, user_prompt, with_image):
    templater = vlm.processor if hasattr(vlm.processor, "apply_chat_template") else vlm.tokenizer

    def render(content):
        msgs = []
        if system_prompt and system_prompt.strip():
            msgs.append({"role": "system", "content": system_prompt.strip()})
        msgs.append({"role": "user", "content": content})
        return templater.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)

    text = user_prompt.strip()
    if not with_image:
        try:
            return render(text)
        except Exception:
            return render([{"type": "text", "text": text}])

    token = vlm.image_token
    attempts = (text, [{"type": "image"}, {"type": "text", "text": text}])
    rendered = None
    errors = []
    for content in attempts:
        try:
            out = render(content)
        except Exception as e:          # template rejects this content shape
            errors.append(str(e))
            continue
        if rendered is None:
            rendered = out
        if token and token in out:
            return out
    if rendered is None:
        raise RuntimeError("chat template failed for both content shapes: " + " | ".join(errors))
    if token and token not in rendered:
        idx = rendered.find(text)
        if idx >= 0:
            rendered = rendered[:idx] + token + "\n" + rendered[idx:]
        else:
            rendered = token + "\n" + rendered
    return rendered


def strip_thinking(text):
    text = THINK_RE.sub("", text)
    if "</think>" in text:                   # unterminated opening tag
        text = text.split("</think>", 1)[1]
    return text.strip()


@torch.inference_mode()
def generate_text(vlm, system_prompt, user_prompt, pil_image=None, *, max_new_tokens=512,
                  temperature=0.6, top_p=0.9, top_k=0, repetition_penalty=1.0, seed=0,
                  remove_thinking=True):
    vlm.ensure_loaded()
    hf = vlm.hf
    device = vlm.device
    tokenizer = vlm.tokenizer

    text = render_chat(vlm, system_prompt, user_prompt, pil_image is not None)

    if pil_image is not None:
        if not vlm.has_processor:
            raise RuntimeError(f"{vlm.meta['name']} has no image processor; it is a text-only model")
        inputs = vlm.processor(text=[text], images=[pil_image], return_tensors="pt")
    elif vlm.has_processor:
        inputs = vlm.processor(text=[text], return_tensors="pt")
    else:
        inputs = tokenizer(text, return_tensors="pt")
    inputs = inputs.to(device)

    compute_dtype = vlm.compute_dtype
    for k, v in list(inputs.items()):
        if torch.is_tensor(v) and torch.is_floating_point(v):
            inputs[k] = v.to(compute_dtype)

    torch.manual_seed(seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(seed)

    gen = {"max_new_tokens": int(max_new_tokens), "use_cache": True}
    if temperature > 0:
        gen.update(do_sample=True, temperature=float(temperature), top_p=float(top_p),
                   top_k=int(top_k) if top_k > 0 else None)
    else:
        gen.update(do_sample=False, temperature=None, top_p=None, top_k=None)
    if repetition_penalty and abs(repetition_penalty - 1.0) > 1e-6:
        gen["repetition_penalty"] = float(repetition_penalty)
    pad = tokenizer.pad_token_id if tokenizer.pad_token_id is not None else tokenizer.eos_token_id
    if pad is not None:
        gen["pad_token_id"] = pad

    out = hf.generate(**inputs, **gen)
    new_tokens = out[0, inputs["input_ids"].shape[1]:]
    result = tokenizer.decode(new_tokens, skip_special_tokens=True)
    return strip_thinking(result) if remove_thinking else result.strip()
