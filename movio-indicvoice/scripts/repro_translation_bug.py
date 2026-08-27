"""Reproduce the Tanglish translation quality bug (BEFORE snapshot).

Runs the pre-fix path end to end for the reported sentence and the adversarial
set, printing what actually reaches TTS. Kept in-repo so the BEFORE/AFTER
comparison is reproducible.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from normalization.deterministic_normalizer import normalize  # noqa: E402
from normalization.language_translator import translate  # noqa: E402
from normalization.speakability import prepare_for_latin_tts  # noqa: E402

SENTENCES = [
    "I'm standing near the security gate with a red suitcase, but the driver has "
    "stopped on the opposite side of the road, so please ask him to turn around "
    "and come to the main entrance.",
    "I am standing near the security gate with a red suitcase.",
    "The driver will arrive in five minutes.",
    "Please share the OTP 4821.",
    "I am waiting near the parking entrance.",
    "The driver is waiting near Guindy.",
    "I need to reach the airport before 7:30 PM.",
    "The driver has arrived.",
    "I am waiting near the security gate.",
    "The OTP is 4821.",
    "I need to reach the airport.",
    "Please wait for five minutes.",
]


def main() -> None:
    for s in SENTENCES:
        res = translate(s, "tanglish")
        det = normalize(res.text)
        latin = prepare_for_latin_tts(det)
        print("SOURCE   :", s)
        print("ENGINE   :", res.engine)
        print("TRANSLATE:", res.text)
        print("NORMALIZE:", det)
        print("LATIN-TTS:", latin)
        print("-" * 100)


if __name__ == "__main__":
    main()
