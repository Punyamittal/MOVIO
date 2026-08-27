"""Quick latency + completeness check after the fix."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from normalization.language_translator import translate  # noqa: E402

SAMPLES = [
    "I'm standing near the security gate with a red suitcase, but the driver has "
    "stopped on the opposite side of the road, so please ask him to turn around "
    "and come to the main entrance.",
    "The driver will arrive in five minutes because of heavy traffic near the pickup.",
    "Please share the OTP 4821.",
    "I need to reach the airport before 7:30 PM.",
]


def main() -> None:
    for s in SAMPLES:
        t0 = time.perf_counter()
        r = translate(s, "tanglish")
        ms = (time.perf_counter() - t0) * 1000
        print(f"[{ms:7.0f}ms | {r.engine}]")
        print(f"  SRC: {s}")
        print(f"  OUT: {r.text}")
        print(f"  words in/out: {len(s.split())}/{len(r.text.split())}")
        print()


if __name__ == "__main__":
    main()
