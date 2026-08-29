"""Multi-level deduplication: audio hash, transcript hash, near-dup text, same segment."""
from __future__ import annotations

import difflib
import hashlib
import logging
from typing import Any

from dataset_pipeline.config_loader import load_dataset_config

logger = logging.getLogger("dataset_pipeline.dedup")


def norm_text(t: str) -> str:
    return " ".join((t or "").lower().split())


def text_hash(t: str) -> str:
    return hashlib.sha256(norm_text(t).encode("utf-8")).hexdigest()


def deduplicate(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Returns (kept, stats). Near-dups and exact dups are flagged rejected/review,
    not silently deleted — originals kept; duplicates marked status=rejected + flag.
    """
    ds = load_dataset_config()
    thr = float(ds.get("near_dup_text_threshold") or 0.92)
    seen_audio: set[str] = set()
    seen_text: set[str] = set()
    seen_seg: set[str] = set()
    kept_texts: list[str] = []
    kept: list[dict[str, Any]] = []
    stats = {
        "input": len(records),
        "exact_audio_dup": 0,
        "exact_text_dup": 0,
        "near_text_dup": 0,
        "same_source_segment": 0,
        "kept": 0,
    }

    for rec in records:
        flags = list(rec.get("quality_flags") or [])
        audio_h = rec.get("audio_sha256") or ""
        th = rec.get("transcript_sha256") or text_hash(rec.get("transcript_raw") or "")
        rec["transcript_sha256"] = th
        seg_key = f"{rec.get('source_video_id')}:{rec.get('start')}:{rec.get('end')}"
        has_span = float(rec.get("end") or 0) > float(rec.get("start") or 0)

        dup = False
        if audio_h and audio_h in seen_audio:
            flags.append("exact_audio_duplicate")
            stats["exact_audio_dup"] += 1
            dup = True
        if th and th in seen_text:
            flags.append("exact_transcript_duplicate")
            stats["exact_text_dup"] += 1
            dup = True
        if has_span and seg_key in seen_seg and rec.get("source_video_id"):
            flags.append("same_source_segment")
            stats["same_source_segment"] += 1
            dup = True

        raw = norm_text(rec.get("transcript_raw") or "")
        if raw and not dup:
            for other in kept_texts:
                if difflib.SequenceMatcher(None, raw, other).ratio() >= thr:
                    flags.append("near_transcript_duplicate")
                    stats["near_text_dup"] += 1
                    dup = True
                    break

        rec["quality_flags"] = flags
        if dup:
            rec["status"] = "rejected"
            # Still append for audit trail (not silent discard)
            kept.append(rec)
            continue

        if audio_h:
            seen_audio.add(audio_h)
        if th:
            seen_text.add(th)
        if has_span:
            seen_seg.add(seg_key)
        if raw:
            kept_texts.append(raw)
        kept.append(rec)
        stats["kept"] += 1

    stats["duplicate_rate"] = round(
        (stats["exact_audio_dup"] + stats["exact_text_dup"] + stats["near_text_dup"] + stats["same_source_segment"])
        / max(1, stats["input"]),
        4,
    )
    return kept, stats
