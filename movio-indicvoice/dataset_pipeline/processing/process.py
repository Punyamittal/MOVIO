"""
Process stage: media → VAD → STT → lang → normalize → Tanglish → quality → dedup.

Also folds bootstrap text samples into clean utterances.jsonl.
Resumable via progress + existing utterance ids.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from dataset_pipeline.acquisition.collect import BOOTSTRAP_JSONL, COLLECTED_JSONL
from dataset_pipeline.io_util import bump_count, load_progress, save_progress
from dataset_pipeline.jsonl import read_jsonl_list, write_jsonl
from dataset_pipeline.paths import AUDIO_DIR, UTTERANCES_JSONL, ensure_dirs
from dataset_pipeline.processing.asr import transcribe_wav
from dataset_pipeline.processing.audio_proc import (
    convert_to_wav_mono,
    load_mono_pcm16,
    segment_speech,
    sha256_file,
    slice_audio,
    write_wav_pcm16,
)
from dataset_pipeline.processing.lang_class import classify_language
from dataset_pipeline.processing.text_proc import generate_tanglish, normalize_transcript
from dataset_pipeline.quality.dedup import deduplicate, text_hash
from dataset_pipeline.quality.filter import score_and_status
from dataset_pipeline.quality.speaker import assign_speaker_ids
from dataset_pipeline.schema import UtteranceRecord, new_sample_id

logger = logging.getLogger("dataset_pipeline.process")


def _process_bootstrap_text(max_samples: int = 1000) -> list[dict[str, Any]]:
    rows = read_jsonl_list(BOOTSTRAP_JSONL)[:max_samples]
    out: list[dict[str, Any]] = []
    for raw in rows:
        rec = UtteranceRecord.from_dict(raw)
        if not rec.transcript_normalized:
            rec.transcript_normalized = normalize_transcript(rec.transcript_raw)
        lang, cs = classify_language(rec.transcript_raw)
        if rec.language in ("unknown", ""):
            rec.language = lang
        rec.code_switching = cs or rec.code_switching
        if not rec.tanglish:
            tg = generate_tanglish(rec.transcript_raw, rec.language, offline_only=True)
            rec.tanglish = tg.get("tanglish") or rec.tanglish
            rec.translation_en = tg.get("translation_en") or rec.translation_en
            rec.meta = {**(rec.meta or {}), "tanglish_meta": tg}
        else:
            # Gold pairs already carry Tanglish — do not regenerate
            rec.meta = {**(rec.meta or {}), "tanglish_meta": {"tanglish_engine": "preexisting"}}
        rec.transcript_sha256 = text_hash(rec.transcript_raw)
        if rec.stt_confidence <= 0:
            rec.stt_confidence = 0.9 if rec.tanglish else 0.7
        rec = score_and_status(rec, audio=None)
        out.append(rec.to_dict())
    return out


def _process_media_entry(entry: dict[str, Any], existing_ids: set[str]) -> list[dict[str, Any]]:
    media = entry.get("media_path") or ""
    if not media or not Path(media).exists():
        # Captions metadata-only — do not invent audio or treat as training
        caps = entry.get("captions_path") or ""
        if caps and Path(caps).exists():
            import json

            data = json.loads(Path(caps).read_text(encoding="utf-8"))
            text = (data.get("text") or "").strip()
            if not text:
                return []
            sid = new_sample_id("meta")
            lang, cs = classify_language(text)
            rec = UtteranceRecord(
                id=sid,
                audio="",
                source=entry.get("source") or "youtube",
                source_video_id=str(entry.get("video_id") or ""),
                language=lang,
                transcript_raw=text[:4000],
                transcript_normalized=normalize_transcript(text[:4000]),
                code_switching=cs,
                domain=str(entry.get("domain") or "general_conversation"),
                license=str(entry.get("license") or "unknown"),
                license_verified=bool(entry.get("license_verified")),
                usable_for_training=False,
                status="review",
                discovery_query=str(entry.get("discovery_query") or ""),
                meta={"acquisition": "captions_meta"},
            )
            tg = generate_tanglish(rec.transcript_raw, rec.language)
            rec.tanglish = tg.get("tanglish") or ""
            rec.translation_en = tg.get("translation_en") or ""
            rec.stt_confidence = 0.5
            rec = score_and_status(rec)
            return [rec.to_dict()]
        return []

    src = Path(media)
    vid = str(entry.get("video_id") or src.stem)
    wav_path = AUDIO_DIR / "full" / f"{vid}.wav"
    try:
        convert_to_wav_mono(src, wav_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("convert failed %s: %s", src, exc)
        return []

    audio, sr = load_mono_pcm16(wav_path, target_sr=16000)
    segs = segment_speech(audio, sr)
    out: list[dict[str, Any]] = []
    for start, end in segs:
        sid = new_sample_id("utt")
        if sid in existing_ids:
            continue
        clip = slice_audio(audio, sr, start, end)
        clip_path = AUDIO_DIR / f"{sid}.wav"
        write_wav_pcm16(clip_path, clip, sample_rate=sr)
        try:
            asr = transcribe_wav(clip_path, language_hint=entry.get("language_guess"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("STT failed %s: %s", sid, exc)
            asr = {"raw_transcript": "", "confidence": 0.0, "language": "unknown", "timestamps": [], "stt_ms": 0}
        raw = asr.get("raw_transcript") or ""
        lang, cs = classify_language(raw)
        norm = normalize_transcript(raw) if raw else ""
        tg = generate_tanglish(raw, lang) if raw else {}
        rec = UtteranceRecord(
            id=sid,
            audio=str(clip_path.relative_to(AUDIO_DIR.parent.parent)) if False else str(clip_path),
            source=entry.get("source") or "youtube",
            source_video_id=vid,
            start=start,
            end=end,
            language=lang,
            transcript_raw=raw,
            transcript_normalized=norm,
            tanglish=tg.get("tanglish") or "",
            translation_en=tg.get("translation_en") or "",
            domain=str(entry.get("domain") or "general_conversation"),
            duration=round(end - start, 3),
            stt_confidence=float(asr.get("confidence") or 0),
            code_switching=cs,
            license=str(entry.get("license") or "unknown"),
            license_verified=bool(entry.get("license_verified")),
            usable_for_training=bool(entry.get("usable_for_training")),
            discovery_query=str(entry.get("discovery_query") or ""),
            audio_sha256=sha256_file(clip_path),
            transcript_sha256=text_hash(raw),
            timestamps=list(asr.get("timestamps") or []),
            meta={"stt_ms": asr.get("stt_ms"), "stt_backend": asr.get("backend"), "tanglish_meta": tg},
        )
        # Store path relative to pipeline output for portability
        try:
            from dataset_pipeline.paths import OUTPUT_DIR

            rec.audio = str(clip_path.relative_to(OUTPUT_DIR)).replace("\\", "/")
        except ValueError:
            rec.audio = str(clip_path)
        rec = score_and_status(rec, audio=clip)
        out.append(rec.to_dict())
        bump_count("transcribed")
    return out


def process(*, limit_media: int | None = None) -> Path:
    ensure_dirs()
    save_progress(stage="process")
    existing = read_jsonl_list(UTTERANCES_JSONL)
    existing_ids = {r.get("id") for r in existing}
    all_rows: list[dict[str, Any]] = list(existing)

    # Bootstrap text
    boot = _process_bootstrap_text()
    for r in boot:
        if r["id"] not in existing_ids:
            all_rows.append(r)
            existing_ids.add(r["id"])
            bump_count("processed")

    # Media / captions
    collected = read_jsonl_list(COLLECTED_JSONL)
    n_media = 0
    for entry in collected:
        if limit_media is not None and n_media >= limit_media:
            break
        if entry.get("media_path"):
            n_media += 1
        new_recs = _process_media_entry(entry, existing_ids)
        for r in new_recs:
            if r["id"] not in existing_ids:
                all_rows.append(r)
                existing_ids.add(r["id"])
                bump_count("processed")

    all_rows = assign_speaker_ids(all_rows)
    all_rows, dedup_stats = deduplicate(all_rows)
    write_jsonl(UTTERANCES_JSONL, all_rows)

    # Status counts
    for r in all_rows:
        bump_count(f"status_{r.get('status')}", 0)  # ensure keys
    # rewrite counts properly
    from dataset_pipeline.io_util import load_progress

    prog = load_progress()
    counts = prog.get("counts") or {}
    for key in ("status_accepted", "status_review", "status_rejected"):
        counts[key] = 0
    for r in all_rows:
        k = f"status_{r.get('status')}"
        counts[k] = counts.get(k, 0) + 1
    counts["dedup"] = dedup_stats
    save_progress(stage="process_done", counts=counts)
    logger.info(
        "Process complete: %d utterances (accepted=%s review=%s rejected=%s) → %s",
        len(all_rows),
        counts.get("status_accepted"),
        counts.get("status_review"),
        counts.get("status_rejected"),
        UTTERANCES_JSONL,
    )
    return UTTERANCES_JSONL
