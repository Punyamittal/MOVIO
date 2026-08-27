"""
Quantization comparison: baseline (FP32/BF16) vs FP16 vs attempted INT8.

INT8 via torch.quantization or bitsandbytes if architecture-compatible.
If INT8 is not feasible for this model class, that is logged as a valid
benchmark finding — not a failure.

Saves optimization/results/quantization_comparison.json and sample audio.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    BENCHMARK_DATA_DIR,
    DATA_GEN_OUTPUT_DIR,
    DEFAULT_VOICE_STYLE,
    OPTIMIZATION_RESULTS_DIR,
    OPTIMIZATION_SENTENCE_COUNT,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("optimization.quantize")


def load_subset(n: int) -> list[str]:
    reviewed = DATA_GEN_OUTPUT_DIR / "combined_benchmark_reviewed.json"
    offline = BENCHMARK_DATA_DIR / "offline_sentences.json"
    path = reviewed if reviewed.exists() else offline
    items = json.loads(path.read_text(encoding="utf-8"))
    return [it["text"] for it in items[:n]]


def _audio_size(audio: bytes) -> int:
    return len(audio)


def run_precision_benchmark(texts: list[str]) -> dict:
    import torch

    from tts_backends.indic_f5 import IndicF5Backend

    results = {"backend": "indic_f5", "precisions": {}, "notes": []}
    sample_dir = OPTIMIZATION_RESULTS_DIR / "audio_samples"
    sample_dir.mkdir(parents=True, exist_ok=True)

    # --- Baseline (BF16 if CUDA else FP32) ---
    baseline_name = "bf16" if torch.cuda.is_available() and torch.cuda.is_bf16_supported() else "fp32"
    backend = IndicF5Backend()
    backend._lazy_load()
    baseline = _bench_backend(backend, texts, sample_dir / f"{baseline_name}_0.wav")
    results["precisions"][baseline_name] = baseline

    # --- FP16 ---
    fp16_stats = {"status": "skipped", "reason": "cuda unavailable"}
    if torch.cuda.is_available() and not backend._mock:
        try:
            backend._model = backend._model.half()
            fp16_stats = _bench_backend(backend, texts, sample_dir / "fp16_0.wav")
            fp16_stats["status"] = "ok"
        except Exception as exc:  # noqa: BLE001
            fp16_stats = {"status": "failed", "error": str(exc)}
            results["notes"].append(f"FP16 cast failed: {exc}")
    else:
        # Mock path still records a comparable timing entry
        fp16_stats = _bench_backend(backend, texts, sample_dir / "fp16_0.wav")
        fp16_stats["status"] = "mock_or_cpu"
        results["notes"].append("FP16 on CUDA not applied; recorded mock/CPU timings")
    results["precisions"]["fp16"] = fp16_stats

    # --- INT8 attempt ---
    int8_stats: dict = {"status": "not_feasible"}
    try:
        int8_stats = _attempt_int8(backend, texts, sample_dir)
    except Exception as exc:  # noqa: BLE001
        int8_stats = {
            "status": "not_feasible",
            "error": str(exc),
            "note": (
                "INT8 not feasible for this model class / environment — "
                "valid benchmark finding, not a failure."
            ),
        }
        logger.warning("INT8 attempt not feasible: %s", exc)
    results["precisions"]["int8"] = int8_stats
    if int8_stats.get("status") == "not_feasible":
        results["notes"].append(int8_stats.get("note", "INT8 not feasible"))

    return results


def _bench_backend(backend, texts: list[str], sample_path: Path) -> dict:
    from server.pipeline import estimate_wav_duration

    times = []
    rtfs = []
    sizes = []
    for i, text in enumerate(texts):
        t0 = time.perf_counter()
        audio = backend.synthesize(text, DEFAULT_VOICE_STYLE)
        dt = time.perf_counter() - t0
        dur = estimate_wav_duration(audio)
        times.append(dt * 1000)
        rtfs.append(dt / dur if dur > 0 else 0.0)
        sizes.append(_audio_size(audio))
        if i == 0:
            sample_path.write_bytes(audio)
    return {
        "n": len(texts),
        "avg_generation_ms": round(sum(times) / len(times), 2),
        "avg_rtf": round(sum(rtfs) / len(rtfs), 4),
        "avg_file_size_bytes": int(sum(sizes) / len(sizes)),
        "sample_audio": str(sample_path),
    }


def _attempt_int8(backend, texts: list[str], sample_dir: Path) -> dict:
    """Try bitsandbytes or torch.quantization; raise/return not_feasible if incompatible."""
    import torch

    if backend._mock or backend._model is None:
        return {
            "status": "not_feasible",
            "note": "Model not loaded (mock mode); INT8 not applicable — valid finding.",
        }

    # Try bitsandbytes dynamic load
    try:
        import bitsandbytes as bnb  # noqa: F401

        logger.info("bitsandbytes present — dynamic INT8 for this TTS class is often unsupported")
    except ImportError:
        logger.info("bitsandbytes not installed")

    try:
        # Dynamic quantization typically targets Linear layers on CPU
        qmodel = torch.quantization.quantize_dynamic(
            backend._model.cpu(),
            {torch.nn.Linear},
            dtype=torch.qint8,
        )
        backend._model = qmodel
        backend.device = "cpu"
        stats = _bench_backend(backend, texts, sample_dir / "int8_0.wav")
        stats["status"] = "attempted_dynamic_int8_cpu"
        stats["note"] = (
            "Dynamic INT8 applied to Linear layers on CPU if architecture allowed; "
            "quality/speed may not represent GPU production path."
        )
        return stats
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "not_feasible",
            "error": str(exc),
            "note": (
                "INT8 not feasible for this model class — valid benchmark finding, not a failure."
            ),
        }


def main():
    OPTIMIZATION_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    texts = load_subset(OPTIMIZATION_SENTENCE_COUNT)
    logger.info("Quantization benchmark on %d sentences", len(texts))
    results = run_precision_benchmark(texts)
    out = OPTIMIZATION_RESULTS_DIR / "quantization_comparison.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    logger.info("Wrote %s", out)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
