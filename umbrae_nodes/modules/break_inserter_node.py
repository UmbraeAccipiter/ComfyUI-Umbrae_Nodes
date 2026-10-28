"""
break_inserter_node.py — umbrae_nodes
Token-aware [BREAK] inserter for ComfyUI CLIP text encoders.

Splits a prompt into lines, counts tokens per line using the CLIP tokenizer,
and inserts [BREAK] markers between lines so no segment exceeds token_limit.
Safe to re-run — strips existing [BREAK] markers before processing.
"""

from transformers import CLIPTokenizer


class BreakInserter:
    """
    Inserts [BREAK] markers into a prompt string at token-safe boundaries.

    Each line in the input is treated as an atomic unit — [BREAK] is only
    inserted between lines, never inside one. If a single line exceeds
    token_limit on its own it is output as its own block so content is
    preserved rather than silently dropped.

    Load the CLIP tokenizer once and cache it on the class so it does not
    reload on every generation.
    """

    _tokenizer = None

    CATEGORY = "umbrae/text"
    FUNCTION = "insert_breaks"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)

    @classmethod
    def _get_tokenizer(cls) -> CLIPTokenizer:
        if cls._tokenizer is None:
            cls._tokenizer = CLIPTokenizer.from_pretrained(
                "openai/clip-vit-large-patch14"
            )
        return cls._tokenizer

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {
                    "multiline": True,
                    "tooltip": (
                        "Prompt text where each line is an atomic group. "
                        "[BREAK] markers are stripped and reinserted automatically."
                    ),
                }),
                "token_limit": ("INT", {
                    "default": 75,
                    "min": 10,
                    "max": 512,
                    "step": 1,
                    "tooltip": (
                        "Maximum tokens per segment. "
                        "SDXL/Danbooru: 75, Illustrious/NoobAI: 248, Flux/Qwen: 512."
                    ),
                }),
            },
        }

    def _count_tokens(self, text: str) -> int:
        tokenizer = self._get_tokenizer()
        # encode without special tokens so we count only content tokens
        tokens = tokenizer.encode(text, add_special_tokens=False)
        return len(tokens)

    def insert_breaks(self, text: str, token_limit: int):
        # Strip existing [BREAK] markers so this is safe to re-run
        cleaned = text.replace("[BREAK]", "").replace("[break]", "")

        # Split into lines, drop blank lines
        lines = [l.strip() for l in cleaned.splitlines() if l.strip()]

        blocks = []
        current_block = []
        current_tokens = 0

        for line in lines:
            line_tokens = self._count_tokens(line)

            if line_tokens > token_limit:
                # Single line exceeds limit — flush current block first,
                # then output the oversized line as its own block with a warning
                if current_block:
                    blocks.append("\n".join(current_block))
                    current_block = []
                    current_tokens = 0
                blocks.append(line)
                print(
                    f"[BreakInserter] WARNING: line exceeds token_limit "
                    f"({line_tokens} > {token_limit}): {line[:60]}..."
                )
                continue

            if current_tokens + line_tokens > token_limit:
                # Adding this line would exceed the limit — flush and start new block
                blocks.append("\n".join(current_block))
                current_block = [line]
                current_tokens = line_tokens
            else:
                current_block.append(line)
                current_tokens += line_tokens

        # Flush any remaining lines
        if current_block:
            blocks.append("\n".join(current_block))

        result = "\n[BREAK]\n".join(blocks)

        print(
            f"[BreakInserter] {len(lines)} line(s) → "
            f"{len(blocks)} segment(s), limit={token_limit}"
        )

        return (result,)


NODE_CLASS_MAPPINGS = {
    "BreakInserter": BreakInserter,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "BreakInserter": "break inserter [umbrae]",
}
