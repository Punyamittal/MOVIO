"""Lightweight speaker labeling — per-video incremental speakers (no demographics)."""
from __future__ import annotations

from typing import Any


def assign_speaker_ids(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Without a neural diarizer, assign speaker_id per contiguous video stream index.
    Consecutive segments in the same video share spk_00 unless a large gap suggests change.
    """
    by_video: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        by_video.setdefault(str(r.get("source_video_id") or "unknown"), []).append(r)

    out: list[dict[str, Any]] = []
    for vid, rows in by_video.items():
        rows = sorted(rows, key=lambda x: float(x.get("start") or 0))
        spk_i = 0
        last_end = None
        count = 0
        for r in rows:
            start = float(r.get("start") or 0)
            end = float(r.get("end") or 0)
            if last_end is not None and (start - last_end) > 8.0:
                spk_i += 1
            r["speaker_id"] = f"spk_{vid[-6:]}_{spk_i:02d}"
            count += 1
            r["speaker_segment_count"] = 0  # filled below
            last_end = end
            out.append(r)
        # segment counts
        counts: dict[str, int] = {}
        for r in rows:
            counts[r["speaker_id"]] = counts.get(r["speaker_id"], 0) + 1
        for r in rows:
            r["speaker_segment_count"] = counts[r["speaker_id"]]
    return out
