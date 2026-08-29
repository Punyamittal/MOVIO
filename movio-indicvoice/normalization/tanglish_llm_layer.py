"""
Tanglish LLM normalization layer (prompt-based, no fine-tuning).

Runs AFTER deterministic_normalizer and pronunciation_lexicon lookup on text
that is already Tanglish but may be malformed (mixed script, wrong suffixes,
English clause collapse, etc.).

The canonical grammar contract lives in tanglish_normalize_spec.py. Rule-based
repair in tanglish_style_normalizer + translation_validator implements the same
rules without calling the LLM (faster, deterministic).

FUTURE QLoRA HOOK: replace call_ollama_tanglish() if validator_flags.log shows
consistent error classes.
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
from normalization.tanglish_normalize_spec import (  # noqa: E402
    build_normalize_messages,
    enforce_roman_script,
    parse_normalize_output,
)
from normalization.tanglish_style_normalizer import polish_tanglish_output  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("normalization.tanglish_llm")


def load_preserve_list(path: Path = PRESERVE_ENGLISH_LIST_PATH) -> list[str]:
    if not path.exists():
        logger.warning("preserve list missing at %s", path)
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [str(x).strip() for x in data if str(x).strip()]


def postprocess_normalize(raw: str, *, source: str = "") -> tuple[str, list[str]]:
    """Apply spec output rules: parse flags, Roman-only, rule-based polish."""
    text, flags = parse_normalize_output(raw)
    text, script_flags = enforce_roman_script(text)
    flags.extend(script_flags)
    # Deterministic pass implements the same grammar contract without guessing.
    if text and not any(f.startswith("normalize_flagged:") for f in flags):
        text = polish_tanglish_output(text, source=source)
    return text, flags


def call_ollama_tanglish(text: str, preserve: list[str] | None = None) -> str:
    preserve = preserve if preserve is not None else load_preserve_list()
    messages = build_normalize_messages(text, preserve)
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
    }
    last_err = None
    for attempt in range(1, LLM_MAX_RETRIES + 2):
        try:
            resp = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=OLLAMA_TIMEOUT_SEC)
            resp.raise_for_status()
            body = resp.json()
            message = body.get("message") or {}
            raw = (message.get("content") or body.get("response") or "").strip()
            out, flags = postprocess_normalize(raw, source=text)
            if flags:
                logger.warning("Tanglish normalize flags: %s", flags)
            if out:
                return out
            raise ValueError("empty LLM response")
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning("Tanglish LLM attempt %d failed: %s", attempt, exc)
    logger.error("Tanglish LLM failed after retries (%s) — returning deterministic text", last_err)
    out, _ = postprocess_normalize(text, source=text)
    return out


def needs_tanglish_llm(text: str) -> bool:
    """Heuristic: mixed script, known malformation markers, or Tanglish particles."""
    has_tamil = any("\u0b80" <= ch <= "\u0bff" for ch in text)
    has_latin = any("a" <= ch.lower() <= "z" for ch in text)
    tanglish_markers = (
        " la ",
        " ah ",
        " nu ",
        "pannu",
        "irukku",
        "unga",
        "naan",
        "-ko ",
        "-ko,",
        " ku block",
        " ponna",
        " panna.",
        " bad day irukku",
    )
    lower = f" {text.lower()} "
    if any(m in lower for m in tanglish_markers):
        return True
    return has_tamil and has_latin


def apply_tanglish_layer(text: str, force: bool = False) -> str:
    """Normalize malformed Tanglish via rules + optional LLM."""
    if not force and not needs_tanglish_llm(text):
        out, _ = postprocess_normalize(text, source=text)
        return out
    if not TRANSLATOR_OLLAMA_ENABLED:
        out, flags = postprocess_normalize(text, source=text)
        if flags:
            logger.info("Tanglish LLM disabled; rule-only normalize flags=%s", flags)
        return out
    return call_ollama_tanglish(text)


if __name__ == "__main__":
    sample = "andha street ippo procession ku block pannirukanga"
    print(apply_tanglish_layer(sample, force=False))
