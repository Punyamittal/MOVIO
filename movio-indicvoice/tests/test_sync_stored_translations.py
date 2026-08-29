"""Stored benchmark refs must match tanglish_gold_pairs.json."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from normalization.tanglish_translator import _normalize_key, exact_gold  # noqa: E402

TAXI_PATH = ROOT / "benchmark" / "data" / "taxi_driver_sentences.json"
GOLD_PATH = ROOT / "normalization" / "tanglish_gold_pairs.json"
BENCH_GOLD_PATH = ROOT / "benchmark" / "data" / "tanglish_gold_pairs.json"


class TestStoredTranslationsMatchGold(unittest.TestCase):
    def test_benchmark_gold_copy_matches_canonical(self):
        self.assertEqual(
            GOLD_PATH.read_bytes(),
            BENCH_GOLD_PATH.read_bytes(),
            "run scripts/sync_stored_translations_from_gold.py",
        )

    def test_taxi_tanglish_ref_matches_gold(self):
        taxi = json.loads(TAXI_PATH.read_text(encoding="utf-8"))
        gold_rows = json.loads(GOLD_PATH.read_text(encoding="utf-8"))
        gold_keys = {
            _normalize_key(r["english"])
            for r in gold_rows
            if (r.get("english") or "").strip() and (r.get("tanglish") or "").strip()
        }

        mismatches: list[str] = []
        missing_ref: list[str] = []
        missing_row: list[str] = []

        taxi_keys: set[str] = set()
        for row in taxi:
            en = (row.get("text") or "").strip()
            if not en:
                continue
            key = _normalize_key(en)
            taxi_keys.add(key)
            gold = exact_gold(en)
            if not gold:
                continue
            ref = (row.get("tanglish_ref") or "").strip()
            if not ref:
                missing_ref.append(en[:80])
            elif ref != gold:
                mismatches.append(en[:80])

        for key in gold_keys - taxi_keys:
            missing_row.append(key[:80])

        self.assertEqual(mismatches, [], f"tanglish_ref mismatches: {mismatches[:5]}")
        self.assertEqual(missing_ref, [], f"missing tanglish_ref: {missing_ref[:5]}")
        self.assertEqual(missing_row, [], f"gold not in taxi: {missing_row[:5]}")


if __name__ == "__main__":
    unittest.main()
