"""Dataset statistics + lightweight chart artifacts."""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

from dataset_pipeline.acquisition.discover import CANDIDATES_JSONL
from dataset_pipeline.acquisition.collect import COLLECTED_JSONL
from dataset_pipeline.io_util import load_progress
from dataset_pipeline.jsonl import read_jsonl_list
from dataset_pipeline.paths import STATS_DIR, UTTERANCES_JSONL, ensure_dirs

logger = logging.getLogger("dataset_pipeline.stats")


def compute_stats() -> dict[str, Any]:
    ensure_dirs()
    candidates = read_jsonl_list(CANDIDATES_JSONL)
    collected = read_jsonl_list(COLLECTED_JSONL)
    utts = read_jsonl_list(UTTERANCES_JSONL)
    prog = load_progress()

    langs = Counter(str(r.get("language") or "unknown") for r in utts)
    domains = Counter(str(r.get("domain") or "other") for r in utts)
    status = Counter(str(r.get("status") or "unknown") for r in utts)
    noise = Counter(str(r.get("noise_level") or "unknown") for r in utts)
    speakers = {r.get("speaker_id") for r in utts if r.get("speaker_id")}
    durations = [float(r.get("duration") or 0) for r in utts if float(r.get("duration") or 0) > 0]
    confs = [float(r.get("stt_confidence") or 0) for r in utts]
    qscores = [float(r.get("quality_score") or 0) for r in utts]
    cs = sum(1 for r in utts if r.get("code_switching"))
    hours = sum(durations) / 3600.0
    permitted = sum(1 for r in candidates if r.get("usable_for_training"))
    downloaded = sum(1 for r in collected if r.get("acquisition") == "audio")

    dedup = (prog.get("counts") or {}).get("dedup") or {}
    stats = {
        "total_discovered": len(candidates),
        "total_permitted": permitted,
        "total_downloaded": downloaded,
        "total_transcribed": sum(1 for r in utts if r.get("transcript_raw") and r.get("audio")),
        "total_utterances": len(utts),
        "total_accepted": status.get("accepted", 0),
        "total_review": status.get("review", 0),
        "total_rejected": status.get("rejected", 0),
        "hours_of_audio": round(hours, 4),
        "tamil": langs.get("ta", 0),
        "english": langs.get("en", 0),
        "tamil_english": langs.get("ta-en", 0),
        "other_lang": langs.get("other", 0) + langs.get("unknown", 0),
        "average_duration": round(sum(durations) / max(1, len(durations)), 3) if durations else 0.0,
        "average_stt_confidence": round(sum(confs) / max(1, len(confs)), 3) if confs else 0.0,
        "average_quality_score": round(sum(qscores) / max(1, len(qscores)), 3) if qscores else 0.0,
        "duplicate_rate": dedup.get("duplicate_rate", 0.0),
        "noise_distribution": dict(noise),
        "domain_distribution": dict(domains),
        "language_distribution": dict(langs),
        "status_distribution": dict(status),
        "speaker_count": len(speakers),
        "code_switching_pct": round(100.0 * cs / max(1, len(utts)), 2),
        "progress": prog,
    }
    out = STATS_DIR / "report.json"
    out.write_text(json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_markdown(stats)
    _write_charts(stats)
    logger.info("Stats written → %s", out)
    return stats


def _write_markdown(stats: dict[str, Any]) -> None:
    lines = [
        "# Dataset Pipeline Stats",
        "",
        f"- Discovered: **{stats['total_discovered']}**",
        f"- Permitted: **{stats['total_permitted']}**",
        f"- Downloaded: **{stats['total_downloaded']}**",
        f"- Transcribed (with audio): **{stats['total_transcribed']}**",
        f"- Accepted / Review / Rejected: **{stats['total_accepted']}** / **{stats['total_review']}** / **{stats['total_rejected']}**",
        f"- Hours of audio: **{stats['hours_of_audio']}**",
        f"- ta / en / ta-en: **{stats['tamil']}** / **{stats['english']}** / **{stats['tamil_english']}**",
        f"- Avg duration: **{stats['average_duration']}s**",
        f"- Avg STT confidence: **{stats['average_stt_confidence']}**",
        f"- Avg quality: **{stats['average_quality_score']}**",
        f"- Duplicate rate: **{stats['duplicate_rate']}**",
        f"- Speakers: **{stats['speaker_count']}**",
        f"- Code-switching %: **{stats['code_switching_pct']}**",
        "",
        "## Domains",
        "",
        "| Category | Samples |",
        "|----------|---------|",
    ]
    for k, v in sorted((stats.get("domain_distribution") or {}).items(), key=lambda x: -x[1]):
        lines.append(f"| {k} | {v} |")
    (STATS_DIR / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_charts(stats: dict[str, Any]) -> None:
    """Write CSV chart data; PNG if matplotlib available."""
    for name, dist in (
        ("language", stats.get("language_distribution") or {}),
        ("domain", stats.get("domain_distribution") or {}),
        ("noise", stats.get("noise_distribution") or {}),
        ("status", stats.get("status_distribution") or {}),
    ):
        path = STATS_DIR / f"chart_{name}.csv"
        path.write_text(
            "label,count\n" + "\n".join(f"{k},{v}" for k, v in sorted(dist.items())),
            encoding="utf-8",
        )
    try:
        import matplotlib.pyplot as plt

        for name, dist in (
            ("language", stats.get("language_distribution") or {}),
            ("domain", stats.get("domain_distribution") or {}),
        ):
            if not dist:
                continue
            labels, values = zip(*sorted(dist.items(), key=lambda x: -x[1]))
            plt.figure(figsize=(8, 4))
            plt.bar(labels, values, color="#0f6e6e")
            plt.title(f"Samples by {name}")
            plt.xticks(rotation=30, ha="right")
            plt.tight_layout()
            plt.savefig(STATS_DIR / f"chart_{name}.png", dpi=120)
            plt.close()
    except Exception as exc:  # noqa: BLE001
        logger.info("matplotlib charts skipped: %s", exc)


def print_stats(stats: dict[str, Any] | None = None) -> None:
    stats = stats or compute_stats()
    print(json.dumps({k: stats[k] for k in stats if k != "progress"}, indent=2, ensure_ascii=False))
