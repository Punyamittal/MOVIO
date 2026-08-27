"""
Optional YouTube transcript sourcing.

HARD RULE: This module must NEVER block the core pipeline.
Downstream code must NOT import from or depend on sourcing/output existing.

Run locally only — cloud IPs commonly get blocked by YouTube.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

# Allow running as `python sourcing/youtube_transcripts.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import SOURCING_OUTPUT_DIR  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sourcing.youtube")

# Placeholder video ID slots — replace with real Tamil/Tanglish taxi-related videos
# when running locally. Leave empty / invalid IDs: failures are logged and skipped.
VIDEO_IDS = [
    "PLACEHOLDER_VIDEO_01",
    "PLACEHOLDER_VIDEO_02",
    "PLACEHOLDER_VIDEO_03",
    "PLACEHOLDER_VIDEO_04",
    "PLACEHOLDER_VIDEO_05",
    "PLACEHOLDER_VIDEO_06",
    "PLACEHOLDER_VIDEO_07",
    "PLACEHOLDER_VIDEO_08",
    "PLACEHOLDER_VIDEO_09",
    "PLACEHOLDER_VIDEO_10",
]

DELAY_BETWEEN_CALLS_SEC = 1.5


def fetch_transcripts(video_ids: list[str] | None = None) -> Path:
    """Fetch transcripts and write one text file per video. Never raises for skippable failures."""
    video_ids = video_ids or VIDEO_IDS
    SOURCING_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SOURCING_OUTPUT_DIR / "youtube_transcripts.txt"

    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        from youtube_transcript_api._errors import (
            NoTranscriptFound,
            TooManyRequests,
            TranscriptsDisabled,
        )
    except ImportError:
        logger.warning(
            "youtube-transcript-api not installed; skipping YouTube sourcing. "
            "Core pipeline continues with benchmark/data/."
        )
        return out_path

    lines: list[str] = []
    for i, vid in enumerate(video_ids):
        if i > 0:
            time.sleep(DELAY_BETWEEN_CALLS_SEC)
        if vid.startswith("PLACEHOLDER"):
            logger.info("Skipping placeholder video id slot: %s", vid)
            continue
        try:
            # youtube-transcript-api API varies by version; try common patterns
            try:
                transcript = YouTubeTranscriptApi.get_transcript(vid, languages=["ta", "en", "ta-IN"])
            except AttributeError:
                api = YouTubeTranscriptApi()
                transcript = api.fetch(vid, languages=["ta", "en"])
            text = " ".join(seg.get("text", str(seg)) for seg in transcript)
            lines.append(f"# video_id={vid}\n{text}\n")
            logger.info("Fetched transcript for %s (%d chars)", vid, len(text))
        except TranscriptsDisabled:
            logger.warning("TranscriptsDisabled for %s — skipping", vid)
        except NoTranscriptFound:
            logger.warning("NoTranscriptFound for %s — skipping", vid)
        except TooManyRequests:
            logger.warning("TooManyRequests for %s — skipping remaining", vid)
            break
        except Exception as exc:  # noqa: BLE001 — optional path must never crash pipeline
            logger.warning("Failed transcript for %s: %s — skipping", vid, exc)

    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Wrote %s (%d entries)", out_path, len(lines))
    return out_path


if __name__ == "__main__":
    fetch_transcripts()
