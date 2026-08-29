"""
Vocabulary derived from the gold corpus, used to spot invented words.

A hardcoded blocklist ("annuh", "pahamilla", "alaiyaa") only catches the exact
garbage already seen. Checking against the vocabulary the gold pairs actually
use generalises to invented words nobody has reported yet.

Deliberately conservative: a single unfamiliar token is normal (the corpus is
269 pairs, not a dictionary), so callers should treat one unknown word as a
soft signal and several as evidence the model is producing non-words.
"""
from __future__ import annotations

import json
import re
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import TANGLISH_GOLD_PAIRS_PATH  # noqa: E402

_TOKEN_RE = re.compile(r"[a-z]+")

_lock = threading.Lock()
_cache: dict[str, frozenset[str]] = {}
_cache_mtime: float | None = None

# Function words and loanwords that are correct Tanglish but may be absent from
# the corpus purely by chance.
_ALWAYS_KNOWN = frozenset(
    {
        "a", "an", "and", "at", "by", "for", "in", "is", "it", "of", "on", "or",
        "so", "the", "to", "up", "ok", "okay", "yes", "no", "please", "sorry",
        "anna", "annae", "uncle", "aunty", "sir", "madam", "boss", "thambi",
        "naan", "naa", "naanga", "namma", "neenga", "unga", "avaru", "avanga",
        "adhu", "idhu", "andha", "indha", "edhu", "enna", "eppo", "eppadi",
        "ippo", "appo", "innum", "konjam", "romba", "dhaan", "illa", "illana",
        "aana", "aanaa", "ithu", "athu", "nu", "la", "ku", "oda", "kitta",
        "um", "aa", "ah", "va", "e",
    }
)


def _load() -> None:
    global _cache_mtime
    path = Path(TANGLISH_GOLD_PAIRS_PATH)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    if _cache and _cache_mtime == mtime:
        return
    tanglish: set[str] = set()
    english: set[str] = set()
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rows = []
    for row in rows:
        tanglish.update(_TOKEN_RE.findall((row.get("tanglish") or "").lower()))
        english.update(_TOKEN_RE.findall((row.get("english") or "").lower()))
    _cache["tanglish"] = frozenset(tanglish | _ALWAYS_KNOWN)
    _cache["english"] = frozenset(english)
    _cache_mtime = mtime


def gold_vocabulary() -> frozenset[str]:
    """Every Tanglish token used by a human-verified gold translation."""
    with _lock:
        _load()
        return _cache["tanglish"]


def english_vocabulary() -> frozenset[str]:
    """Every English token appearing on the source side of the gold corpus."""
    with _lock:
        _load()
        return _cache["english"]


def unknown_tokens(output: str, source: str = "") -> list[str]:
    """Tokens in `output` that match neither the gold corpus nor the source.

    Tokens carried over from the English source are always acceptable — the
    whole point of Tanglish is keeping the English words a Chennai speaker
    would say in English.
    """
    known = gold_vocabulary()
    english = english_vocabulary()
    src_tokens = set(_TOKEN_RE.findall((source or "").lower()))
    seen: list[str] = []
    for tok in _TOKEN_RE.findall((output or "").lower()):
        if len(tok) < 3:
            continue
        if tok in known or tok in english or tok in src_tokens:
            continue
        # Hyphenated Tanglish splits into stem + suffix; accept a known stem.
        if any(tok.startswith(stem) for stem in ("pann", "sollu", "iruk", "vandh")):
            continue
        if tok not in seen:
            seen.append(tok)
    return seen
