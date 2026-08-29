"""Spot-check live studio normalize for domain batch (one per category)."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CSV_PATH = ROOT / "normalization" / "gold_batch_domain_90.csv"
BASE = "http://127.0.0.1:8001"


def main() -> None:
    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8")))
    rows.sort(key=lambda r: (r["category"], int(r["id"])))
    seen: set[str] = set()
    samples: list[dict[str, str]] = []
    for row in rows:
        cat = row["category"]
        if cat not in seen:
            seen.add(cat)
            samples.append(row)

    eng_fb = 0
    for row in samples:
        en = row["english"].strip()
        r = requests.post(
            f"{BASE}/studio/normalize",
            json={"text": en, "target_lang": "tanglish"},
            timeout=60,
        )
        r.raise_for_status()
        j = r.json()
        engine = j.get("translator_engine", "")
        norm = (j.get("normalized") or "")[:90]
        if engine == "fallback-source" or norm.strip().lower() == en.lower():
            eng_fb += 1
        print(f"[{row['category']}] {engine}: {norm}")

    print(f"\nEnglish fallback: {eng_fb}/{len(samples)} category samples")


if __name__ == "__main__":
    main()
