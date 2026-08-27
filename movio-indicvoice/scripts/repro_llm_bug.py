"""Show what the pre-fix Ollama prompt produces for the reported sentence."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from normalization.language_translator import _ollama_translate  # noqa: E402

SENTENCES = [
    "I'm standing near the security gate with a red suitcase, but the driver has "
    "stopped on the opposite side of the road, so please ask him to turn around "
    "and come to the main entrance.",
    "I am standing near the security gate with a red suitcase.",
    "The driver will arrive in five minutes.",
    "I need to reach the airport.",
]

for s in SENTENCES:
    print("SOURCE:", s)
    for i in range(2):
        try:
            print(f"  run{i}:", _ollama_translate(s, "tanglish"))
        except Exception as exc:  # noqa: BLE001
            print(f"  run{i}: FAILED {exc}")
    print("-" * 100)
