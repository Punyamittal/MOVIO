"""STT wrapper — reuses phone_test STT (IndicWhisper / Whisper)."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

# Ensure project root importable
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger("dataset_pipeline.asr")


def transcribe_wav(
    path: Path,
    *,
    language_hint: str | None = None,
) -> dict[str, Any]:
    """
    Returns raw_transcript, confidence (heuristic), language, timestamps, stt_ms.
    Does not fabricate transcripts — empty/error surfaces clearly.
    """
    from phone_test import stt as stt_mod

    text, stt_ms = stt_mod.transcribe_file(path, language_hint=language_hint)
    text = (text or "").strip()
    # Whisper pipeline often lacks per-utt confidence; use length/heuristic proxy
    # and flag low when empty/short relative to duration later in quality.
    conf = 0.0 if not text else min(0.95, 0.55 + min(0.35, len(text.split()) * 0.02))
    return {
        "raw_transcript": text,
        "confidence": conf,
        "language": language_hint or "unknown",
        "timestamps": [],
        "stt_ms": stt_ms,
        "backend": stt_mod.status().get("backend"),
    }
