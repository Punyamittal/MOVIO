"""
Load pronunciation phrase rules from tanglish_gold_pairs.json.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]*|\d+")
_GOLD_PATH = Path(__file__).resolve().parent / "tanglish_gold_pairs.json"


def _normalize_phrase_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


@lru_cache(maxsize=1)
def load_gold_tanglish_phrases() -> tuple[tuple[str, str], ...]:
    if not _GOLD_PATH.exists():
        return ()
    rows = json.loads(_GOLD_PATH.read_text(encoding="utf-8"))
    from normalization.pronunciation_rules import apply_token_phonetics_only

    seen: set[str] = set()
    phrases: list[tuple[str, str]] = []
    for row in rows:
        tanglish = (row.get("tanglish") or "").strip()
        if not tanglish or _TAMIL_RE.search(tanglish):
            continue
        key = _normalize_phrase_key(tanglish)
        if key in seen:
            continue
        seen.add(key)
        phonetic = apply_token_phonetics_only(tanglish)
        phrases.append((tanglish, phonetic))

    phrases.sort(key=lambda p: len(p[0]), reverse=True)
    return tuple(phrases)


def mine_gold_tokens(min_count: int = 3) -> dict[str, int]:
    if not _GOLD_PATH.exists():
        return {}
    rows = json.loads(_GOLD_PATH.read_text(encoding="utf-8"))
    counts: dict[str, int] = {}
    for row in rows:
        tanglish = (row.get("tanglish") or "").strip().lower()
        for tok in _WORD_RE.findall(tanglish):
            if len(tok) < 2:
                continue
            counts[tok] = counts.get(tok, 0) + 1
    return {k: v for k, v in counts.items() if v >= min_count}
