"""Final acceptance check: problem sentence, consecutive leakage, phone dirs."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from normalization.language_translator import translate  # noqa: E402
from normalization.tanglish_translator import (  # noqa: E402
    clear_cache,
    reload_gold,
    translate_to_tanglish,
)
from normalization.translation_validator import validate_translation  # noqa: E402

BEFORE = (
    "En, nammal aana security gate la neerla suitcase irukku, driver aana "
    "opposite side la road la, aana turn around pannunga, main entrance la "
    "come pannunga, OTP la send pannunga, cab la waiting pannunga, parking "
    "la find pannunga, minutes la wait pannunga."
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


def main() -> None:
    reload_gold()
    clear_cache()

    print("=== BEFORE (reported hallucination) ===")
    print(BEFORE)
    print()

    t0 = time.perf_counter()
    r = translate(PROBLEM, "tanglish")
    ms = (time.perf_counter() - t0) * 1000
    print("=== AFTER (pipeline translate) ===")
    print(r.text)
    print(f"engine={r.engine} latency={ms:.0f}ms")
    print("validator:", validate_translation(PROBLEM, r.text).flags or "PASS")
    print()

    print("=== CONSECUTIVE (no leakage) ===")
    clear_cache()
    for src in SEQ:
        rr = translate_to_tanglish(src)
        print(f"SRC: {src}")
        print(f"OUT: {rr.text}  [{rr.engine}]")
        print()

    print("=== Phone A→B (EN→Tanglish) ===")
    ab = translate("Please share the OTP 4821.", "tanglish")
    print(ab.engine, "=>", ab.text)
    print("PASS" if "4821" in ab.text and "otp" in ab.text.lower() else "FAIL")

    print("=== Phone B→A (Tanglish→EN) ===")
    ba = translate("OTP 4821 share pannunga.", "en")
    print(ba.engine, "=>", ba.text)
    low = ba.text.lower()
    print("PASS" if "otp" in low and ("4821" in ba.text or "four" in low) else "FAIL")


if __name__ == "__main__":
    main()
