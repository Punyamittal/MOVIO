"""Measure preprocess vs synth split (TTFA breakdown)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from server.pipeline import TTSPipeline  # noqa: E402


def main() -> None:
    pipe = TTSPipeline(skip_llm=True)
    samples = [
        "Please share the OTP 4821.",
        "I'm standing near the security gate with a red suitcase, but the driver has "
        "stopped on the opposite side of the road, so please ask him to turn around "
        "and come to the main entrance.",
        "Tell the driver I am at the main gate with two bags.",
    ]
    for s in samples:
        t0 = time.perf_counter()
        text, ok, flags, meta = pipe.preprocess(s)
        pre_ms = (time.perf_counter() - t0) * 1000
        print(f"preprocess {pre_ms:8.1f}ms  engine={meta.get('translator_engine')}")
        print(f"  => {text[:100]}")
        print()


if __name__ == "__main__":
    main()
