"""
Replaceable acquisition adapters.

- youtube: download audio ONLY when usable_for_training; else captions/metadata
- user_provided: authorized local media
- existing_corpora: bootstrap text samples from project corpora (no overwrite)
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from dataset_pipeline.acquisition.license_check import evaluate_license
from dataset_pipeline.config_loader import load_dataset_config, load_sources_config
from dataset_pipeline.io_util import bump_count, save_progress
from dataset_pipeline.jsonl import append_jsonl, read_jsonl_list, write_jsonl
from dataset_pipeline.paths import (
    CANDIDATES_DIR,
    MEDIA_DIR,
    PROJECT_ROOT,
    TRANSCRIPTS_META_DIR,
    ensure_dirs,
)
from dataset_pipeline.schema import SourceCandidate, UtteranceRecord, new_sample_id

logger = logging.getLogger("dataset_pipeline.acquire")

COLLECTED_JSONL = CANDIDATES_DIR / "collected.jsonl"
BOOTSTRAP_JSONL = CANDIDATES_DIR / "bootstrap_text.jsonl"


def _yt_dlp_download_audio(video_id: str, out_dir: Path) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_tmpl = str(out_dir / f"{video_id}.%(ext)s")
    url = f"https://www.youtube.com/watch?v={video_id}"
    cmd = [
        "yt-dlp",
        "-x",
        "--audio-format",
        "wav",
        "--audio-quality",
        "0",
        "-o",
        out_tmpl,
        "--no-playlist",
        "--ignore-errors",
        url,
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("download failed %s: %s", video_id, exc)
        return None
    matches = list(out_dir.glob(f"{video_id}.*"))
    return matches[0] if matches else None


def _fetch_captions_meta(video_id: str) -> dict[str, Any]:
    """Best-effort captions via youtube-transcript-api (metadata path)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return {"ok": False, "error": "youtube-transcript-api not installed"}
    try:
        try:
            segs = YouTubeTranscriptApi.get_transcript(video_id, languages=["ta", "en", "ta-IN"])
        except AttributeError:
            api = YouTubeTranscriptApi()
            segs = api.fetch(video_id, languages=["ta", "en"])
            segs = [{"text": getattr(s, "text", str(s)), "start": getattr(s, "start", 0), "duration": getattr(s, "duration", 0)} for s in segs]
        text = " ".join(str(s.get("text") or "") for s in segs)
        return {"ok": True, "segments": segs, "text": text}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


def collect_youtube(limit: int | None = None) -> Path:
    ensure_dirs()
    ds = load_dataset_config()
    src = load_sources_config()
    yt_cfg = src.get("youtube") or {}
    limit = limit or int(ds.get("max_collect_videos") or 40)
    candidates_path = CANDIDATES_DIR / "candidates.jsonl"
    rows = read_jsonl_list(candidates_path)
    already = {r.get("video_id") for r in read_jsonl_list(COLLECTED_JSONL)}
    collected: list[dict[str, Any]] = []
    save_progress(stage="collect")

    n = 0
    for raw in rows:
        if n >= limit:
            break
        cand = evaluate_license(raw)
        if cand.video_id in already or str(cand.video_id).startswith("STUB_"):
            continue
        entry: dict[str, Any] = cand.to_dict()
        entry["media_path"] = ""
        entry["captions_path"] = ""
        entry["acquisition"] = "metadata_only"

        if cand.usable_for_training and yt_cfg.get("download_audio_if_usable", True):
            media = _yt_dlp_download_audio(cand.video_id, MEDIA_DIR / cand.video_id)
            if media:
                entry["media_path"] = str(media)
                entry["acquisition"] = "audio"
                bump_count("downloaded")
                n += 1
            else:
                entry["notes"] = (entry.get("notes") or "") + " | audio download failed"
        elif yt_cfg.get("allow_metadata_only", True):
            caps = _fetch_captions_meta(cand.video_id)
            cap_path = TRANSCRIPTS_META_DIR / f"{cand.video_id}.json"
            cap_path.write_text(json.dumps(caps, ensure_ascii=False, indent=2), encoding="utf-8")
            entry["captions_path"] = str(cap_path)
            entry["acquisition"] = "captions_meta"
            entry["usable_for_training"] = False  # captions without clear license ≠ training audio
            bump_count("metadata_only")
            n += 1
            time.sleep(0.8)

        collected.append(entry)
        already.add(cand.video_id)

    if collected:
        append_jsonl(COLLECTED_JSONL, collected)
    save_progress(stage="collect_done")
    logger.info("Collected %d sources → %s", len(collected), COLLECTED_JSONL)
    return COLLECTED_JSONL


def collect_user_provided() -> Path:
    """Copy authorized files from output/raw/user_provided into media/."""
    ensure_dirs()
    src_dir = MEDIA_DIR.parent / "user_provided"
    src_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for p in list(src_dir.glob("*.wav")) + list(src_dir.glob("*.mp3")) + list(src_dir.glob("*.flac")):
        dest = MEDIA_DIR / "user_provided" / p.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        meta_side = p.with_suffix(".json")
        meta: dict[str, Any] = {}
        if meta_side.exists():
            meta = json.loads(meta_side.read_text(encoding="utf-8"))
        cand = SourceCandidate(
            source="user_provided",
            video_id=meta.get("id") or p.stem,
            title=meta.get("title") or p.name,
            url=meta.get("url") or "",
            license=meta.get("license") or "user_authorized",
            license_verified=bool(meta.get("license_verified", True)),
            usable_for_training=bool(meta.get("usable_for_training", True)),
            discovery_query="user_provided",
            domain=meta.get("domain") or "general_conversation",
            language_guess=meta.get("language") or "unknown",
        )
        row = cand.to_dict()
        row["media_path"] = str(dest)
        row["acquisition"] = "audio"
        rows.append(row)
    if rows:
        append_jsonl(COLLECTED_JSONL, rows)
        bump_count("downloaded", len(rows))
    return COLLECTED_JSONL


def bootstrap_existing_corpora() -> Path:
    """
    Import checked-in project text corpora as text-only samples for Tanglish
    pipeline validation. Does not modify those source files.
    """
    ensure_dirs()
    src = load_sources_config()
    corp = src.get("existing_corpora") or {}
    if not corp.get("paths"):
        return BOOTSTRAP_JSONL
    usable = bool(corp.get("usable_for_training", True))
    source_label = str(corp.get("source_label") or "existing_corpora")
    rows: list[dict[str, Any]] = []

    for rel in corp["paths"]:
        path = PROJECT_ROOT / rel
        if not path.exists():
            logger.warning("bootstrap skip missing %s", path)
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            continue
        for item in data:
            if "english" in item and "tanglish" in item:
                text = str(item.get("english") or "")
                tanglish = str(item.get("tanglish") or "")
                lang = "en"
                domain = str(item.get("category") or "general_conversation")
            else:
                text = str(item.get("text") or item.get("input") or "")
                tanglish = ""
                lang = str(item.get("language_mix") or "ta-en")
                domain = str(item.get("category") or "general_conversation")
            if not text.strip():
                continue
            sid = new_sample_id("boot")
            rec = UtteranceRecord(
                id=sid,
                audio="",
                source=source_label,
                source_video_id=f"corpus:{path.stem}",
                language="ta-en" if lang in ("tanglish", "ta-en") else ("en" if lang == "en" else "unknown"),
                transcript_raw=text,
                transcript_normalized="",
                tanglish=tanglish,
                domain=domain if domain else "general_conversation",
                duration=0.0,
                stt_confidence=1.0 if tanglish else 0.0,
                quality_score=0.7,
                code_switching=("tanglish" in lang) or ("ta-en" in lang),
                license="internal_reference",
                license_verified=True,
                usable_for_training=usable,
                status="review",
                verified=False,
                discovery_query=f"bootstrap:{path.name}",
                meta={"bootstrap_file": rel, "original": item},
            )
            rows.append(rec.to_dict())

    write_jsonl(BOOTSTRAP_JSONL, rows)
    bump_count("bootstrap_text", len(rows))
    logger.info("Bootstrapped %d text samples from existing corpora → %s", len(rows), BOOTSTRAP_JSONL)
    return BOOTSTRAP_JSONL


def collect_all(limit: int | None = None) -> dict[str, Path]:
    ensure_dirs()
    ds = load_dataset_config()
    out = {
        "youtube": collect_youtube(limit=limit),
        "user_provided": collect_user_provided(),
    }
    if ds.get("bootstrap_from_benchmark", True):
        out["bootstrap"] = bootstrap_existing_corpora()
    return out
