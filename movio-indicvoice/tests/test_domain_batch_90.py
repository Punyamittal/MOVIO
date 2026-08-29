"""Verify domain batch (90 pickup/directions/payment/etc.) gold pairs."""
from __future__ import annotations

import csv
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from normalization.language_translator import translate  # noqa: E402
from normalization.tanglish_translator import clear_cache, exact_gold  # noqa: E402

_TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")
CSV_PATH = ROOT / "normalization" / "gold_batch_domain_90.csv"


def _load_csv() -> list[dict[str, str]]:
    with CSV_PATH.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class TestDomainBatch90(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = _load_csv()
        clear_cache()

    def test_csv_has_ninety_rows(self) -> None:
        self.assertEqual(len(self.rows), 90)

    def test_every_csv_row_hits_gold(self) -> None:
        for row in self.rows:
            english = (row.get("english") or "").strip()
            expected = (row.get("tanglish") or "").strip()
            with self.subTest(id=row.get("id"), category=row.get("category")):
                gold = exact_gold(english)
                self.assertIsNotNone(gold)
                assert gold is not None
                self.assertEqual(gold, expected)
                self.assertFalse(_TAMIL_RE.search(gold))
                r = translate(english, "tanglish")
                self.assertEqual(r.engine, "gold")
                self.assertEqual(r.text, expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
