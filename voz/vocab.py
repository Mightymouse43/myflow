"""Personal dictionary: exact and sound-alike replacement, plus learning from corrections."""

from __future__ import annotations

import difflib
import itertools
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import jellyfish
from rapidfuzz import fuzz

from . import config

_SYSTEM_WORDS = Path("/usr/share/dict/words")
_DIGIT_WORDS = {
    "0": ["zero", "oh"], "1": ["one", "won"], "2": ["two", "to", "too"], "3": ["three"],
    "4": ["four", "for"], "5": ["five"], "6": ["six"], "7": ["seven"], "8": ["eight", "ate"],
    "9": ["nine"],
}
_TOKEN = re.compile(r"^(\W*)(.*?)(\W*)$", re.S)
_SUFFIXES = (("ies", "y"), ("es", ""), ("s", ""), ("ed", ""), ("d", ""), ("ing", ""), ("ing", "e"),
             ("er", ""), ("est", ""), ("ly", ""))


@dataclass(frozen=True)
class Rule:
    heard: str | None
    canonical: str


def parse_dictionary(text: str) -> list[Rule]:
    rules: list[Rule] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=>" in line:
            heard, canonical = (s.strip() for s in line.split("=>", 1))
            if heard and canonical:
                rules.append(Rule(heard, canonical))
        else:
            rules.append(Rule(None, line))
    return rules


# ---- English word knowledge -------------------------------------------------------

@lru_cache(maxsize=1)
def _word_lists() -> tuple[frozenset[str], frozenset[str]]:
    """(common, everything) from the system dictionary, lowercased.

    The system list keeps proper names capitalised (Claude, Jennifer, Monday) and ordinary words in
    lowercase, so "common" = listed in lowercase = a real English word that must never be rewritten.
    """
    try:
        lines = [l.strip() for l in _SYSTEM_WORDS.read_text(errors="ignore").splitlines()]
    except OSError:
        return frozenset(), frozenset()
    common = frozenset(w for w in lines if w and w[0].islower())
    everything = frozenset(w.lower() for w in lines if w)
    return common, everything


def known_words() -> frozenset[str]:
    """Every word the system dictionary knows, names included, lowercased."""
    return _word_lists()[1]


def common_words() -> frozenset[str]:
    return _word_lists()[0]


def _stems(word: str) -> set[str]:
    w = word.lower()
    out = {w}
    for suf, rep in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            out.add(w[: -len(suf)] + rep)
    return out


def is_english_word(word: str) -> bool:
    """True for anything the system list knows in any simple inflection (parked, sedans, whispers)."""
    return any(s in known_words() for s in _stems(word))


def is_common_word(word: str) -> bool:
    """True for ordinary lowercase English (instantly, clay, shorts, wild), not for names."""
    return any(s in common_words() for s in _stems(word))


# ---- sound-alike scoring -----------------------------------------------------------

def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _variants(canonical: str) -> list[str]:
    """Normalised spellings a listener might produce, e.g. Tenants2Guest -> tenantstoguest."""
    base = _norm(canonical)
    digits = [c for c in base if c.isdigit()]
    if not digits:
        return [base]
    choices = [_DIGIT_WORDS.get(d, [d]) + [d] for d in digits]
    out = [base]
    for combo in itertools.islice(itertools.product(*choices), 16):
        it = iter(combo)
        out.append("".join(next(it) if c.isdigit() else c for c in base))
    return list(dict.fromkeys(out))


def _score(window: str, variants: list[str], multiword: bool) -> float:
    """0 when the window does not sound like any variant, else a similarity in [88, 100]."""
    if len(window) < (6 if multiword else 4):
        return 0.0
    best = 0.0
    for v in variants:
        if window == v:
            return 100.0
        if multiword and abs(len(window) - len(v)) > 3:
            continue
        ratio = fuzz.ratio(window, v)
        if ratio >= 88:
            best = max(best, ratio)
            continue
        code = jellyfish.metaphone(window)
        if code and code == jellyfish.metaphone(v):
            if multiword and len(code) >= 4 and ratio >= 70:
                best = max(best, 88.0)
            elif not multiword and len(code) >= 3 and ratio >= 80:
                best = max(best, 88.0)
    return best


def _sounds_like(window: str, variants: list[str], multiword: bool) -> bool:
    return _score(window, variants, multiword) > 0


def _boundary_regex(phrase: str) -> re.Pattern:
    return re.compile(r"(?i)(?<!\w)" + re.escape(phrase) + r"(?!\w)")


class Vocab:
    def __init__(self, rules: list[Rule], learned: list[Rule]):
        self.rules = rules
        self.learned = learned

    # ---- construction -------------------------------------------------
    @classmethod
    def from_text(cls, text: str) -> "Vocab":
        return cls(parse_dictionary(text), [])

    @classmethod
    def load(cls) -> "Vocab":
        rules = parse_dictionary(config.DICTIONARY_PATH.read_text()) if config.DICTIONARY_PATH.exists() else []
        learned: list[Rule] = []
        if config.LEARNED_PATH.exists():
            try:
                learned = [Rule(d["heard"], d["canonical"]) for d in json.loads(config.LEARNED_PATH.read_text())]
            except (ValueError, KeyError, TypeError):
                learned = []
        return cls(rules, learned)

    # ---- queries --------------------------------------------------------
    def words(self) -> list[str]:
        return list(dict.fromkeys(r.canonical for r in self.rules + self.learned))

    def apply(self, text: str) -> str:
        if not text:
            return text
        out = text
        # 1. exact replacements: explicit "heard => Word" first, then the words themselves (fixes casing).
        #    A plain entry that is an ordinary English word (instantly, clay, shorts) is left alone;
        #    only an explicit mapping may rewrite those.
        for r in self.learned + self.rules:
            if r.heard is None and " " not in r.canonical and is_common_word(r.canonical):
                continue
            out = _boundary_regex(r.heard or r.canonical).sub(lambda m, c=r.canonical: c, out)
        # 2. sound-alike replacements on 1 to 3 word windows
        return "\n".join(self._fuzzy_line(line) for line in out.split("\n"))

    def _fuzzy_line(self, line: str) -> str:
        toks = line.split(" ")
        parts = [_TOKEN.match(t).groups() for t in toks]
        canon = sorted(self.words(), key=len, reverse=True)
        if not canon:
            return line
        variants = {c: _variants(c) for c in canon}
        canon_norms = {_norm(c) for c in canon}
        canon_phrases = [re.compile(r"(?<!\w)" + re.escape(c.lower()) + r"(?!\w)") for c in canon]
        i, out = 0, []
        while i < len(parts):
            candidates: list[tuple[float, int, str]] = []
            for n in (1, 2, 3):
                if i + n > len(parts):
                    break
                cores = [p[1] for p in parts[i:i + n]]
                if any(not c for c in cores):
                    break
                if any(_norm(c0) in canon_norms for c0 in cores):
                    break  # already holds a dictionary word
                joined = " ".join(cores)
                if n > 1 and any(p.search(joined.lower()) for p in canon_phrases):
                    break  # already holds a dictionary phrase; do not swallow the words around it
                if n == 1 and is_english_word(cores[0]):
                    continue  # real English stays English
                window = _norm(joined)
                for c in canon:
                    if window == _norm(c):
                        continue
                    s = _score(window, variants[c], multiword=n > 1)
                    if s:
                        candidates.append((s, -n, c))
            if candidates:
                s, neg_n, c = max(candidates)
                n = -neg_n
                out.append(parts[i][0] + c + parts[i + n - 1][2])
                i += n
            else:
                out.append(toks[i])
                i += 1
        return " ".join(out)

    # ---- learning -------------------------------------------------------
    def add_word(self, word: str) -> None:
        word = word.strip()
        if not word or word in self.words():
            return
        self.rules.append(Rule(None, word))
        config.VOZ_DIR.mkdir(parents=True, exist_ok=True)
        if not config.DICTIONARY_PATH.exists():
            config.DICTIONARY_PATH.write_text(config.DICTIONARY_HEADER)
        with config.DICTIONARY_PATH.open("a") as f:
            f.write(word + "\n")

    def _save_learned(self) -> None:
        config.VOZ_DIR.mkdir(parents=True, exist_ok=True)
        config.LEARNED_PATH.write_text(json.dumps(
            [{"heard": r.heard, "canonical": r.canonical} for r in self.learned], indent=1))

    def forget_learned(self) -> None:
        self.learned = []
        config.LEARNED_PATH.unlink(missing_ok=True)

    def _plausible_mishearing(self, heard: str, canonical: str) -> bool:
        """Only mishearings become rules; rewording ("good" -> "great") must not."""
        dictionary = {w.lower() for w in self.words()}
        if any(t.lower() in dictionary for t in canonical.split()):
            return True
        if any(not is_english_word(t) for t in heard.split()):
            return True
        if _norm(heard) == _norm(canonical):
            return True
        return _sounds_like(_norm(heard), _variants(canonical), multiword=(" " in heard or " " in canonical))

    def learn(self, raw: str, corrected: str) -> list[Rule]:
        """Turn an edit of a dictation into rules. Returns the rules added this call."""
        a, b = raw.split(), corrected.split()
        key = lambda t: _TOKEN.match(t).group(2).lower()
        sm = difflib.SequenceMatcher(a=[key(t) for t in a], b=[key(t) for t in b], autojunk=False)
        added: list[Rule] = []
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op != "replace":
                continue
            heard = " ".join(_TOKEN.match(t).group(2) for t in a[i1:i2]).strip()
            canonical = " ".join(_TOKEN.match(t).group(2) for t in b[j1:j2]).strip()
            if not heard or not canonical or heard == canonical:
                continue
            if not self._plausible_mishearing(heard, canonical):
                continue
            rule = Rule(heard.lower(), canonical)
            if rule not in self.learned:
                self.learned.append(rule)
                added.append(rule)
        if added:
            self._save_learned()
        # New names (capitalised, not sentence-initial, unknown to the system list) join the dictionary.
        for j, tok in enumerate(b):
            core = _TOKEN.match(tok).group(2)
            sentence_start = j == 0 or b[j - 1].rstrip()[-1:] in ".!?"
            if core[:1].isupper() and not sentence_start and not is_english_word(core):
                self.add_word(core)
        return added
