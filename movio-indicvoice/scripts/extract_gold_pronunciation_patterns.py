"""
Mine gold Tanglish for pronunciation gaps and suffix patterns.

Usage:
  python scripts/extract_gold_pronunciation_patterns.py
  python scripts/extract_gold_pronunciation_patterns.py --write
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from normalization.gold_phonetic_loader import mine_gold_tokens  # noqa: E402
from normalization.pronunciation_rules import (  # noqa: E402
    clear_pronunciation_cache,
    load_pronunciation_lexicon,
)

_PATTERNS_PATH = ROOT / "normalization" / "gold_phonetic_patterns.json"
_SUFFIXES = (
    "nu sollunga",
    "pannunga sollunga",
    "thappa iruku",
    "driver-kitta sollunga",
    "ku vandhuduchu",
    "pakkathula wait",
    "konjam neram",
    "illa nu",
    "venaam nu",
)


def _existing_tokens() -> set[str]:
    lex = load_pronunciation_lexicon()
    known = {str(r.get("token", "")).lower() for r in lex.get("tokens", [])}
    if _PATTERNS_PATH.exists():
        data = json.loads(_PATTERNS_PATH.read_text(encoding="utf-8"))
        known |= {str(r.get("token", "")).lower() for r in data.get("tokens", [])}
    return known


def _suffix_counts(min_count: int = 5) -> list[tuple[str, int]]:
    from normalization.gold_phonetic_loader import _GOLD_PATH

    rows = json.loads(_GOLD_PATH.read_text(encoding="utf-8"))
    counts: Counter[str] = Counter()
    for row in rows:
        t = (row.get("tanglish") or "").lower()
        for suf in _SUFFIXES:
            if suf in t:
                counts[suf] += 1
    return [(s, n) for s, n in counts.most_common() if n >= min_count]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Append missing high-freq tokens to patterns file")
    parser.add_argument("--min-count", type=int, default=8)
    args = parser.parse_args()

    clear_pronunciation_cache()
    freq = mine_gold_tokens(min_count=args.min_count)
    known = _existing_tokens()
    missing = sorted(
        ((tok, cnt) for tok, cnt in freq.items() if tok.lower() not in known and tok.isalpha()),
        key=lambda x: (-x[1], x[0]),
    )

    print(f"Gold tokens (>={args.min_count} hits): {len(freq)}")
    print(f"Missing from lexicon+patterns: {len(missing)}")
    for tok, cnt in missing[:40]:
        print(f"  {tok:20s} {cnt}")

    print("\nSuffix patterns in gold:")
    for suf, cnt in _suffix_counts():
        print(f"  {suf:30s} {cnt}")

    if args.write and missing:
        data = json.loads(_PATTERNS_PATH.read_text(encoding="utf-8")) if _PATTERNS_PATH.exists() else {
            "version": 1,
            "tokens": [],
            "suffix_patterns": [],
        }
        have = {str(r.get("token", "")).lower() for r in data.get("tokens", [])}
        for tok, _cnt in missing[:25]:
            if tok.lower() in have:
                continue
            data["tokens"].append(
                {
                    "token": tok,
                    "phonetic": tok,
                    "compact_phonetic": tok,
                    "hyphenated": tok,
                    "note": "auto-mined from gold; review phonetic",
                }
            )
        _PATTERNS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"\nWrote {len(data['tokens'])} pattern tokens to {_PATTERNS_PATH}")


if __name__ == "__main__":
    main()
