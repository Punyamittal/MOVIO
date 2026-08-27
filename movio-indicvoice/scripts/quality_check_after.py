"""Warm the model and print BEFORE/AFTER quality checks."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from normalization.tanglish_translator import (  # noqa: E402
    clear_cache,
    translate_to_tanglish,
    warmup,
)

PROBLEM = (
    "I'm standing near the security gate with a red suitcase, but the driver has "
    "stopped on the opposite side of the road, so please ask him to turn around "
    "and come to the main entrance."
)

SEQ = [
    "The driver has arrived.",
    "I am waiting near the security gate.",
    "The OTP is 4821.",
    "I need to reach the airport.",
    "Please wait for five minutes.",
]

EXTRA = [
    "I am standing near the security gate with a red suitcase.",
    "The driver will arrive in five minutes.",
    "Please share the OTP 4821.",
    "I am waiting near the parking entrance.",
    "The driver is waiting near Guindy.",
    "I need to reach the airport before 7:30 PM.",
]


def main() -> None:
    print("warming...", flush=True)
    print("warm=", warmup(), flush=True)
    clear_cache()

    print("\n=== PROBLEM SENTENCE ===", flush=True)
    r = translate_to_tanglish(PROBLEM, use_cache=False)
    print(r.debug_block(), flush=True)

    print("=== CONSECUTIVE ===", flush=True)
    for x in SEQ:
        rr = translate_to_tanglish(x, use_cache=False)
        print(f"SRC: {x}", flush=True)
        print(
            f"OUT: {rr.text}  [{rr.engine} {rr.latency_ms:.0f}ms ok={rr.ok} flags={rr.flags}]",
            flush=True,
        )
        print(flush=True)

    print("=== ADVERSARIAL ===", flush=True)
    for x in EXTRA:
        rr = translate_to_tanglish(x, use_cache=False)
        print(f"SRC: {x}", flush=True)
        print(
            f"OUT: {rr.text}  [{rr.engine} {rr.latency_ms:.0f}ms ok={rr.ok}]",
            flush=True,
        )
        print(flush=True)


if __name__ == "__main__":
    main()
