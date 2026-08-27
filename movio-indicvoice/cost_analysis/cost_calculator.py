"""
Cost calculator from concurrency results.

HARDWARE_COST_PER_HOUR is a configurable placeholder:
  - Local LOQ testing ≈ $0 marginal cost (not representative of production)
  - Typical cloud GPU tiers (T4 / A10G) roughly $0.50–1.50 / hour
Set based on actual intended deployment target before finalizing numbers.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    CONCURRENCY_RESULTS_DIR,
    COST_RESULTS_DIR,
    HARDWARE_COST_PER_HOUR,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("cost_analysis")

# Assumed average utterance duration when concurrency JSON lacks audio duration
DEFAULT_UTTERANCE_SEC = 3.0


def compute(cost_per_hour: float | None = None) -> dict:
    cost_per_hour = HARDWARE_COST_PER_HOUR if cost_per_hour is None else cost_per_hour
    src = CONCURRENCY_RESULTS_DIR / "latency_vs_concurrency.json"
    if not src.exists():
        logger.warning(
            "%s missing — writing placeholder cost rows from concurrency levels alone",
            src,
        )
        levels = [
            {"concurrency_level": c, "throughput_rps": None, "success_rate": None}
            for c in (1, 5, 10, 15, 20)
        ]
        ceiling = {"measured_ceiling": None, "note": "Run load_test.py first"}
    else:
        payload = json.loads(src.read_text(encoding="utf-8"))
        levels = payload.get("levels", [])
        ceiling = payload.get("ceiling", {})

    rows = []
    for level in levels:
        rps = level.get("throughput_rps") or 0.0
        # audio-minutes-generated-per-hour ≈ successful utterances/hour * duration
        utterances_per_hour = rps * 3600
        audio_minutes_per_hour = utterances_per_hour * (DEFAULT_UTTERANCE_SEC / 60.0)
        cost_per_min = (
            (cost_per_hour / audio_minutes_per_hour) if audio_minutes_per_hour > 0 else None
        )
        rows.append(
            {
                "concurrency_level": level.get("concurrency_level"),
                "throughput_rps": level.get("throughput_rps"),
                "success_rate": level.get("success_rate"),
                "audio_minutes_generated_per_hour": round(audio_minutes_per_hour, 2),
                "cost_per_generated_minute": None
                if cost_per_min is None
                else round(cost_per_min, 6),
                "hardware_cost_per_hour": cost_per_hour,
            }
        )

    result = {
        "hardware_cost_per_hour": cost_per_hour,
        "assumption_utterance_sec": DEFAULT_UTTERANCE_SEC,
        "notes": [
            "Local LOQ testing is ~$0 marginal cost but NOT representative of production.",
            "Typical cloud GPU tiers (T4/A10G) run roughly $0.50–1.50/hour — set HARDWARE_COST_PER_HOUR accordingly.",
            ceiling.get("note", ""),
        ],
        "rows": rows,
        "ceiling": ceiling,
    }
    COST_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = COST_RESULTS_DIR / "cost_summary.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    logger.info("Wrote %s", out)

    print(
        "concurrency | audio_min/hour | cost/min | success | rps"
    )
    for r in rows:
        print(
            f"{r['concurrency_level']:>11} | {r['audio_minutes_generated_per_hour']:>14} | "
            f"{r['cost_per_generated_minute']} | {r['success_rate']} | {r['throughput_rps']}"
        )
    return result


if __name__ == "__main__":
    compute()
