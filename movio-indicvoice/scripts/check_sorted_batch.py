"""Check domain batch CSV (sorted by category) through the live translation path."""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from normalization.language_translator import to_tanglish  # noqa: E402
from normalization.tanglish_translator import clear_cache  # noqa: E402

CSV_PATH = ROOT / "normalization" / "gold_batch_domain_90.csv"


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
    rows.sort(key=lambda r: (r.get("category", ""), int(r["id"]) if str(r.get("id", "")).isdigit() else r.get("id", "")))
    clear_cache()

    by_engine: dict[str, int] = defaultdict(int)
    by_cat: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    problems: list[tuple[str, str, str, str]] = []

    for row in rows:
        en = (row.get("english") or "").strip()
        exp = (row.get("tanglish") or "").strip()
        cat = row.get("category") or "?"
        out, engine = to_tanglish(en, "en")
        by_engine[engine] += 1
        by_cat[cat][engine] += 1
        if out.strip().lower() == en.strip().lower():
            problems.append((cat, row.get("id", "?"), engine, "PURE_ENGLISH"))
        elif engine != "gold" or out != exp:
            problems.append((cat, row.get("id", "?"), engine, out[:80]))

    print(f"DOMAIN BATCH 90 — sorted by category ({len(rows)} sentences)")
    print("Engines:", dict(sorted(by_engine.items(), key=lambda x: -x[1])))
    print()
    for cat in sorted(by_cat):
        print(f"  {cat}: {dict(by_cat[cat])}")
    print()
    print(f"Problems: {len(problems)}")
    for p in problems:
        print(f"  [{p[0]} #{p[1]}] {p[2]} — {p[3]}")


if __name__ == "__main__":
    main()
