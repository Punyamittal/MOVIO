"""Quality scoring, difficulty buckets, accept/review/reject (never silent drop)."""
from __future__ import annotations

import re
from typing import Any

import numpy as np

from dataset_pipeline.config_loader import load_filtering_config
from dataset_pipeline.processing.audio_proc import rms
from dataset_pipeline.schema import Difficulty, QualityStatus, UtteranceRecord

_OTP_RE = re.compile(r"\b\d{4,8}\b")
_PLATE_RE = re.compile(r"\bTN\s?\d{2}\s?[A-Z]{1,2}\s?\d{3,4}\b", re.I)


def estimate_noise_level(audio: np.ndarray | None, text: str = "") -> str:
    cfg = load_filtering_config().get("noise_levels") or {}
    if audio is None or audio.size == 0:
        return "unknown"
    r = rms(audio) * 32768  # approx PCM scale
    if r >= float(cfg.get("low_rms_above") or 1500):
        return "low"
    if r >= float(cfg.get("medium_rms_above") or 600):
        return "medium"
    return "high"


def difficulty_for(rec: UtteranceRecord) -> Difficulty:
    cfg = load_filtering_config().get("difficulty") or {}
    hard = False
    if cfg.get("hard_if_code_switch") and rec.code_switching:
        hard = True
    if cfg.get("hard_if_has_otp_or_plate") and (
        _OTP_RE.search(rec.transcript_raw) or _PLATE_RE.search(rec.transcript_raw)
    ):
        hard = True
    if rec.duration >= float(cfg.get("hard_if_duration_above") or 12):
        hard = True
    tokens = rec.transcript_raw.split()
    if len(tokens) <= int(cfg.get("easy_if_token_count_below") or 6) and rec.duration <= float(
        cfg.get("easy_if_duration_below") or 3
    ):
        if not hard and not rec.code_switching:
            return "easy"
    return "hard" if hard else "medium"


def score_and_status(
    rec: UtteranceRecord,
    *,
    audio: np.ndarray | None = None,
) -> UtteranceRecord:
    cfg = load_filtering_config()
    reject_cfg = cfg.get("reject") or {}
    review_cfg = cfg.get("review") or {}
    accept_cfg = cfg.get("accept") or {}
    flags: list[str] = list(rec.quality_flags or [])

    # Audio gates (skip for text-only bootstrap / metadata samples)
    has_audio = bool(rec.audio) or (audio is not None and getattr(audio, "size", 0) > 0)
    if has_audio and audio is not None and audio.size:
        r = rms(audio)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        clip_ratio = float(np.mean(np.abs(audio) > 0.99)) if audio.size else 0.0
        if r * 32768 < float(reject_cfg.get("min_rms") or 200):
            flags.append("low_volume")
        if clip_ratio > float(reject_cfg.get("max_clipping_ratio") or 0.02):
            flags.append("clipping")
        if peak < 0.02:
            flags.append("near_silent")
        rec.noise_level = estimate_noise_level(audio, rec.transcript_raw)

    if has_audio:
        if rec.duration < float(reject_cfg.get("min_duration_sec") or 0.8):
            flags.append("too_short")
        if rec.duration > float(reject_cfg.get("max_duration_sec") or 25):
            flags.append("too_long")
    if not (rec.transcript_raw or "").strip():
        flags.append("empty_transcript")
    if has_audio and rec.stt_confidence < float(reject_cfg.get("min_stt_confidence") or 0.35):
        flags.append("low_stt_confidence")
    if rec.language in (reject_cfg.get("non_target_languages") or ["other"]):
        flags.append("non_target_language")
    if not rec.usable_for_training and accept_cfg.get("require_usable_for_training", True):
        flags.append("not_licensed_for_training")

    # Quality score 0..1
    score = 0.5
    score += min(0.25, rec.stt_confidence * 0.25)
    if rec.transcript_normalized:
        score += 0.05
    if rec.tanglish:
        score += 0.05
    if rec.code_switching:
        score += 0.05  # valuable
    score -= 0.08 * len([f for f in flags if f not in ("not_licensed_for_training",)])
    if "not_licensed_for_training" in flags:
        score -= 0.2
    rec.quality_score = round(max(0.0, min(1.0, score)), 3)
    rec.quality_flags = flags
    rec.difficulty = difficulty_for(rec)

    # Status — never silently discard
    hard_reject_flags = ["empty_transcript", "near_silent", "non_target_language"]
    if has_audio:
        hard_reject_flags.append("too_short")
    hard_reject = any(f in flags for f in hard_reject_flags)
    if hard_reject:
        rec.status = "rejected"
        return rec

    # Text-only internal corpora (bootstrap)
    if not has_audio and rec.source == "existing_corpora":
        if rec.tanglish and rec.transcript_raw and rec.usable_for_training:
            rec.status = "accepted"
        else:
            rec.status = "review"
        return rec

    if (
        rec.usable_for_training
        and rec.stt_confidence >= float(accept_cfg.get("min_stt_confidence") or 0.75)
        and rec.quality_score >= float(accept_cfg.get("min_quality_score") or 0.8)
        and "not_licensed_for_training" not in flags
    ):
        rec.status = "accepted"
    elif rec.stt_confidence < float(review_cfg.get("stt_confidence_below") or 0.7) or rec.quality_score < float(
        review_cfg.get("quality_score_below") or 0.75
    ) or "not_licensed_for_training" in flags:
        rec.status = "review"
    else:
        rec.status = "review"

    return rec
