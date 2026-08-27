"""
Synthetic Tanglish sentence generation via local Ollama REST API.

No API key. Uses config.OLLAMA_MODEL (gemma4:31b default / gemma4:26b swap).
Does NOT depend on sourcing/ output.
"""
from __future__ import annotations

import difflib
import json
import logging
import re
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    CATEGORIES,
    DATA_GEN_OUTPUT_DIR,
    LLM_MAX_RETRIES,
    OLLAMA_CHAT_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT_SEC,
    SENTENCES_PER_CATEGORY,
)
from data_generation.prompts.categories import SYSTEM_INSTRUCTION, build_user_prompt  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("data_generation.generate")


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _extract_json_array(text: str) -> list | None:
    cleaned = _strip_fences(text)
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "items" in data:
            return data["items"]
    except json.JSONDecodeError:
        pass
    match = re.search(r"\[[\s\S]*\]", cleaned)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, list) else None
    except json.JSONDecodeError:
        return None


def call_ollama(user_prompt: str) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "format": "json",
    }
    resp = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=OLLAMA_TIMEOUT_SEC)
    resp.raise_for_status()
    body = resp.json()
    message = body.get("message") or {}
    return message.get("content") or body.get("response") or ""


def generate_category(category: str, n: int) -> list[dict]:
    prompt = build_user_prompt(category, n)
    last_err = None
    for attempt in range(1, LLM_MAX_RETRIES + 2):  # initial + 2 retries
        try:
            raw = call_ollama(prompt)
            items = _extract_json_array(raw)
            if items is None:
                raise ValueError("Could not parse JSON array from model response")
            cleaned = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text", "")).strip()
                if not text:
                    continue
                cleaned.append(
                    {
                        "text": text,
                        "category": item.get("category", category),
                        "language_mix": item.get("language_mix", "tanglish"),
                    }
                )
            if cleaned:
                return cleaned
            raise ValueError("Empty item list after parse")
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            logger.warning(
                "Category %s attempt %d failed: %s", category, attempt, exc
            )
    logger.error("Skipping category %s after retries: %s", category, last_err)
    return []


def dedup_texts(items: list[dict], threshold: float = 0.92) -> list[dict]:
    kept: list[dict] = []
    texts: list[str] = []
    for item in items:
        t = item["text"]
        if any(difflib.SequenceMatcher(None, t.lower(), other.lower()).ratio() >= threshold for other in texts):
            continue
        kept.append(item)
        texts.append(t)
    return kept


def run(categories: list[str] | None = None, n_per_cat: int | None = None) -> Path:
    categories = categories or CATEGORIES
    n_per_cat = n_per_cat or SENTENCES_PER_CATEGORY
    DATA_GEN_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    combined: list[dict] = []
    for cat in categories:
        logger.info("Generating %d sentences for %s via %s", n_per_cat, cat, OLLAMA_MODEL)
        items = generate_category(cat, n_per_cat)
        items = dedup_texts(items)
        cat_path = DATA_GEN_OUTPUT_DIR / f"{cat}.json"
        cat_path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Saved %s (%d items)", cat_path, len(items))
        combined.extend(items)

    combined = dedup_texts(combined)
    out = DATA_GEN_OUTPUT_DIR / "combined_benchmark.json"
    out.write_text(json.dumps(combined, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Saved combined benchmark: %s (%d items)", out, len(combined))
    return out


if __name__ == "__main__":
    run()
