"""Language detection with confidence for two-phone routing."""
from __future__ import annotations

from dataclasses import dataclass

from normalization.language_translator import detect_language

# Tokens that strongly suggest Tanglish / Chennai taxi speech
_STRONG_TANGLISH = (
    "la ", " la", "unga ", "ungal ", "vandhu", "irukken", "irukku", "pannunga",
    "sollunga", "saar", "anna", "akka", "otp", "cab", "auto", "parking",
    "omr", "ecr", "guindy", "t nagar", "tnagar", "adyar", "velachery",
    "porur", "tambaram", "airport", "drop", "pickup", "fare",
)


@dataclass
class LangDetectResult:
    language: str  # en | ta | tanglish | unknown | uncertain
    confidence: float  # 0..1
    uncertain: bool

    @property
    def label(self) -> str:
        if self.uncertain or self.language in ("unknown", "uncertain"):
            return "UNCERTAIN"
        return self.language.upper()


def detect_language_confident(text: str) -> LangDetectResult:
    """
    Wrap heuristic detect_language with a confidence score.

    Low-confidence / empty results become UNCERTAIN so the pipeline does not
    invent a wrong translation target.
    """
    raw = (text or "").strip()
    if not raw:
        return LangDetectResult("uncertain", 0.0, True)

    base = detect_language(raw)
    lower = f" {raw.lower()} "
    has_ta = any("\u0b80" <= ch <= "\u0bff" for ch in raw)
    has_latin = any("a" <= ch.lower() <= "z" for ch in raw)
    tokens = [t for t in raw.replace(",", " ").replace(".", " ").split() if t]
    n = len(tokens)

    conf = 0.55
    if base == "tanglish":
        hits = sum(1 for m in _STRONG_TANGLISH if m in lower)
        conf = 0.72 + min(0.2, hits * 0.04)
        if has_ta and has_latin:
            conf = max(conf, 0.85)
    elif base == "ta":
        conf = 0.9 if has_ta and not has_latin else 0.7
    elif base == "en":
        conf = 0.88 if has_latin and not has_ta else 0.65
        # Very short English replies stay confident enough to process
        if n <= 2 and has_latin and not has_ta:
            conf = max(conf, 0.75)
    else:
        conf = 0.25

    # Ambiguous scraps
    if n == 1 and base == "en" and tokens[0].isalpha() and len(tokens[0]) <= 2:
        conf = min(conf, 0.45)
    if base == "unknown":
        conf = 0.15

    uncertain = conf < 0.5 or base in ("unknown",)
    language = "uncertain" if uncertain else base
    return LangDetectResult(language=language, confidence=round(conf, 3), uncertain=uncertain)
