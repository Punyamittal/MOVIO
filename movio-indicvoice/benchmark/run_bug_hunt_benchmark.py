"""
Run bug-hunting utterances through the layered TTS cache pipeline.

Uses benchmark/data/bug_hunting_sentences.json — long speech, OTP/numbers,
names/places, questions, confusables, informal, and translation-stress lines.

Reports per-category latency, clause/template cache behaviour, and
normalization fingerprints (OTP digits, place lexicon).

Run: python -m benchmark.run_bug_hunt_benchmark
"""
from __future__ import annotations

import json
import logging
import statistics
import sys
import time
from collections import defaultdict
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
logger = logging.getLogger("benchmark.bug_hunt")

DATA_PATH = BENCHMARK_DATA_DIR / "bug_hunting_sentences.json"
TAXI_DRIVER_PATH = BENCHMARK_DATA_DIR / "taxi_driver_sentences.json"


class CountingBackend(TTSBackend):
    name = "bug_hunt_mock"
    audio_format = "wav"

    def __init__(self, delay_sec: float = 0.05):
        self.delay_sec = delay_sec
        self.calls = 0
        self.texts: list[str] = []

    def synthesize(self, text: str, voice_style: str) -> bytes:
        import io
        import struct
        import wave

        self.calls += 1
        self.texts.append(text)
        scale = max(0.2, min(2.0, len(text) / 40.0))
        time.sleep(self.delay_sec * scale)
        sr = 22050
        n = max(int(0.15 * sr), int(0.012 * sr * max(1, len(text.split()))))
        frames = [((ord(text[i % len(text)]) % 40) - 20) * 80 for i in range(min(64, n))]
        frames.extend([0] * (n - len(frames)))
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(struct.pack("<" + "h" * n, *frames))
        return buf.getvalue()


def _mean(xs: list[float]) -> float:
    return float(statistics.mean(xs)) if xs else 0.0


def load_items() -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    for path in (DATA_PATH, TAXI_DRIVER_PATH):
        if not path.exists():
            logger.warning("Missing dataset %s", path)
            continue
        chunk = json.loads(path.read_text(encoding="utf-8"))
        for item in chunk:
            text = (item.get("text") or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            items.append(item)
    if not items:
        raise FileNotFoundError(f"No sentences in {DATA_PATH} or {TAXI_DRIVER_PATH}")
    return items

def run_suite(items: list[dict], *, clause: bool, template: bool, label: str) -> dict:
    backend = CountingBackend()
    cache = AudioCache(8192)
    pipe = TTSPipeline(
        backend=backend,
        cache=cache,
        skip_llm=True,
        translate_enabled=False,
        clause_cache=clause,
        template_cache=template,
    )
    rows = []
    by_cat: dict[str, list[float]] = defaultdict(list)
    # Pass 1: cold / building cache
    for item in items:
        text = item["text"]
        t0 = time.perf_counter()
        result = pipe.run(text, DEFAULT_VOICE_STYLE, target_lang="en")
        e2e = (time.perf_counter() - t0) * 1000
        by_cat[item.get("category", "unknown")].append(e2e)
        rows.append(
            {
                "pass": 1,
                "category": item.get("category"),
                "stress": item.get("stress"),
                "text": text,
                "normalized": result.normalized_text,
                "e2e_ms": round(e2e, 2),
                "full_synthesis_ms": round(result.timing.full_synthesis_ms(), 2),
                "chunk_count": result.chunk_count,
                "cache_hit": result.cache_hit,
                "cache_level": result.cache_level,
                "units_from_cache": result.units_from_cache,
                "units_synthesized": result.units_synthesized,
                "audio_duration_sec": round(result.audio_duration_sec, 3),
            }
        )
    # Pass 2: identical replay (full-utterance hits)
    for item in items:
        text = item["text"]
        t0 = time.perf_counter()
        result = pipe.run(text, DEFAULT_VOICE_STYLE, target_lang="en")
        e2e = (time.perf_counter() - t0) * 1000
        rows.append(
            {
                "pass": 2,
                "category": item.get("category"),
                "text": text,
                "e2e_ms": round(e2e, 2),
                "cache_hit": result.cache_hit,
                "cache_level": result.cache_level,
                "units_from_cache": result.units_from_cache,
                "units_synthesized": result.units_synthesized,
            }
        )

    pass1 = [r for r in rows if r["pass"] == 1]
    pass2 = [r for r in rows if r["pass"] == 2]
    e2e_bug = next(
        (r["e2e_ms"] for r in pass1 if r.get("category") == "bug_hunting_e2e"),
        None,
    )
    return {
        "label": label,
        "clause_cache": clause,
        "template_cache": template,
        "n_items": len(items),
        "tts_calls_total": backend.calls,
        "cache_stats": cache.stats(),
        "pass1_avg_e2e_ms": round(_mean([r["e2e_ms"] for r in pass1]), 2),
        "pass2_avg_e2e_ms": round(_mean([r["e2e_ms"] for r in pass2]), 2),
        "pass2_full_hit_rate": round(
            sum(1 for r in pass2 if r.get("cache_level") == "full" or r.get("cache_hit"))
            / max(len(pass2), 1),
            4,
        ),
        "by_category_avg_e2e_ms": {
            k: round(_mean(v), 2) for k, v in sorted(by_cat.items())
        },
        "bug_hunting_e2e_ms": e2e_bug,
        "long_avg_chunks": round(
            _mean([r["chunk_count"] for r in pass1 if r.get("category") == "long"]),
            2,
        ),
        "otp_normalized_samples": [
            {"text": r["text"], "normalized": r["normalized"]}
            for r in pass1
            if r.get("category") == "numbers_otp"
        ][:4],
        "place_normalized_samples": [
            {"text": r["text"], "normalized": r["normalized"]}
            for r in pass1
            if r.get("category") == "names_places"
        ][:4],
        "rows": rows,
    }


def main() -> None:
    BENCHMARK_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    items = load_items()
    logger.info(
        "Loaded %d sentences from bug_hunting + taxi_driver datasets",
        len(items),
    )

    before = run_suite(items, clause=False, template=False, label="BEFORE_full_only")
    after = run_suite(
        items, clause=True, template=True, label="AFTER_full_clause_template"
    )

    report = {
        "dataset": [str(DATA_PATH), str(TAXI_DRIVER_PATH)],
        "dataset_size": len(items),
        "categories": sorted({i.get("category") for i in items}),
        "comparison": {
            "tts_calls": {
                "before": before["tts_calls_total"],
                "after": after["tts_calls_total"],
                "saved": before["tts_calls_total"] - after["tts_calls_total"],
            },
            "pass1_avg_e2e_ms": {
                "before": before["pass1_avg_e2e_ms"],
                "after": after["pass1_avg_e2e_ms"],
                "delta_ms": round(
                    before["pass1_avg_e2e_ms"] - after["pass1_avg_e2e_ms"], 2
                ),
            },
            "pass2_avg_e2e_ms": {
                "before": before["pass2_avg_e2e_ms"],
                "after": after["pass2_avg_e2e_ms"],
                "delta_ms": round(
                    before["pass2_avg_e2e_ms"] - after["pass2_avg_e2e_ms"], 2
                ),
            },
            "pass2_full_hit_rate": {
                "before": before["pass2_full_hit_rate"],
                "after": after["pass2_full_hit_rate"],
            },
            "bug_hunting_e2e_ms": {
                "before": before["bug_hunting_e2e_ms"],
                "after": after["bug_hunting_e2e_ms"],
            },
            "by_category_after": after["by_category_avg_e2e_ms"],
        },
        "normalization_samples": {
            "otp": after["otp_normalized_samples"],
            "places": after["place_normalized_samples"],
        },
        "cache_stats_after": after["cache_stats"],
        "long_avg_chunks_after": after["long_avg_chunks"],
    }
    out = BENCHMARK_RESULTS_DIR / "bug_hunt_benchmark.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logger.info("Wrote %s", out)

    print("\n=== Bug-hunt TTS/cache benchmark ===")
    print(f"Sentences: {len(items)}")
    print(
        f"Pass1 e2e: before={before['pass1_avg_e2e_ms']}ms  "
        f"after={after['pass1_avg_e2e_ms']}ms"
    )
    print(
        f"Pass2 e2e: before={before['pass2_avg_e2e_ms']}ms  "
        f"after={after['pass2_avg_e2e_ms']}ms  "
        f"(full hit rate after={after['pass2_full_hit_rate']})"
    )
    print(
        f"TTS calls: before={before['tts_calls_total']}  after={after['tts_calls_total']}"
    )
    print(
        f"Bug-hunting E2E sentence: before={before['bug_hunting_e2e_ms']}ms  "
        f"after={after['bug_hunting_e2e_ms']}ms"
    )
    print("By category (after, pass1 avg e2e ms):")
    for k, v in after["by_category_avg_e2e_ms"].items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
