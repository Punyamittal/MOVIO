"""
Single-request benchmark across both TTS backends.

Records full timestamp breakdown per request. TTFA and full-synthesis latency
are stored and summarized separately (never collapsed).

Falls back to benchmark/data/offline_sentences.json if reviewed set is absent.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.metrics import print_comparison_table, summarize_latencies  # noqa: E402
from config import (  # noqa: E402
    BENCHMARK_DATA_DIR,
    BENCHMARK_RESULTS_DIR,
    DATA_GEN_OUTPUT_DIR,
    DEFAULT_VOICE_STYLE,
)
from server.pipeline import TTSPipeline  # noqa: E402
from tts_backends.edge_fast import EdgeFastBackend  # noqa: E402
from tts_backends.indic_f5 import IndicF5Backend  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("benchmark.run")


def load_benchmark_items() -> list[dict]:
    reviewed = DATA_GEN_OUTPUT_DIR / "combined_benchmark_reviewed.json"
    combined = DATA_GEN_OUTPUT_DIR / "combined_benchmark.json"
    offline = BENCHMARK_DATA_DIR / "offline_sentences.json"
    for path in (reviewed, combined, offline):
        if path.exists():
            logger.info("Loading benchmark texts from %s", path)
            return json.loads(path.read_text(encoding="utf-8"))
    raise FileNotFoundError("No benchmark data found")


def run_backend(name: str, backend, items: list[dict]) -> dict:
    pipe = TTSPipeline(backend=backend, skip_llm=True)
    audio_dir = BENCHMARK_RESULTS_DIR / "audio" / name
    audio_dir.mkdir(parents=True, exist_ok=True)

    per_request = []
    ttfa, full, rtf = [], [], []
    for i, item in enumerate(items):
        text = item["text"]
        result = pipe.run(text, DEFAULT_VOICE_STYLE)
        wav_path = audio_dir / f"{i}.wav"
        wav_path.write_bytes(result.audio)
        metrics = result.metrics_dict()
        metrics.update(
            {
                "index": i,
                "text": text,
                "category": item.get("category"),
                "timestamps": {
                    "request_received": result.timing.request_received,
                    "normalization_complete": result.timing.normalization_complete,
                    "tts_started": result.timing.tts_started,
                    "first_audio_generated": result.timing.first_audio_generated,
                    "first_audio_sent": result.timing.first_audio_sent,
                    "generation_complete": result.timing.generation_complete,
                    "response_complete": result.timing.response_complete,
                },
            }
        )
        per_request.append(metrics)
        ttfa.append(metrics["ttfa_ms"])
        full.append(metrics["full_synthesis_ms"])
        rtf.append(metrics["rtf"])
        logger.info(
            "[%s %d] ttfa_ms=%.1f full_synthesis_ms=%.1f rtf=%.3f",
            name,
            i,
            metrics["ttfa_ms"],
            metrics["full_synthesis_ms"],
            metrics["rtf"],
        )

    summary = summarize_latencies(ttfa, full, rtf)
    return {"backend": name, "summary": summary, "per_request": per_request}


def main():
    BENCHMARK_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    items = load_benchmark_items()
    by_backend = {}
    all_results = {}

    for name, backend in (
        ("edge_fast", EdgeFastBackend()),
        ("indic_f5", IndicF5Backend()),
    ):
        logger.info("=== Benchmarking %s (%d sentences) ===", name, len(items))
        result = run_backend(name, backend, items)
        by_backend[name] = result["summary"]
        all_results[name] = result

    out = {
        "note": "ttfa_ms and full_synthesis_ms are distinct — do not collapse them.",
        "backends": all_results,
        "comparison": by_backend,
    }
    summary_path = BENCHMARK_RESULTS_DIR / "summary.json"
    summary_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    logger.info("Wrote %s", summary_path)
    print_comparison_table(by_backend)


if __name__ == "__main__":
    main()
