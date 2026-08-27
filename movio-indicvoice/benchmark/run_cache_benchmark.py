"""
Before/after benchmark for layered TTS cache (full + clause + template).

Uses a counting mock backend so measurements isolate cache behaviour
(not network/GPU noise). Also runs an optional live win_sapi pass when available.

Run: python -m benchmark.run_cache_benchmark
"""
from __future__ import annotations

import json
import logging
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    BENCHMARK_DATA_DIR,
    BENCHMARK_RESULTS_DIR,
    DEFAULT_VOICE_STYLE,
)
from server.cache import AudioCache  # noqa: E402
from server.pipeline import TTSPipeline  # noqa: E402
from tts_backends.base import TTSBackend  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("benchmark.cache")


def _load_cache_pairs() -> list[str]:
    path = BENCHMARK_DATA_DIR / "taxi_driver_sentences.json"
    if not path.exists():
        return []
    items = json.loads(path.read_text(encoding="utf-8"))
    return [i["text"] for i in items if i.get("category") == "cache_pairs"]


# Prefer explicit cache-pair families from taxi_driver_sentences.json; fall back
# to a small built-in set if the file is missing.
_FALLBACK_PAIRS = [
    "Your driver will arrive in 5 minutes.",
    "Your driver will arrive in 10 minutes.",
    "Your driver will arrive in 15 minutes.",
    "Your driver will arrive in 20 minutes.",
    "Please share the OTP 4821.",
    "Please share the OTP 7392.",
    "Please share the OTP 6158.",
    "Please share the OTP 9043.",
    "Your driver is waiting near the main entrance.",
    "Your driver is waiting near the security gate.",
    "Your driver is waiting near the parking area.",
    "Your driver is waiting near the metro station.",
    "Please ask the driver to wait for five minutes.",
    "Please ask the driver to wait for ten minutes.",
    "Please ask the driver to wait for fifteen minutes.",
    "Please ask the driver to wait for twenty minutes.",
    "The driver will reach Guindy in ten minutes.",
    "The driver will reach Velachery in ten minutes.",
    "The driver will reach Adyar in ten minutes.",
    "The driver will reach T Nagar in ten minutes.",
    # Exact repeats for full-utterance hits
    "Your driver has arrived.",
    "Your driver has arrived.",
    "Please share the OTP.",
    "Please share the OTP.",
]

TAXI_DATASET = _load_cache_pairs() or _FALLBACK_PAIRS
if "Your driver has arrived." not in TAXI_DATASET:
    TAXI_DATASET = list(TAXI_DATASET) + [
        "Your driver has arrived.",
        "Your driver has arrived.",
        "Please share the OTP.",
        "Please share the OTP.",
    ]


class CountingBackend(TTSBackend):
    name = "bench_mock"
    audio_format = "wav"

    def __init__(self, delay_sec: float = 0.08):
        self.delay_sec = delay_sec
        self.calls = 0
        self.texts: list[str] = []

    def synthesize(self, text: str, voice_style: str) -> bytes:
        self.calls += 1
        self.texts.append(text)
        # Shorter units finish faster — models real TTS cost scaling with length
        scale = max(0.25, min(1.5, len(text) / 36.0))
        time.sleep(self.delay_sec * scale)
        # Minimal valid WAV
        import io
        import struct
        import wave

        sr = 22050
        n = max(int(0.2 * sr), int(0.02 * sr * max(1, len(text.split()))))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(struct.pack("<" + "h" * n, *([0] * n)))
        return buf.getvalue()


def _mean(xs: list[float]) -> float:
    return float(statistics.mean(xs)) if xs else 0.0


def run_pass(
    label: str,
    texts: list[str],
    *,
    clause: bool,
    template: bool,
    delay_sec: float = 0.08,
) -> dict:
    backend = CountingBackend(delay_sec=delay_sec)
    cache = AudioCache(512)
    pipe = TTSPipeline(
        backend=backend,
        cache=cache,
        skip_llm=True,
        translate_enabled=False,
        clause_cache=clause,
        template_cache=template,
    )
    e2e: list[float] = []
    full_lat: list[float] = []
    per: list[dict] = []
    for text in texts:
        t0 = time.perf_counter()
        result = pipe.run(text, DEFAULT_VOICE_STYLE, target_lang="en")
        wall = (time.perf_counter() - t0) * 1000
        e2e.append(wall)
        full_lat.append(result.timing.full_synthesis_ms())
        per.append(
            {
                "text": text,
                "normalized": result.normalized_text,
                "cache_hit": result.cache_hit,
                "cache_level": result.cache_level,
                "chunk_count": result.chunk_count,
                "units_from_cache": result.units_from_cache,
                "units_synthesized": result.units_synthesized,
                "e2e_ms": round(wall, 2),
                "full_synthesis_ms": round(result.timing.full_synthesis_ms(), 2),
            }
        )
    stats = cache.stats()
    return {
        "label": label,
        "clause_cache": clause,
        "template_cache": template,
        "tts_calls_total": backend.calls,
        "tts_texts": backend.texts,
        "avg_e2e_ms": round(_mean(e2e), 2),
        "avg_full_synthesis_ms": round(_mean(full_lat), 2),
        "cache_stats": stats,
        "per_request": per,
    }


def categorize_latencies(result: dict) -> dict:
    """Group measured e2e by scenario for the report table."""
    full_sentence = []
    repeated_clause = []
    template_rows = []
    for row in result["per_request"]:
        text = row["text"]
        e2e = row["e2e_ms"]
        if text in ("Your driver has arrived.", "Please share the OTP.", "Your ride will arrive shortly."):
            full_sentence.append(e2e)
        if "will arrive in" in text and "minutes" in text and ". Please" not in text:
            template_rows.append(e2e)
        if "waiting near" in text:
            template_rows.append(e2e)
        if text.startswith("Please share the OTP ") and any(c.isdigit() for c in text):
            template_rows.append(e2e)
        if ". " in text:
            repeated_clause.append(e2e)
    return {
        "full_sentence_avg_ms": round(_mean(full_sentence), 2),
        "repeated_clause_avg_ms": round(_mean(repeated_clause), 2),
        "template_avg_ms": round(_mean(template_rows), 2),
    }


def naturalness_probe(clause: bool, template: bool) -> dict:
    """
    Compare full-sentence synth vs stitched template units on duration/continuity
    proxies (listening still required for pitch/prosody judgment).
    """
    backend = CountingBackend(delay_sec=0.01)
    cache = AudioCache(64)
    # Force miss path for stitch: disable storing full until after
    pipe = TTSPipeline(
        backend=backend,
        cache=cache,
        skip_llm=True,
        translate_enabled=False,
        clause_cache=clause,
        template_cache=template,
        stitch_gap_ms=90,
    )
    text = "Your driver will arrive in five minutes."
    stitched = pipe.run(text, "v", target_lang="en")
    # Fresh pipeline without template stitch — synthesize whole normalized clause once
    backend2 = CountingBackend(delay_sec=0.01)
    pipe2 = TTSPipeline(
        backend=backend2,
        cache=None,
        skip_llm=True,
        translate_enabled=False,
        clause_cache=False,
        template_cache=False,
    )
    whole = pipe2._run_single(text, "v", target_lang="en")  # noqa: SLF001
    return {
        "text": text,
        "stitched_duration_sec": round(stitched.audio_duration_sec, 3),
        "whole_duration_sec": round(whole.audio_duration_sec, 3),
        "stitched_units": stitched.chunk_count,
        "duration_delta_sec": round(stitched.audio_duration_sec - whole.audio_duration_sec, 3),
        "note": (
            "Mock backend uses silence; duration delta reflects stitch gap only. "
            "Listen to live win_sapi/edge samples for pitch/prosody judgment."
        ),
    }


def try_live_sapi_sample() -> dict | None:
    try:
        from tts_backends.win_sapi import WinSapiBackend

        backend = WinSapiBackend()
        out_dir = BENCHMARK_RESULTS_DIR / "cache_naturalness"
        out_dir.mkdir(parents=True, exist_ok=True)
        cache = AudioCache(64)
        pipe = TTSPipeline(
            backend=backend,
            cache=cache,
            skip_llm=True,
            translate_enabled=False,
            clause_cache=True,
            template_cache=True,
        )
        text = "Your driver will arrive in five minutes."
        stitched = pipe.run(text, DEFAULT_VOICE_STYLE, target_lang="en")
        (out_dir / "stitched_template.wav").write_bytes(stitched.audio)
        pipe_whole = TTSPipeline(
            backend=backend,
            cache=None,
            skip_llm=True,
            translate_enabled=False,
            clause_cache=False,
            template_cache=False,
        )
        whole = pipe_whole._run_single(text, DEFAULT_VOICE_STYLE, target_lang="en")  # noqa: SLF001
        (out_dir / "whole_utterance.wav").write_bytes(whole.audio)
        return {
            "backend": "win_sapi",
            "stitched_path": str(out_dir / "stitched_template.wav"),
            "whole_path": str(out_dir / "whole_utterance.wav"),
            "stitched_ms": round(stitched.timing.end_to_end_ms(), 2),
            "whole_ms": round(whole.timing.end_to_end_ms(), 2),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("Live SAPI naturalness sample skipped: %s", exc)
        return None


def main() -> None:
    BENCHMARK_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # Warm identical dataset twice-worth of repeats already in list
    before = run_pass("BEFORE_full_only", TAXI_DATASET, clause=False, template=False)
    after_clause = run_pass("AFTER_full_clause", TAXI_DATASET, clause=True, template=False)
    after_full = run_pass(
        "AFTER_full_clause_template", TAXI_DATASET, clause=True, template=True
    )

    table = {
        "before": {**before, "categories": categorize_latencies(before)},
        "after_clause": {**after_clause, "categories": categorize_latencies(after_clause)},
        "after_clause_template": {
            **after_full,
            "categories": categorize_latencies(after_full),
        },
    }

    # Derived improvements
    def improve(a: float, b: float) -> dict:
        if a <= 0:
            return {"before": a, "after": b, "delta_ms": 0, "pct": 0}
        return {
            "before": a,
            "after": b,
            "delta_ms": round(a - b, 2),
            "pct": round(100.0 * (a - b) / a, 1),
        }

    comparison = {
        "tts_calls": {
            "before": before["tts_calls_total"],
            "after_clause": after_clause["tts_calls_total"],
            "after_clause_template": after_full["tts_calls_total"],
            "saved_vs_before_clause": before["tts_calls_total"] - after_clause["tts_calls_total"],
            "saved_vs_before_template": before["tts_calls_total"] - after_full["tts_calls_total"],
        },
        "avg_e2e_ms": {
            "before": before["avg_e2e_ms"],
            "after_clause": after_clause["avg_e2e_ms"],
            "after_clause_template": after_full["avg_e2e_ms"],
            "improvement_clause": improve(before["avg_e2e_ms"], after_clause["avg_e2e_ms"]),
            "improvement_template": improve(before["avg_e2e_ms"], after_full["avg_e2e_ms"]),
        },
        "cache_hit_rate": {
            "before": before["cache_stats"].get("cache_hit_rate"),
            "after_clause": after_clause["cache_stats"].get("cache_hit_rate"),
            "after_clause_template": after_full["cache_stats"].get("cache_hit_rate"),
        },
        "categories": {
            "before": table["before"]["categories"],
            "after_clause": table["after_clause"]["categories"],
            "after_clause_template": table["after_clause_template"]["categories"],
        },
    }

    # Recommendation: latency for phone calls matters more than raw TTS call count.
    # Template path may issue extra warm-up synths but still win on average e2e
    # when later slot variants only synthesize short dynamic units.
    tts_clause = after_clause["tts_calls_total"]
    tts_tmpl = after_full["tts_calls_total"]
    e2e_clause = after_clause["avg_e2e_ms"]
    e2e_tmpl = after_full["avg_e2e_ms"]
    latency_win = e2e_tmpl < e2e_clause * 0.97
    calls_win = tts_tmpl < tts_clause
    if latency_win or (calls_win and e2e_tmpl <= e2e_clause * 1.05):
        recommendation = "full + clause + template"
        reason = (
            f"Template path avg e2e {e2e_tmpl:.1f}ms vs clause-only {e2e_clause:.1f}ms "
            f"(TTS calls {tts_tmpl} vs {tts_clause}). "
            + (
                "Latency win from short dynamic-unit synthesis after static warm."
                if latency_win
                else "Fewer or similar TTS calls without e2e regression."
            )
        )
    else:
        recommendation = "full + clause"
        reason = (
            f"Template path did not clearly beat clause-only "
            f"(TTS {tts_tmpl} vs {tts_clause}, e2e {e2e_tmpl:.1f} vs {e2e_clause:.1f}ms)."
        )

    naturalness = {
        "mock": naturalness_probe(True, True),
        "live": try_live_sapi_sample(),
    }

    # Hit examples
    hits = [
        r
        for r in after_full["per_request"]
        if r["cache_hit"] or r["units_from_cache"] > 0
    ][:12]

    report = {
        "dataset_size": len(TAXI_DATASET),
        "comparison": comparison,
        "recommendation": recommendation,
        "recommendation_reason": reason,
        "naturalness": naturalness,
        "cache_hit_examples": hits,
        "raw": {
            "before_tts_texts": before["tts_texts"],
            "after_template_tts_texts": after_full["tts_texts"],
            "before_stats": before["cache_stats"],
            "after_clause_stats": after_clause["cache_stats"],
            "after_template_stats": after_full["cache_stats"],
        },
    }

    out = BENCHMARK_RESULTS_DIR / "cache_hierarchy_benchmark.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Wrote %s", out)

    print("\n=== Cache hierarchy benchmark ===")
    print(f"Dataset size: {len(TAXI_DATASET)}")
    print(
        f"TTS calls:  before={before['tts_calls_total']}  "
        f"clause={after_clause['tts_calls_total']}  "
        f"clause+template={after_full['tts_calls_total']}"
    )
    print(
        f"Avg e2e ms: before={before['avg_e2e_ms']}  "
        f"clause={after_clause['avg_e2e_ms']}  "
        f"clause+template={after_full['avg_e2e_ms']}"
    )
    print(
        f"Hit rate:   before={before['cache_stats'].get('cache_hit_rate')}  "
        f"clause={after_clause['cache_stats'].get('cache_hit_rate')}  "
        f"clause+template={after_full['cache_stats'].get('cache_hit_rate')}"
    )
    print(f"Recommendation: {recommendation}")
    print(f"Reason: {reason}")


if __name__ == "__main__":
    main()
