"""
Tanglish LLM layer (prompt-based, no fine-tuning).

============================================================================
DESIGN PRINCIPLE — NATURAL SPOKEN TANGLISH, NOT TAMIL TRANSLATION
============================================================================
Terms in preserve_english_list.json must NEVER be converted to Tamil script
regardless of context. The goal is natural spoken Tanglish for a Chennai taxi
voice-agent, preserving English loanwords in Latin script inline.

Example:
  Input:  "Unga driver 5 minutes la vandhuruvaanga"
  GOOD:   "உங்க driver 5 minutes ல வந்துருவாங்க"
  BAD:    "உங்க டிரைவர் ஐந்து நிமிடத்தில் வந்துவிடுவார்கள்"
          (fully Tamil-script literary translation)

This layer runs AFTER deterministic_normalizer and pronunciation_lexicon lookup.
It only handles what those two could not resolve.

FUTURE QLoRA HOOK (not implemented):
  If validator_flags.log shows consistent Tanglish error classes (over-translation
  of loanwords, bad code-mix, etc.), a future QLoRA fine-tune of a small adapter
  on flagged (input, corrected_output) pairs could be inserted HERE — replacing
  or wrapping call_ollama_tanglish(). Do NOT train in this repo; prompt-only.
============================================================================
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    LLM_MAX_RETRIES,
    OLLAMA_CHAT_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT_SEC,
    PRESERVE_ENGLISH_LIST_PATH,
    TRANSLATOR_OLLAMA_ENABLED,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("normalization.tanglish_llm")


def load_preserve_list(path: Path = PRESERVE_ENGLISH_LIST_PATH) -> list[str]:
    if not path.exists():
        logger.warning("preserve list missing at %s", path)
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [str(x).strip() for x in data if str(x).strip()]


def build_tanglish_prompt(text: str, preserve: list[str]) -> str:
    preserve_csv = ", ".join(preserve)
    return (
        "You normalize text for a Chennai taxi TTS voice agent.\n"
        "Output NATURAL SPOKEN TANGLISH — do NOT produce pure Tamil literary "
        "translation and do NOT force pure English.\n"
        f"NEVER convert these English loanwords to Tamil script: {preserve_csv}.\n"
        "Keep them in Latin script inline. You may add Tamil particles/suffixes "
        "around them (e.g. 'driver', 'OTP', 'cab', 'traffic').\n"
        "Do not invent new facts. Return ONLY the normalized sentence text, "
        "no quotes, no markdown.\n\n"
        f"Input: {text}\n"
        "Output:"
    )


def call_ollama_tanglish(text: str, preserve: list[str] | None = None) -> str:
    preserve = preserve if preserve is not None else load_preserve_list()
    prompt = build_tanglish_prompt(text, preserve)
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a Tanglish normalizer for taxi TTS. "
                    "Preserve English loanwords in Latin script. "
                    "Never fully translate to literary Tamil."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    }
    last_err = None
    for attempt in range(1, LLM_MAX_RETRIES + 2):
        try:
            resp = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=OLLAMA_TIMEOUT_SEC)
            resp.raise_for_status()
            body = resp.json()
            message = body.get("message") or {}
            out = (message.get("content") or body.get("response") or "").strip()
            out = out.strip('"').strip("'").strip()
            if out:
                return out
            raise ValueError("empty LLM response")
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning("Tanglish LLM attempt %d failed: %s", attempt, exc)
    logger.error("Tanglish LLM failed after retries (%s) — returning deterministic text", last_err)
    # Soft fallback: pass through so TTS still works without Ollama
    return text


def needs_tanglish_llm(text: str) -> bool:
    """Heuristic: Tamil script mixed with Latin, or common Tanglish suffixes."""
    has_tamil = any("\u0b80" <= ch <= "\u0bff" for ch in text)
    has_latin = any("a" <= ch.lower() <= "z" for ch in text)
    tanglish_markers = (" la ", " ah ", " nu ", "pannu", "irukku", "unga", "naan")
    lower = f" {text.lower()} "
    if any(m in lower for m in tanglish_markers):
        return True
    return has_tamil and has_latin


def apply_tanglish_layer(text: str, force: bool = False) -> str:
    """Apply LLM Tanglish handling only when needed (or force=True).

    Disabled unless TRANSLATOR_OLLAMA_ENABLED — offline rewrite already
    produces speakable Tanglish; Ollama here routinely adds 3–20s to TTFA.
    """
    if not TRANSLATOR_OLLAMA_ENABLED:
        return text
    if not force and not needs_tanglish_llm(text):
        logger.debug("Skipping Tanglish LLM for: %r", text)
        return text
    return call_ollama_tanglish(text)


if __name__ == "__main__":
    sample = "Unga driver 5 minutes la vandhuruvaanga"
    print(apply_tanglish_layer(sample, force=True))
