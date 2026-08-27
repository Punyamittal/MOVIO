"""
Dashboard overview API — live telemetry + on-disk benchmark/evaluation artifacts.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from config import (
    BENCHMARK_RESULTS_DIR,
    DEFAULT_TTS_BACKEND,
    EVALUATION_RESULTS_DIR,
    TTFA_TARGET_MS,
)
from server import telemetry

logger = logging.getLogger("server.dashboard_api")
router = APIRouter(tags=["dashboard"])

KNOWN_VOICES = [
    {"id": "jaya", "label": "Jaya — Tamil"},
    {"id": "kavitha", "label": "Kavitha — Tamil"},
    {"id": "divya", "label": "Divya — English"},
    {"id": "rohit", "label": "Rohit — English"},
    {"id": "pallavi", "label": "Pallavi — Edge Tamil"},
    {"id": "valluvar", "label": "Valluvar — Edge Tamil"},
    {"id": "neerja", "label": "Neerja — Edge English"},
]


def _read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed reading %s: %s", path, exc)
        return None


def _benchmark_snapshot() -> dict[str, Any]:
    summary = _read_json(BENCHMARK_RESULTS_DIR / "summary.json") or {}
    bug = _read_json(BENCHMARK_RESULTS_DIR / "bug_hunt_benchmark.json") or {}
    cache = _read_json(BENCHMARK_RESULTS_DIR / "cache_hierarchy_benchmark.json") or {}
    phone = _read_json(BENCHMARK_RESULTS_DIR / "phone_cache_sim.json") or {}

    comparison = summary.get("comparison") if isinstance(summary, dict) else None
    best_p99 = None
    best_backend = None
    if isinstance(comparison, dict):
        for name, block in comparison.items():
            ttfa = (block or {}).get("ttfa_ms") or {}
            p99 = ttfa.get("p99")
            if isinstance(p99, (int, float)):
                if best_p99 is None or p99 < best_p99:
                    best_p99 = float(p99)
                    best_backend = name

    return {
        "has_runs": bool(comparison) or bool(bug) or bool(cache),
        "best_p99_ttfa_ms": round(best_p99, 1) if best_p99 is not None else None,
        "best_backend": best_backend,
        "comparison": comparison or {},
        "bug_hunt_dataset_size": bug.get("dataset_size") if isinstance(bug, dict) else None,
        "cache_recommendation": cache.get("recommendation") if isinstance(cache, dict) else None,
        "phone_avg_e2e_round1_ms": phone.get("avg_e2e_round1_ms") if isinstance(phone, dict) else None,
        "phone_avg_e2e_round2_ms": phone.get("avg_e2e_round2_ms") if isinstance(phone, dict) else None,
    }


def _evaluation_snapshot() -> dict[str, Any]:
    acceptance = _read_json(EVALUATION_RESULTS_DIR / "acceptance_results.json") or {}
    wer = _read_json(EVALUATION_RESULTS_DIR / "wer_cer_scores.json") or {}
    agg = wer.get("aggregate") if isinstance(wer, dict) else {}
    avg_wer = None
    if isinstance(agg, dict):
        for key in ("avg_wer_vs_normalized", "avg_wer_vs_raw"):
            val = agg.get(key)
            if isinstance(val, (int, float)):
                avg_wer = float(val)
                break

    # MOS template is usually empty — only report when scores exist.
    mos_path = EVALUATION_RESULTS_DIR.parent / "mos_scoring_template.csv"
    mos_avg = None
    mos_n = 0
    if mos_path.exists():
        try:
            lines = mos_path.read_text(encoding="utf-8").splitlines()[1:]
            scores: list[float] = []
            for line in lines:
                parts = line.split(",")
                # naturalness col index 3
                if len(parts) > 3 and parts[3].strip():
                    try:
                        scores.append(float(parts[3].strip()))
                    except ValueError:
                        pass
            if scores:
                mos_avg = round(sum(scores) / len(scores), 2)
                mos_n = len(scores)
        except Exception:  # noqa: BLE001
            pass

    return {
        "acceptance_summary": acceptance.get("summary") if isinstance(acceptance, dict) else None,
        "acceptance_pass": acceptance.get("auto_pass") if isinstance(acceptance, dict) else None,
        "acceptance_total": acceptance.get("total") if isinstance(acceptance, dict) else None,
        "avg_wer": round(avg_wer * 100, 1) if isinstance(avg_wer, float) else None,
        "avg_mos": mos_avg,
        "mos_evaluations": mos_n,
        "wer_n": (agg or {}).get("n") if isinstance(agg, dict) else None,
    }


@router.get("/dashboard/overview")
async def dashboard_overview():
    from server import main as server_main

    live = telemetry.aggregate_overview()
    health = {
        "ok": True,
        "default_backend": server_main._normalize_backend(DEFAULT_TTS_BACKEND),
        "loaded_backends": list(server_main._pipelines.keys()),
        "tts_mock": False,
    }
    try:
        pipe = server_main._get_pipeline(DEFAULT_TTS_BACKEND)
        health["tts_mock"] = bool(getattr(pipe.backend, "_mock", False))
        health["tts_device"] = getattr(pipe.backend, "device", "cpu")
    except Exception as exc:  # noqa: BLE001
        health["ok"] = False
        health["error"] = str(exc)

    bench = _benchmark_snapshot()
    evaluation = _evaluation_snapshot()

    # Prefer live p99; fall back to benchmark artifact.
    p99 = live.get("p99_ttfa_ms")
    if p99 is None:
        p99 = bench.get("best_p99_ttfa_ms")

    # Product dashboard target (paste / SLA card). Config TTFA_TARGET_MS is
    # the aspirational edge path (~100ms).
    display_target_ms = 500

    return {
        "ok": True,
        "version": "v1.1 prototype",
        "status": {
            "engine_online": bool(health.get("ok")) and not health.get("tts_mock"),
            "label": "Engine online" if health.get("ok") else "Engine offline",
            "detail": (
                f"TTS runtime ready · {len(KNOWN_VOICES)} voices"
                if health.get("ok")
                else "TTS runtime unavailable"
            ),
            "default_backend": health.get("default_backend"),
            "loaded_backends": health.get("loaded_backends"),
            "device": health.get("tts_device"),
        },
        "kpis": {
            "syntheses": live["syntheses_total"],
            "syntheses_24h": live["syntheses_24h"],
            "avg_ttfa_ms": live["avg_ttfa_ms"],
            "min_ttfa_ms": live["min_ttfa_ms"],
            "max_ttfa_ms": live["max_ttfa_ms"],
            "audio_minutes": live["audio_minutes"],
            "p99_latency_ms": p99,
            "ttfa_target_ms": display_target_ms,
            "aspirational_ttfa_ms": TTFA_TARGET_MS,
        },
        "charts": {
            "activity_7d": live["activity_7d"],
            "language_mix": live["language_mix"],
            "voice_usage": live["voice_usage"],
            "ttfa_distribution": live["ttfa_distribution"],
            "trend_by_voice": live["trend_by_voice"],
            "trend_by_lang": live["trend_by_lang"],
            "heatmap": live["heatmap"],
            "funnel": live["funnel"],
        },
        "recent": live["recent"],
        "benchmark": bench,
        "evaluation": evaluation,
        "voices": KNOWN_VOICES,
        "quick_actions": [
            {
                "id": "studio",
                "title": "Generate speech",
                "body": "Try the TTS Studio with Tamil, English or Tanglish",
                "href": "/studio",
            },
            {
                "id": "phones",
                "title": "Two-phone test",
                "body": "QR-pair two phones for live STT → translate → TTS",
                "href": "/phones",
            },
            {
                "id": "scenarios",
                "title": "Browse scenarios",
                "body": "13 taxi contact-center use cases ready to use",
                "href": "/scenarios",
            },
            {
                "id": "benchmark",
                "title": "Run a load test",
                "body": "Check p99 latency at 15-20 concurrent requests",
                "href": "/benchmark",
            },
        ],
    }
