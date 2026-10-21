"""Optional cleanup pass with a small local LLM (mlx-lm). Off by default; adds ~0.5 to 1 s."""

from __future__ import annotations

import logging
import re
from typing import Callable

log = logging.getLogger("voz.polish")

INSTRUCTIONS = (
    "You clean up dictated text. Fix punctuation and capitalization, drop filler words and false starts, "
    "and keep the speaker's own words, order, and meaning. Never add information, never answer or reply to "
    "the text, never translate. Spell these names exactly as written: {words}. "
    "Return only the cleaned text, nothing else."
)


def build_prompt(text: str, words: list[str], examples: list[str]) -> str:
    parts = [INSTRUCTIONS.format(words=", ".join(words) if words else "none")]
    if examples:
        parts.append("Examples of how this person's finished text usually reads:\n" + "\n".join(f"- {e}" for e in examples[:20]))
    parts.append("Dictated text:\n" + text)
    return "\n\n".join(parts)


def _tidy_output(out: str) -> str:
    out = out.strip()
    out = out.split("\n\n", 1)[0].strip()  # anything after a blank line is commentary
    out = re.sub(r'^(["\'`“”‘’]+)|(["\'`“”‘’]+)$', "", out).strip()
    out = re.sub(r"^(cleaned text|output|text)\s*:\s*", "", out, flags=re.I).strip()
    return out


class Polisher:
    def __init__(self, model_id: str = "mlx-community/Qwen2.5-1.5B-Instruct-4bit",
                 generate: Callable[[str], str] | None = None):
        self.model_id = model_id
        self._generate = generate
        self._model = None
        self._tokenizer = None

    @staticmethod
    def available() -> bool:
        import importlib.util

        return importlib.util.find_spec("mlx_lm") is not None

    def warm(self) -> None:
        """Load (and on first use download) the model now, so the first dictation does not wait."""
        if self._generate is None and self._model is None:
            from mlx_lm import load

            log.info("loading %s", self.model_id)
            self._model, self._tokenizer = load(self.model_id)

    def _default_generate(self, prompt: str) -> str:
        from mlx_lm import generate, load
        from mlx_lm.sample_utils import make_sampler

        if self._model is None:
            log.info("loading %s", self.model_id)
            self._model, self._tokenizer = load(self.model_id)
        chat = self._tokenizer.apply_chat_template(
            [{"role": "user", "content": prompt}], add_generation_prompt=True, tokenize=False)
        max_tokens = min(600, 40 + 2 * len(prompt.split()))
        return generate(self._model, self._tokenizer, prompt=chat, max_tokens=max_tokens,
                        sampler=make_sampler(temp=0.0), verbose=False)

    def polish(self, text: str, words: list[str], examples: list[str]) -> str:
        gen = self._generate or self._default_generate
        try:
            out = _tidy_output(gen(build_prompt(text, words, examples)))
        except Exception:
            log.exception("polish failed; using the unpolished text")
            return text
        if not out:
            return text
        ratio = len(out) / max(len(text), 1)
        if ratio > 1.4 or ratio < 0.6:
            log.warning("polish output length off (%.2fx); using the unpolished text", ratio)
            return text
        if "\n" in text and "\n" not in out:
            return text
        return out
