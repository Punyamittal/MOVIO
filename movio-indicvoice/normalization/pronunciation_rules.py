"""
Chennai Tanglish colloquial + phonetic rules for TTS.

Layers (apply in order for phonetic pass):
  1. Gold tanglish phrases (from tanglish_gold_pairs.json) — longest match
  2. Lexicon phrases + gold suffix patterns
  3. Token rules (gold_phonetic_patterns.json overrides lexicon tokens)

Colloquial written form is separate (all backends).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Callable

_TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")
_LEXICON_PATH = Path(__file__).with_name("pronunciation_lexicon.json")
_PATTERNS_PATH = Path(__file__).with_name("gold_phonetic_patterns.json")

Rule = tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]]


def _rules(raw: list[tuple[str, str | Callable[[re.Match[str]], str], int]]) -> list[Rule]:
    return [(re.compile(pat, flags), repl) for pat, repl, flags in raw]


def _apply_rules(text: str, rules: list[Rule]) -> str:
    out = text or ""
    for pattern, repl in rules:
        out = pattern.sub(repl, out)
    return out


def _token_pattern(token: str) -> str:
    escaped = re.escape(token.strip().lower())
    escaped = escaped.replace(r"\ ", r"\s+")
    return rf"(?<![\w-]){escaped}(?![\w-])"


def strip_tamil_script(text: str) -> str:
    return _TAMIL_RE.sub(" ", text or "")


def flatten_lexicon_entries(data: dict | None) -> dict[str, str]:
    """Map token → speak-as spelling for deterministic_normalizer.apply_lexicon."""
    if not data:
        return {}
    out: dict[str, str] = {}
    for row in data.get("tokens", []):
        tok = (row.get("token") or "").strip()
        ph = (row.get("phonetic") or "").strip()
        if tok and ph:
            out[tok] = ph.replace("-", "")
    for row in _load_pattern_file().get("tokens", []):
        tok = (row.get("token") or "").strip()
        ph = (row.get("compact_phonetic") or row.get("phonetic") or "").strip()
        if tok and ph:
            out[tok] = ph.replace("-", "")
    for key, val in data.items():
        if key in ("version", "phrases", "tokens", "phonological_notes"):
            continue
        if isinstance(val, str) and val.strip():
            out[str(key)] = val.strip()
    return out


@lru_cache(maxsize=1)
def load_pronunciation_lexicon() -> dict:
    data = json.loads(_LEXICON_PATH.read_text(encoding="utf-8"))
    for row in data.get("tokens", []):
        if _TAMIL_RE.search(str(row.get("token", ""))):
            raise ValueError(f"Tamil script in token entry: {row.get('token')!r}")
    for row in data.get("phrases", []):
        if _TAMIL_RE.search(str(row.get("tanglish", ""))):
            raise ValueError(f"Tamil script in phrase entry: {row.get('id')!r}")
    return data


@lru_cache(maxsize=1)
def _load_pattern_file() -> dict:
    if not _PATTERNS_PATH.exists():
        return {"tokens": [], "suffix_patterns": []}
    return json.loads(_PATTERNS_PATH.read_text(encoding="utf-8"))


def _phonetic_value(row: dict, *, compact: bool) -> str:
    if compact:
        return (
            (row.get("compact_phonetic") or row.get("phonetic") or "")
            .strip()
            .replace("-", "")
        )
    return (row.get("hyphenated") or row.get("phonetic") or "").strip()


@lru_cache(maxsize=2)
def _token_phonetic_rules(compact: bool) -> list[Rule]:
    raw: list[tuple[str, str, int]] = []
    seen: set[str] = set()

    for row in _load_pattern_file().get("tokens", []):
        token = (row.get("token") or "").strip().lower()
        phonetic = _phonetic_value(row, compact=compact)
        if token and phonetic and token not in seen:
            seen.add(token)
            raw.append((_token_pattern(token), phonetic, re.I))

    data = load_pronunciation_lexicon()
    tokens = sorted(data.get("tokens", []), key=lambda r: len(str(r.get("token", ""))), reverse=True)
    for row in tokens:
        token = (row.get("token") or "").strip().lower()
        phonetic = (row.get("phonetic") or "").strip()
        if not token or not phonetic or token in seen:
            continue
        seen.add(token)
        if compact:
            phonetic = phonetic.replace("-", "")
        raw.append((_token_pattern(token), phonetic, re.I))

    return _rules(raw)


def apply_token_phonetics_only(text: str, *, compact: bool = False) -> str:
    """Token-level phonetics without phrase rules (used to precompute gold phrases)."""
    out = strip_tamil_script(text)
    out = _apply_rules(out, _token_phonetic_rules(compact))
    return re.sub(r"\s{2,}", " ", out).strip()


@lru_cache(maxsize=2)
def _phonetic_rules_full(compact: bool) -> list[Rule]:
    raw: list[tuple[str, str, int]] = []

    # Gold corpus phrases (longest first)
    from normalization.gold_phonetic_loader import load_gold_tanglish_phrases

    for tanglish, phonetic in load_gold_tanglish_phrases():
        ph = phonetic.replace("-", "") if compact else phonetic
        raw.append((_token_pattern(tanglish), ph, re.I))

    data = load_pronunciation_lexicon()
    for row in data.get("phrases", []):
        tanglish = (row.get("tanglish") or "").strip()
        phonetic = (row.get("phonetic") or "").strip()
        if tanglish and phonetic:
            ph = phonetic.replace("-", "") if compact else phonetic
            raw.append((_token_pattern(tanglish), ph, re.I))

    for row in _load_pattern_file().get("suffix_patterns", []):
        pat = (row.get("pattern") or "").strip()
        phonetic = _phonetic_value(row, compact=compact)
        if pat and phonetic:
            raw.append((_token_pattern(pat), phonetic, re.I))

    return _rules(raw) + _token_phonetic_rules(compact)


def clear_pronunciation_cache() -> None:
    load_pronunciation_lexicon.cache_clear()
    _load_pattern_file.cache_clear()
    _token_phonetic_rules.cache_clear()
    _phonetic_rules_full.cache_clear()
    from normalization.gold_phonetic_loader import load_gold_tanglish_phrases

    load_gold_tanglish_phrases.cache_clear()


_COLLOQUIAL_RAW: list[tuple[str, str | Callable[[re.Match[str]], str], int]] = [
    (r"\s+pakkathula\b", " kitta", re.I),
    (r"\s+pakkathule\b", " kitte", re.I),
    (r"\s+pakkathil\b", " kitta", re.I),
    (r"\s+pakkatla\b", " kitta", re.I),
    (r"\s+arukil\b", " kitta", re.I),
    (r"\bbuilding-ngil\b", "building kitta", re.I),
    (r"\bbuilding-ngula\b", "building kitta", re.I),
    (r"\bbuilding-oda\b", "building kitta", re.I),
    (r"-thula\b", "-la", re.I),
    (r"\bwait pannitu irukken\b", "wait pannit iruken", re.I),
    (r"\bwait pannitu irukkaaru\b", "wait pannit irukaaru", re.I),
    (r"\bpannitu irukken\b", "pannit iruken", re.I),
    (r"\bpannitu irukkaaru\b", "pannit irukaaru", re.I),
    (r"\bpannitu irukken-nu\b", "pannit iruken-nu", re.I),
    (r"\bUPI pannitrukken\b", "UPI pannitrukken", re.I),
    (r"\bthirumbunga\b", "thirumbu", re.I),
    (r"\bpoidunga\b", "po", re.I),
    (r"\bedukkalainga\b", "edukka mattengaru", re.I),
    (r"\bporuthukonga\b", "poruthungo", re.I),
    (r"\bporuthunga\b", "poruthungo", re.I),
    (r"\beththanai\b", "ethana", re.I),
    (r"\bgaadi\b", "vandi", re.I),
    (r"\billainga\b", "illa", re.I),
    (r"\birukken\b", "iruken", re.I),
    (r"\bvandhutten\b", "vantutten", re.I),
]

COLLOQUIAL_TANGLISH: list[Rule] = _rules(_COLLOQUIAL_RAW)


def colloquialize_tanglish(text: str) -> str:
    return _apply_rules(text, COLLOQUIAL_TANGLISH)


def phoneticize_tanglish(text: str, *, compact: bool = False) -> str:
    """Add speak-as hints. compact=True for neural TTS (no hyphens)."""
    out = strip_tamil_script(text)
    out = _apply_rules(out, _phonetic_rules_full(compact))
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = re.sub(r"\s+([.,!?])", r"\1", out)
    return out
