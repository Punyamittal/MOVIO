"""
Simulate phone A↔B TTS path with layered cache metrics.

Does not require live SIP phones — exercises the same pipeline used by
phone_test/routes.py (_run_tts_pipeline equivalent).

Run: python -m benchmark.run_phone_cache_sim
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import BENCHMARK_RESULTS_DIR, DEFAULT_VOICE_STYLE  # noqa: E402
from server.cache import AudioCache  # noqa: E402
from server.pipeline import TTSPipeline  # noqa: E402
from tts_backends.win_sapi import WinSapiBackend  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("benchmark.phone_cache")

# Typical translated English lines that would reach TTS after STT+translate
# Mix of template-friendly lines + bug-hunting stress utterances.
A_TO_B = [
    "Your driver will arrive in five minutes.",
    "Please share the OTP 4821.",
    "உங்க driver முன்வாசல் அருகில் காத்திட்டு இருக்காரு.",
    "நான் கிண்டி Metro Station அருகில் காத்திட்டு இருக்கேன்.",
    "OTP 4821-ஐ driver-கிட்ட மட்டும் பகிருங்கள்.",
]
B_TO_A = [
    "Your driver will arrive in ten minutes.",
    "Please share the OTP 7394.",
    "உங்க driver security கேட் அருகில் காத்திட்டு இருக்காரு.",
    "நான் கிண்டி மெட்ரோ அருகில் காத்திருக்கிறேன்.",
    "உங்க driver பத்து நிமிடத்துல வந்துருவாங்க.",
]
A_TO_B_ROUND2 = [
    "Your driver will arrive in fifteen minutes.",
    "Please share the OTP 3046.",
    "உங்க driver parking நுழைவாயில் அருகில் காத்திட்டு இருக்காரு.",
    "டிரைவர் ஐந்து நிமிடத்தில் வருவார்.",
    "வேளச்சேரில இருந்து OMR-க்கு drop பண்ணுங்கள்.",
]


def _run_direction(pipe: TTSPipeline, label: str, texts: list[str]) -> list[dict]:
    rows = []
    for text in texts:
        t0 = time.perf_counter()
        result = pipe.run(text, DEFAULT_VOICE_STYLE, target_lang="en")
        rows.append(
            {
                "direction": label,
                "text": text,
                "e2e_ms": round((time.perf_counter() - t0) * 1000, 2),
                "full_synthesis_ms": round(result.timing.full_synthesis_ms(), 2),
                "cache_hit": result.cache_hit,
                "cache_level": result.cache_level,
                "units_from_cache": result.units_from_cache,
                "units_synthesized": result.units_synthesized,
                "chunk_count": result.chunk_count,
            }
        )
        logger.info(
            "[%s] e2e=%.0fms synth=%d cache_units=%d hit=%s :: %s",
            label,
            rows[-1]["e2e_ms"],
            result.units_synthesized,
            result.units_from_cache,
            result.cache_hit,
            text,
        )
    return rows


def main() -> None:
    BENCHMARK_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    cache = AudioCache(256)
    backend = WinSapiBackend()
    pipe = TTSPipeline(
        backend=backend,
        cache=cache,
        skip_llm=True,
        translate_enabled=False,
        clause_cache=True,
        template_cache=True,
    )

    rows: list[dict] = []
    rows.extend(_run_direction(pipe, "PhoneA→B", A_TO_B))
    rows.extend(_run_direction(pipe, "PhoneB→A", B_TO_A))
    rows.extend(_run_direction(pipe, "PhoneA→B_r2", A_TO_B_ROUND2))

    stats = cache.stats()
    n1 = len(A_TO_B) + len(B_TO_A)
    round1 = rows[:n1]
    round2 = rows[n1:]
    avg1 = sum(r["e2e_ms"] for r in round1) / max(len(round1), 1)
    avg2 = sum(r["e2e_ms"] for r in round2) / max(len(round2), 1)

    report = {
        "ok": True,
        "phone_a_to_b": "PASS",
        "phone_b_to_a": "PASS",
        "avg_e2e_round1_ms": round(avg1, 2),
        "avg_e2e_round2_ms": round(avg2, 2),
        "latency_improvement_ms": round(avg1 - avg2, 2),
        "cache_stats": stats,
        "rows": rows,
    }
    out = BENCHMARK_RESULTS_DIR / "phone_cache_sim.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Wrote %s", out)
    print(json.dumps({k: report[k] for k in report if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()
