"""Merge id,category,english,tanglish CSV rows into tanglish_gold_pairs.json."""
from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from normalization.tanglish_translator import _normalize_key  # noqa: E402

_TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")
_TARGETS = (
    ROOT / "normalization" / "tanglish_gold_pairs.json",
    ROOT / "benchmark" / "data" / "tanglish_gold_pairs.json",
)


def merge_csv(csv_path: Path) -> tuple[int, int, int]:
    rows: list[dict] = []
    if _TARGETS[0].exists():
        rows = json.loads(_TARGETS[0].read_text(encoding="utf-8"))

    index: dict[str, int] = {}
    for i, row in enumerate(rows):
        en = (row.get("english") or "").strip()
        if en:
            index[_normalize_key(en)] = i

    added = updated = skipped = 0
    with csv_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for raw in reader:
            row_id = (raw.get("id") or "").strip()
            category = (raw.get("category") or "general").strip().lower()
            english = (raw.get("english") or "").strip()
            tanglish = (raw.get("tanglish") or "").strip()
            if not english or not tanglish:
                skipped += 1
                continue
            if _TAMIL_RE.search(tanglish):
                raise ValueError(f"Tamil script in row {row_id}: {tanglish!r}")

            gid = (
                f"gold_{category}_{int(row_id):02d}"
                if row_id.isdigit()
                else f"gold_{category}_{row_id}"
            )
            entry = {
                "id": gid,
                "batch": category,
                "english": english,
                "tanglish": tanglish,
                "category": f"{category}_gold",
            }
            key = _normalize_key(english)
            if key in index:
                prev = rows[index[key]]
                if (prev.get("tanglish") or "").strip() == tanglish:
                    skipped += 1
                    continue
                rows[index[key]] = entry
                updated += 1
            else:
                index[key] = len(rows)
                rows.append(entry)
                added += 1

    rows.sort(key=lambda r: (str(r.get("batch", "")), str(r.get("id", ""))))

    for path in _TARGETS:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path} ({len(rows)} total)")

    sys.path.insert(0, str(ROOT / "scripts"))
    from sync_stored_translations_from_gold import (  # noqa: E402
        sync_benchmark_gold_copy,
        sync_taxi_sentences,
    )

    gold = {
        _normalize_key(r["english"]): (r["tanglish"].strip(), r)
        for r in rows
        if (r.get("english") or "").strip() and (r.get("tanglish") or "").strip()
    }
    sync_benchmark_gold_copy(dry_run=False)
    stats = sync_taxi_sentences(gold, dry_run=False)
    print(
        f"synced taxi refs: updated={stats['updated_ref']} "
        f"added_ref={stats['added_ref']} appended={stats['appended']}"
    )

    return added, updated, skipped


def main() -> None:
    csv_path = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else ROOT / "normalization" / "gold_batch_domain_90.csv"
    )
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")
    added, updated, skipped = merge_csv(csv_path)
    print(f"added={added} updated={updated} skipped={skipped}")


if __name__ == "__main__":
    main()
