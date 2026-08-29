"""Utterance language classification: ta / en / ta-en / other / unknown."""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dataset_pipeline.schema import LanguageLabel

_TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_TANGLISH_MARKERS = (
    "la ", " la", "unga ", "vandhu", "irukken", "irukku", "pannunga",
    "sollunga", "saar", "enna", "illa", "aana", "nu ", "ku ",
)


def classify_language(text: str) -> tuple[LanguageLabel, bool]:
    """
    Returns (label, code_switching).
    ta-en is the valuable Chennai code-switch class — never auto-discarded.
    """
    t = (text or "").strip()
    if not t:
        return "unknown", False
    has_ta = bool(_TAMIL_RE.search(t))
    has_latin = bool(_LATIN_RE.search(t))
    lower = f" {t.lower()} "
    markers = sum(1 for m in _TANGLISH_MARKERS if m in lower)

    if has_ta and has_latin:
        return "ta-en", True
    if markers >= 1 and has_latin:
        return "ta-en", True
    if has_ta and not has_latin:
        return "ta", False
    if has_latin and not has_ta:
        # Could still be Tanglish Latin-only
        if markers >= 2:
            return "ta-en", True
        return "en", False
    return "other", False
