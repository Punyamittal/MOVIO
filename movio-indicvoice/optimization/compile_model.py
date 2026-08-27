"""
torch.compile() wrapper comparison against the local IndicF5 backend.

Edge TTS has no local torch model to compile. Saves
optimization/results/compilation_comparison.json
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
logger = logging.getLogger("optimization.compile")


def load_subset(n: int) -> list[str]:
    reviewed = DATA_GEN_OUTPUT_DIR / "combined_benchmark_reviewed.json"
    offline = BENCHMARK_DATA_DIR / "offline_sentences.json"
    path = reviewed if reviewed.exists() else offline
    items = json.loads(path.read_text(encoding="utf-8"))
    return [it["text"] for it in items[:n]]


def _time_runs(backend, texts: list[str]) -> list[float]:
    times = []
    for text in texts:
        t0 = time.perf_counter()
        backend.synthesize(text, DEFAULT_VOICE_STYLE)
        times.append((time.perf_counter() - t0) * 1000)
    return times


def main():
    import torch

    from tts_backends.indic_f5 import IndicF5Backend

    OPTIMIZATION_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    texts = load_subset(OPTIMIZATION_SENTENCE_COUNT)

    backend = IndicF5Backend()
    backend._lazy_load()

    before = _time_runs(backend, texts)
    before_avg = sum(before) / len(before)

    compile_note = None
    warmup_ms = None
    after = before
    after_avg = before_avg
    compiled = False

    if getattr(backend, "_mock", False) or getattr(backend, "_model", None) is None:
        compile_note = "Model mock mode — torch.compile skipped; timings are mock baselines."
        logger.warning(compile_note)
    else:
        try:
            t_warm0 = time.perf_counter()
            backend._model = torch.compile(backend._model)
            backend.synthesize(texts[0], DEFAULT_VOICE_STYLE)
            warmup_ms = (time.perf_counter() - t_warm0) * 1000
            after = _time_runs(backend, texts)
            after_avg = sum(after) / len(after)
            compiled = True
        except Exception as exc:  # noqa: BLE001
            compile_note = f"torch.compile failed/unsupported: {exc}"
            logger.warning(compile_note)

    result = {
        "backend": "indic_f5",
        "n": len(texts),
        "before_avg_generation_ms": round(before_avg, 2),
        "after_avg_generation_ms": round(after_avg, 2),
        "warmup_ms": None if warmup_ms is None else round(warmup_ms, 2),
        "steady_state_speedup": round(before_avg / after_avg, 3) if after_avg else None,
        "compiled": compiled,
        "note": compile_note,
        "before_ms_list": [round(x, 2) for x in before],
        "after_ms_list": [round(x, 2) for x in after],
    }
    out = OPTIMIZATION_RESULTS_DIR / "compilation_comparison.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    logger.info("Wrote %s", out)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
