"""Special entity subset — locations, OTP, transport terms; complements lexicon."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dataset_pipeline.jsonl import read_jsonl_list, write_jsonl
from dataset_pipeline.paths import ENTITIES_DIR, UTTERANCES_JSONL, ensure_dirs

_OTP = re.compile(r"\b\d{4,8}\b")
_PLATE = re.compile(r"\bTN\s?\d{2}\s?[A-Z]{1,2}\s?\d{3,4}\b", re.I)
_MONEY = re.compile(r"(₹|rs\.?|inr)\s?\d+", re.I)
_TIME = re.compile(r"\b\d{1,2}:\d{2}\s*(am|pm)?\b", re.I)


def build_entity_subset() -> Path:
    ensure_dirs()
    from config import PRESERVE_ENGLISH_LIST_PATH, PRONUNCIATION_LEXICON_PATH

    preserve = json.loads(PRESERVE_ENGLISH_LIST_PATH.read_text(encoding="utf-8"))
    lexicon = json.loads(PRONUNCIATION_LEXICON_PATH.read_text(encoding="utf-8"))
    place_keys = [k for k in lexicon if not str(k).startswith("_") and lexicon.get(k)]

    rows = read_jsonl_list(UTTERANCES_JSONL)
    hits: list[dict[str, Any]] = []
    for r in rows:
        text = r.get("transcript_normalized") or r.get("transcript_raw") or ""
        lower = text.lower()
        tags = []
        if _OTP.search(text):
            tags.append("otp")
        if _PLATE.search(text):
            tags.append("vehicle_number")
        if _MONEY.search(text):
            tags.append("currency")
        if _TIME.search(text):
            tags.append("time")
        for p in place_keys:
            if p.lower() in lower:
                tags.append("location")
                break
        for w in preserve:
            if re.search(rf"\b{re.escape(str(w))}\b", text, re.I):
                tags.append("transport_term")
                break
        if tags:
            item = dict(r)
            item["entity_tags"] = sorted(set(tags))
            # Normalize entity spelling via lexicon keys present in text
            item["entity_notes"] = "Do not trust raw YouTube spelling; lexicon-normalized review required."
            hits.append(item)

    out = ENTITIES_DIR / "entity_subset.jsonl"
    write_jsonl(out, hits)
    (ENTITIES_DIR / "entity_stats.json").write_text(
        json.dumps({"count": len(hits), "tag_histogram": _hist(hits)}, indent=2),
        encoding="utf-8",
    )
    return out


def _hist(rows: list[dict[str, Any]]) -> dict[str, int]:
    h: dict[str, int] = {}
    for r in rows:
        for t in r.get("entity_tags") or []:
            h[t] = h.get(t, 0) + 1
    return h
