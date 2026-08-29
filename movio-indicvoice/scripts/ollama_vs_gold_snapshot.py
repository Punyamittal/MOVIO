"""One-off: compare Ollama raw output vs gold for compound sentences."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import TANGLISH_MODEL  # noqa: E402
from normalization.tanglish_translator import build_messages, call_model, exact_gold  # noqa: E402

SAMPLES = [
    "The app is showing that my driver has already reached the pickup point, but I've been standing outside for the last ten minutes and I don't see any car nearby, so I think either the GPS is showing the wrong location or he's waiting at a completely different gate.",
    "Since it's raining heavily right now and the traffic near the flyover is completely blocked because of a diversion, I think it would be better if the driver takes the inner road route instead of the main road, even if it takes a few extra minutes, because at least we won't be stuck for an hour.",
    "Before you drop me off, could you please wait for exactly two minutes near the gate because I need to run inside and grab a package that I forgot, and I promise it won't take any longer than that since the security guard already has it ready at the front desk.",
]


def main() -> None:
    for i, en in enumerate(SAMPLES, 1):
        gold = exact_gold(en)
        print(f"\n{'='*72}\n#{i} EN:\n{en}\n")
        print(f"GOLD:\n{gold}\n")
        try:
            msgs = build_messages(en, examples=[])
            out, ms = call_model(
                msgs, model=TANGLISH_MODEL, source=en, temperature=0.3, timeout=120
            )
            print(f"OLLAMA ({ms:.0f}ms):\n{out}\n")
        except Exception as exc:
            print(f"OLLAMA ERROR: {exc}\n")


if __name__ == "__main__":
    main()
