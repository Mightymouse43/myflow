"""Pure-text cleanup: fillers, stutters, spoken commands, tidy casing and punctuation."""

from __future__ import annotations

import re

from .config import Config

_PUNCT = ",.!?;:"
_SENTENCE_END = ".!?"
# Pairs people say on purpose; never collapse these.
_REPEAT_ALLOWLIST = {"bye", "very", "no", "so"}
# Nothing goes between these and the next word: they open something.
_OPENERS = set("([{\"'\u201c\u2018\u00ab")


def _filler_pattern(fillers: list[str]) -> re.Pattern | None:
    if not fillers:
        return None
    alts = sorted((re.escape(f.strip()).replace(r"\ ", r"\s+") for f in fillers if f.strip()),
                  key=len, reverse=True)
    if not alts:
        return None
    # pre: start of text, or preceded by whitespace (zero-width), or a comma we swallow.
    # post: punctuation glued to the filler. Must be followed by whitespace or the end.
    return re.compile(
        rf"(?i)(?P<pre>(?:^|(?<=\s)|,\s+))(?P<f>{'|'.join(alts)})(?P<post>[{re.escape(_PUNCT)}]*)(?=\s|$)"
    )


def remove_fillers(text: str, fillers: list[str]) -> str:
    pat = _filler_pattern(fillers)
    if not text or pat is None:
        return text
    multiword = {f.strip().lower() for f in fillers if " " in f.strip()}

    def repl(m: re.Match) -> str:
        pre, f, post = m.group("pre"), m.group("f"), m.group("post")
        bracketed = pre.startswith(",") or bool(post) or m.start() == 0
        if re.sub(r"\s+", " ", f.lower()) in multiword and not bracketed:
            return m.group(0)  # "do you know the way" is a real phrase
        if any(c in _SENTENCE_END for c in post):
            # keep the sentence ending the filler was carrying
            return next(c for c in post if c in _SENTENCE_END)
        return ""

    out = pat.sub(repl, text)
    out = re.sub(r"\s+([" + re.escape(_PUNCT) + "])", r"\1", out)  # "it ." -> "it."
    out = re.sub(r",([.!?])", r"\1", out)                          # "it,." -> "it."
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    if text[:1].isupper() and out[:1].islower():
        out = out[0].upper() + out[1:]
    return out


def collapse_repeats(text: str) -> str:
    if not text:
        return text
    tokens = text.split()
    out: list[str] = []
    for tok in tokens:
        core = tok.strip(_PUNCT).lower()
        if out and core and core not in _REPEAT_ALLOWLIST and out[-1].strip(_PUNCT).lower() == core:
            out[-1] = tok  # keep the later token; it carries the punctuation that matters
            continue
        out.append(tok)
    return " ".join(out)


_NEWLINE_CMD = re.compile(r"(?i),?\s*\bnew\s+(?P<kind>line|paragraph)\b[,.!]?[ \t]*")


def apply_spoken_commands(text: str) -> str:
    def repl(m: re.Match) -> str:
        return "\n" if m.group("kind").lower() == "line" else "\n\n"

    out = _NEWLINE_CMD.sub(repl, text)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n[ \t]+", "\n", out)
    return out.strip()


def tidy(text: str) -> str:
    out = re.sub(r"[ \t]+", " ", text).strip()
    out = re.sub(r"\s+([" + re.escape(_PUNCT) + "])", r"\1", out)
    out = re.sub(r",([.!?])", r"\1", out)
    out = re.sub(r"[ \t]*\n[ \t]*", "\n", out)
    if not out:
        return out
    # Capitalise the first letter and the first letter after a sentence ending.
    out = out[0].upper() + out[1:]
    out = re.sub(r"([.!?])(\s+)([a-z])", lambda m: m.group(1) + m.group(2) + m.group(3).upper(), out)
    words = out.split()
    if len(words) >= 3 and out[-1].isalnum():
        out += "."
    return out


def clean(text: str, cfg: Config) -> str:
    out = text or ""
    if cfg.remove_fillers:
        out = remove_fillers(out, cfg.fillers)
    out = collapse_repeats(out)
    if cfg.spoken_commands:
        out = apply_spoken_commands(out)
    return tidy(out)


def join_prefix(prev: str | None, text: str) -> str:
    """What to put between the text already before the caret and a new dictation.

    A space, unless the field is empty, the caret sits after whitespace or an opening bracket/quote, the new
    text starts with its own whitespace (a spoken "new line"), or the caret context is unknown (None)."""
    if not text or text[0].isspace() or not prev:
        return ""
    if prev.isspace() or prev in _OPENERS:
        return ""
    return " "
