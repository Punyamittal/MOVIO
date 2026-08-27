"""
Make text speakable for Latin/English TTS engines (esp. Windows SAPI).

English OS voices letter-spell unknown Tanglish tokens and skip/mangle
Tamil script. This module:
  1. Coerces pure Tamil-script speak-as to English when no Indic OS voice
  2. Keeps Tanglish as Latin code-mix (phoneticized) — do NOT translate away
  3. Filters out Tamil-script lexicon replacements for English-only voices
"""
from __future__ import annotations

import re

_TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")

# Backends that only handle Latin/English reliably (unless Indic OS voice installed)
LATIN_ONLY_BACKENDS = frozenset({"win_sapi", "sapi", "turbo", "local"})

# Residual Tanglish → approximate English syllables (last resort)
_PHONETIC_TANGLISH = [
    (re.compile(r"\bvandhuruvaanga\b", re.I), "van dhu ru vaan ga"),
    (re.compile(r"\bvandhuruvaan\b", re.I), "van dhu ru vaan"),
    (re.compile(r"\bpannunga\b", re.I), "pa nun ga"),
    (re.compile(r"\bpannanum\b", re.I), "pa na num"),
    (re.compile(r"\bpanni\b", re.I), "pan ni"),
    (re.compile(r"\birukku\b", re.I), "i ruk ku"),
    (re.compile(r"\birukken\b", re.I), "i ruk ken"),
    (re.compile(r"\birundhu\b", re.I), "i run dhu"),
    (re.compile(r"\bunga\b", re.I), "oon ga"),
    (re.compile(r"\bnaan\b", re.I), "naan"),
    (re.compile(r"\bvaruthu\b", re.I), "va ru thu"),
    (re.compile(r"\bvarum\b", re.I), "va rum"),
    (re.compile(r"\baagiruchu\b", re.I), "aa gi ru chu"),
    (re.compile(r"\baagum\b", re.I), "aa gum"),
    (re.compile(r"\baavaaru\b", re.I), "aa vaa ru"),
    (re.compile(r"\bsollunga\b", re.I), "sol lun ga"),
    (re.compile(r"\bvenum\b", re.I), "ve num"),
    (re.compile(r"\bpannitu\b", re.I), "pan ni tu"),
    (re.compile(r"\bwait\s+pannitu\b", re.I), "waiting"),
    (re.compile(r"\bla\b", re.I), ""),
    (re.compile(r"\bah\b", re.I), ""),
    (re.compile(r"\bku\b", re.I), "koo"),
    (re.compile(r"\bnu\b", re.I), ""),
]


def is_latin_only_backend(backend_name: str | None) -> bool:
    return (backend_name or "").lower().strip() in LATIN_ONLY_BACKENDS


def resolve_speak_target(
    backend_name: str | None,
    requested_target: str,
    detected_lang: str,
    *,
    has_indic_os_voice: bool = False,
) -> str:
    """
    Speak-as for Latin-only backends:
      - Tanglish stays Tanglish (Latin code-mix + phonetic pass)
      - Pure Tamil script → English only when no Indic OS voice is installed
    """
    tgt = (requested_target or "tanglish").lower().strip()
    if not is_latin_only_backend(backend_name):
        return tgt
    if has_indic_os_voice:
        return tgt
    # English-only OS voice: keep Tanglish Latin; only rewrite literary Tamil
    if tgt in ("ta", "tamil", "ta-in"):
        return "en"
    if tgt in ("auto", "none", "off") and detected_lang == "ta":
        return "en"
    return tgt


def latin_safe_lexicon(lexicon: dict[str, str] | None) -> dict[str, str]:
    """Drop Tamil-script pronunciations — English SAPI cannot read them."""
    if not lexicon:
        return {}
    out: dict[str, str] = {}
    for key, val in lexicon.items():
        if str(key).startswith("_"):
            continue
        s = str(val or "").strip()
        if not s:
            continue
        if _TAMIL_RE.search(s):
            continue
        out[key] = s
    return out


def strip_tamil_script(text: str) -> str:
    """Remove leftover Tamil characters that English voices cannot speak."""
    return _TAMIL_RE.sub(" ", text or "")


def phoneticize_tanglish(text: str) -> str:
    """Syllabify residual Tanglish tokens for English TTS."""
    out = text or ""
    for pattern, repl in _PHONETIC_TANGLISH:
        out = pattern.sub(repl, out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = re.sub(r"\s+([.,!?])", r"\1", out)
    return out


def prepare_for_latin_tts(text: str, lexicon: dict[str, str] | None = None) -> str:
    """Final pass before win_sapi / similar engines."""
    _ = lexicon  # lexicon already applied upstream with latin_safe filter
    out = strip_tamil_script(text)
    out = phoneticize_tanglish(out)
    return re.sub(r"\s{2,}", " ", out).strip()
