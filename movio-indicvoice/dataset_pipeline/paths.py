"""Path layout for dataset_pipeline (never writes into existing corpora dirs)."""
from __future__ import annotations

from pathlib import Path

PIPELINE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PIPELINE_ROOT.parent
CONFIG_DIR = PIPELINE_ROOT / "config"
OUTPUT_DIR = PIPELINE_ROOT / "output"

RAW_DIR = OUTPUT_DIR / "raw"
CANDIDATES_DIR = RAW_DIR / "candidates"
MEDIA_DIR = RAW_DIR / "media"
TRANSCRIPTS_META_DIR = RAW_DIR / "transcripts_meta"

CLEAN_DIR = OUTPUT_DIR / "clean"
SEGMENTS_DIR = CLEAN_DIR / "segments"
AUDIO_DIR = CLEAN_DIR / "audio"
UTTERANCES_JSONL = CLEAN_DIR / "utterances.jsonl"

VERIFIED_DIR = OUTPUT_DIR / "verified"
VERIFIED_JSONL = VERIFIED_DIR / "utterances.jsonl"
HUMAN_EDITS_JSONL = VERIFIED_DIR / "human_edits.jsonl"

TRAIN_DIR = OUTPUT_DIR / "train"
VAL_DIR = OUTPUT_DIR / "validation"
TEST_DIR = OUTPUT_DIR / "test"

SHARDS_DIR = OUTPUT_DIR / "shards"
STATS_DIR = OUTPUT_DIR / "stats"
BASELINE_DIR = OUTPUT_DIR / "baseline"
REVIEW_DIR = OUTPUT_DIR / "review"
STATE_DIR = OUTPUT_DIR / "state"
ENTITIES_DIR = OUTPUT_DIR / "entities"

PROGRESS_PATH = STATE_DIR / "progress.json"
SEEN_VIDEO_IDS_PATH = STATE_DIR / "seen_video_ids.json"


def ensure_dirs() -> None:
    for p in (
        CANDIDATES_DIR,
        MEDIA_DIR,
        TRANSCRIPTS_META_DIR,
        SEGMENTS_DIR,
        AUDIO_DIR,
        VERIFIED_DIR,
        TRAIN_DIR,
        VAL_DIR,
        TEST_DIR,
        SHARDS_DIR,
        STATS_DIR,
        BASELINE_DIR,
        REVIEW_DIR,
        STATE_DIR,
        ENTITIES_DIR,
    ):
        p.mkdir(parents=True, exist_ok=True)
