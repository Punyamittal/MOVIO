"""
Normalization + Tanglish — reuses project pipelines.

Keeps Translation / Tanglish / Code-switch as separate fields.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger("dataset_pipeline.text")


def normalize_transcript(text: str) -> str:
    from normalization.deterministic_normalizer import normalize

    return normalize(text or "")


def generate_tanglish(text: str, language: str, *, offline_only: bool = True) -> dict[str, Any]:
    """
    Produce Tanglish via existing translator when source is Tamil / needs speakable Latin.

    offline_only=True (default for dataset batch): use offline rewrite / gold only —
    do not call Ollama for hundreds of rows (keeps laptop pipeline usable).
    """
    from normalization.language_translator import detect_language, to_english
    from normalization.tanglish_rewrite import lookup_gold_tanglish, rewrite_en_to_tanglish

    detected = detect_language(text or "")
    tanglish = ""
    translation_en = ""
    transliteration = ""
    meta_engine = "skip"
    eng_engine = "skip"

    # Already Latin Tanglish / code-switch utterance — keep as tanglish field
    if language == "ta-en" and text and not any("\u0b80" <= ch <= "\u0bff" for ch in text):
        return {
            "tanglish": text,
            "translation_en": "",
            "transliteration": "",
            "detected": detected or "tanglish",
            "tanglish_engine": "passthrough-codeswitch",
            "en_engine": "skip",
        }

    def _gold() -> str | None:
        try:
            return lookup_gold_tanglish(text)
        except Exception:  # noqa: BLE001
            return None

    if language in ("ta", "ta-en") or detected in ("ta", "tanglish"):
        gold = _gold()
        if gold:
            tanglish = gold
            meta_engine = "gold"
        else:
            try:
                tanglish = rewrite_en_to_tanglish(text) if detected in ("en", "unknown") else text
                meta_engine = "offline-rewrite" if tanglish != text else "passthrough"
            except Exception as exc:  # noqa: BLE001
                logger.warning("offline tanglish failed: %s", exc)
                tanglish = text
                meta_engine = "passthrough"
        if not offline_only:
            try:
                from normalization.language_translator import to_tanglish

                out, engine = to_tanglish(text, detected if detected != "unknown" else "ta")
                if out:
                    tanglish = out
                    meta_engine = engine
            except Exception as exc:  # noqa: BLE001
                logger.warning("tanglish failed: %s", exc)
        if offline_only:
            translation_en = ""
            eng_engine = "skipped-offline-batch"
        else:
            try:
                en, eng_engine = to_english(text, detected if detected != "unknown" else "ta")
                translation_en = en or ""
            except Exception:  # noqa: BLE001
                translation_en = ""
                eng_engine = "error"
        return {
            "tanglish": tanglish,
            "translation_en": translation_en,
            "transliteration": transliteration,
            "detected": detected,
            "tanglish_engine": meta_engine,
            "en_engine": eng_engine,
        }

    if language == "en" or detected == "en":
        gold = _gold()
        if gold:
            tanglish = gold
            meta_engine = "gold"
        else:
            try:
                tanglish = rewrite_en_to_tanglish(text)
                meta_engine = "offline-rewrite"
            except Exception as exc:  # noqa: BLE001
                logger.warning("en→tanglish offline failed: %s", exc)
                tanglish = ""
                meta_engine = "error"
        return {
            "tanglish": tanglish,
            "translation_en": text,
            "transliteration": "",
            "detected": detected,
            "tanglish_engine": meta_engine,
            "en_engine": "passthrough",
        }

    return {
        "tanglish": tanglish,
        "translation_en": translation_en or text,
        "transliteration": transliteration,
        "detected": detected,
        "tanglish_engine": "skip",
        "en_engine": "skip",
    }
