"""
Make text speakable for Latin/English TTS engines (esp. Windows SAPI).

Phonetic + colloquial rules apply to ALL Tanglish backends (edge_fast + win_sapi).
Neural voices use compact respelling (annuh); SAPI uses hyphenated (ann-uh).
"""
from __future__ import annotations

import re

from normalization.pronunciation_rules import (
    colloquialize_tanglish,
    phoneticize_tanglish,
    strip_tamil_script,
)

_TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")

LATIN_ONLY_BACKENDS = frozenset({"win_sapi", "sapi", "turbo", "local"})


def is_latin_only_backend(backend_name: str | None) -> bool:
    return (backend_name or "").lower().strip() in LATIN_ONLY_BACKENDS


def resolve_speak_target(
    backend_name: str | None,
    requested_target: str,
    detected_lang: str,
    *,
    has_indic_os_voice: bool = False,
) -> str:
    tgt = (requested_target or "tanglish").lower().strip()
    if not is_latin_only_backend(backend_name):
        return tgt
    if has_indic_os_voice:
        return tgt
    if tgt in ("ta", "tamil", "ta-in"):
        return "en"
    if tgt in ("auto", "none", "off") and detected_lang == "ta":
        return "en"
    return tgt


def latin_safe_lexicon(lexicon: dict[str, str] | None) -> dict[str, str]:
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


def prepare_for_tanglish_tts(
    text: str,
    *,
    backend_name: str | None = None,
    lexicon: dict[str, str] | None = None,
) -> str:
    """Colloquial + gold-derived phonetics for any Tanglish backend."""
    _ = lexicon
    latin_only = is_latin_only_backend(backend_name)
    out = strip_tamil_script(text)
    out = colloquialize_tanglish(out)
    out = phoneticize_tanglish(out, compact=not latin_only)
    return re.sub(r"\s{2,}", " ", out).strip()


def prepare_for_latin_tts(text: str, lexicon: dict[str, str] | None = None) -> str:
    """Alias: hyphenated phonetics for Latin-only engines."""
    return prepare_for_tanglish_tts(text, backend_name="win_sapi", lexicon=lexicon)
