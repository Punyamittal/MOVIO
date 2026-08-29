"""
Align stored English→Tanglish references with tanglish_gold_pairs.json.

Updates benchmark/data/taxi_driver_sentences.json:
  - sets tanglish_ref on every English sentence that has a gold pair
  - appends missing gold sentences with tanglish_ref

Also keeps benchmark/data/tanglish_gold_pairs.json in sync with normalization/.

Usage:
  python scripts/sync_stored_translations_from_gold.py
  python scripts/sync_stored_translations_from_gold.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from normalization.tanglish_translator import _normalize_key  # noqa: E402

GOLD_PATH = ROOT / "normalization" / "tanglish_gold_pairs.json"
BENCH_GOLD_PATH = ROOT / "benchmark" / "data" / "tanglish_gold_pairs.json"
TAXI_PATH = ROOT / "benchmark" / "data" / "taxi_driver_sentences.json"


def _load_gold() -> list[dict]:
    return json.loads(GOLD_PATH.read_text(encoding="utf-8"))


def _gold_map(rows: list[dict]) -> dict[str, tuple[str, dict]]:
    out: dict[str, tuple[str, dict]] = {}
    for row in rows:
        en = (row.get("english") or "").strip()
        ta = (row.get("tanglish") or "").strip()
        if en and ta:
            out[_normalize_key(en)] = (ta, row)
    return out


def sync_benchmark_gold_copy(*, dry_run: bool) -> bool:
    if GOLD_PATH.read_bytes() == BENCH_GOLD_PATH.read_bytes():
        return False
    if not dry_run:
        BENCH_GOLD_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(GOLD_PATH, BENCH_GOLD_PATH)
    return True


def sync_taxi_sentences(gold: dict[str, tuple[str, dict]], *, dry_run: bool) -> dict[str, int]:
    taxi: list[dict] = json.loads(TAXI_PATH.read_text(encoding="utf-8"))
    index: dict[str, int] = {}
    for i, row in enumerate(taxi):
        en = (row.get("text") or "").strip()
        if en:
            index[_normalize_key(en)] = i

    updated_ref = added_ref = appended = skipped = 0
    for key, (tanglish, row) in gold.items():
        category = str(row.get("category") or row.get("batch") or "natural_tanglish_gold")
        if key in index:
            entry = taxi[index[key]]
            prev = (entry.get("tanglish_ref") or "").strip()
            if prev != tanglish:
                if prev:
                    updated_ref += 1
                else:
                    added_ref += 1
                if not dry_run:
                    entry["tanglish_ref"] = tanglish
                    if entry.get("language_mix") in (None, "", "english", "mixed"):
                        entry["language_mix"] = "tanglish"
            else:
                skipped += 1
            continue

        appended += 1
        if not dry_run:
            taxi.append(
                {
                    "text": row.get("english", "").strip(),
                    "category": category,
                    "language_mix": "tanglish",
                    "stress": ["gold_pair", str(row.get("batch") or "gold")],
                    "tanglish_ref": tanglish,
                }
            )
            index[key] = len(taxi) - 1

    if not dry_run and (updated_ref or added_ref or appended):
        TAXI_PATH.write_text(json.dumps(taxi, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "updated_ref": updated_ref,
        "added_ref": added_ref,
        "appended": appended,
        "unchanged": skipped,
        "taxi_total": len(taxi),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not GOLD_PATH.exists():
        raise SystemExit(f"Gold pairs not found: {GOLD_PATH}")

    rows = _load_gold()
    gold = _gold_map(rows)
    copied = sync_benchmark_gold_copy(dry_run=args.dry_run)
    stats = sync_taxi_sentences(gold, dry_run=args.dry_run)

    print(f"gold pairs: {len(gold)}")
    if copied:
        print(f"copied {GOLD_PATH.name} -> {BENCH_GOLD_PATH.relative_to(ROOT)}")
    else:
        print("benchmark gold copy already in sync")
    print(
        "taxi: "
        f"updated_ref={stats['updated_ref']} "
        f"added_ref={stats['added_ref']} "
        f"appended={stats['appended']} "
        f"unchanged={stats['unchanged']} "
        f"total={stats['taxi_total']}"
    )
    if args.dry_run:
        print("(dry run — no files written)")


if __name__ == "__main__":
    main()
