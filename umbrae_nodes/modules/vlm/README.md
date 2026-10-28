# modules/vlm — HF vision-language / text models inside ComfyUI's memory manager

Four nodes, no downloads, no bitsandbytes. Wiring (same shape as JoyCaption Advanced):

```
Load Image ──────────────────────────────┐ image
                                         ▼
load vlm / llm (hf) ── vlm ───────► vlm generate ── text ───────► (one run per caption)
                                         ▲         └─ text_joined ─► (all captions, one string)
caption extras ── extras ─► caption prompt ── prompt ┘
```

| node | what it does |
|---|---|
| **load vlm / llm (hf) [umbrae]** | `external_root` blank = scan `ComfyUI/models/LLM` (any depth up to 3; a model folder is one that contains `config.json`). Set `external_root` to a path anywhere on disk and press **Refresh models**: if that folder *is* a model folder the dropdown shows `.` and loads it directly (e.g. a Gemma snapshot you already have elsewhere); if it holds several model folders they are listed. The list is cached in the workflow and refreshed through `/umbrae/vlm/scan` (web/umbrae_vlm.js). The model is loaded **through ComfyUI's ModelPatcher**: it sits in RAM between uses, is moved to the GPU on demand, and is evicted like any other model when a diffusion model needs the VRAM. Output: `UMBRAE_VLM` + an info string. One loader can feed several generate nodes. |
| **vlm generate [umbrae]** | `vlm` + `prompt` (+ optional IMAGE batch) + the LLM controls -> text. `system_prompt_override` is empty by default, which uses the built-in captioning system prompt (JoyCaption's); type anything to replace it, or `-` for none. `text` is a **list** (one string per image; a downstream node runs once per caption). `text_joined` is the same captions in **one string**, separated by `joiner`. With one image they are identical, so use whichever your downstream node wants. `after_run`: keep on GPU, or offload to RAM right away. `append_image_facts` adds the real pixel size, orientation and aspect ratio of each image to the prompt (models only see a resized copy and guess these badly). Works text-only when no image is connected. |
| **caption prompt (joycaption) [umbrae]** | style + length / word count + `additions` free text (+ optional `extras`) -> `prompt`. |
| **caption extras (joycaption) [umbrae]** | JoyCaption's 27 extra-option toggles + character name -> `extras`. Plain instructions, so they also work with Qwen-VL and friends. |

## weights

| option | behaviour |
|---|---|
| `auto (as stored)` | respects the checkpoint: bf16, or a pre-quantized checkpoint. **compressed-tensors FP8** (`pip install compressed-tensors`): current transformers would keep the weights compressed and then *decompress them to bf16 on the first forward*, so an "FP8" 8B model would silently run as 17 GB. The loader prevents that two ways: it asks transformers for its FP8 kernel path (`use_optimized_inference`, weights stay FP8 and matmuls run on `torch._scaled_mm`; needs compute capability 8.9+, i.e. RTX 40-series / Hopper), and any layer still left compressed is adopted into `QuantLinear` (fp8 weight + per-channel scale, dequantized per forward) before the decompress hook can fire. If an older transformers dequantized at load instead, the weights are re-quantized on the fly. The checkpoint's *ignore list* is also widened with regexes so the vision tower / projector / lm_head stay float on every transformers version. GPTQ/AWQ need their own kernels. |
| `bf16` / `fp16` | cast a float checkpoint. Llama-family models were trained in bf16; fp16 can overflow. |
| `fp8_e4m3fn (on the fly)` / `int8 (on the fly)` | load bf16, then replace every eligible `nn.Linear` in the language model with a per-output-channel quantized weight (1 byte) + float32 scale, dequantized at compute time. Same idea as ComfyUI's fp8 diffusion loading: storage-only, works on any GPU. ~8.5 GB for an 8B model. `keep_vision_float` (default on) leaves the vision tower, projector and lm_head in bf16. |

Quantization runs on the GPU layer by layer (a bf16 8B model needs ~17 GB of **RAM** briefly while loading).

## VRAM behaviour

* The generate node calls `load_models_gpu([...], force_full_load=True)` before every run, so a model ComfyUI partially evicted is brought back whole.
* `after_run = offload to ram` unloads immediately (useful right before a big diffusion step in the same workflow). Otherwise the model stays resident until something else needs the space.
* The loader's output is cached by ComfyUI like any node output; changing the folder's files (`IS_CHANGED` hashes config + weight file names/sizes/mtimes) reloads it.

## prompt / image token handling

Templates differ: JoyCaption's Llama template inserts its own image token and only accepts string content; Qwen-VL / standard LLaVA expect `[{"type":"image"},{"type":"text"}]`. `generate.render_chat` tries string content, then structured content, and keeps the first render that contains the processor's image token; if neither does, the token is prepended to the user text.

## files

```
quant.py      QuantLinear + convert_linears (fp8_e4m3fn / int8, per-channel)
loader.py     discovery, compressed-tensors ignore shim, VLMContainer/ModelPatcher wrap, UmbraeVLM
generate.py   render_chat, strip_thinking, generate_text
prompts.py    JoyCaption styles / lengths / extra options (from fancyfeast's JoyCaption prompt set)
nodes.py      the four nodes (+ registers the scan route)
../../web/umbrae_vlm.js   loader dropdown refresh from external_root
```

Not done yet / ideas: `torch._scaled_mm` fast path for the *on-the-fly* FP8 mode too (compressed-tensors FP8 checkpoints already get it through transformers), int4 packed weights, streaming output.

Load timing: the log prints per-phase times (`from_pretrained`, compressed-tensors handling, processor). A cold read of ~10 GB from a hard disk dominates the first load of a session; after that the model stays in RAM/VRAM under ComfyUI's management and later runs skip loading entirely.
