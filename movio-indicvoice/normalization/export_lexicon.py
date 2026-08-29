"""
Export pronunciation_lexicon.json to CSV (tokens + phrases).

Usage:
  python -m normalization.export_lexicon
  python -m normalization.export_lexicon --out path/to/export.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import PRONUNCIATION_LEXICON_PATH  # noqa: E402

_TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")


def validate_lexicon(data: dict) -> list[str]:
    issues: list[str] = []
    seen_tokens: set[str] = set()
    seen_phrase_ids: set[str] = set()

    for row in data.get("tokens", []):
        token = (row.get("token") or "").strip().lower()
        if not token:
            issues.append("empty token entry")
            continue
        if token in seen_tokens:
            issues.append(f"duplicate token: {token!r}")
        seen_tokens.add(token)
        if _TAMIL_RE.search(token):
            issues.append(f"Tamil script in token: {token!r}")

    for row in data.get("phrases", []):
        pid = row.get("id") or ""
        if pid in seen_phrase_ids:
            issues.append(f"duplicate phrase id: {pid!r}")
        seen_phrase_ids.add(pid)
        tanglish = row.get("tanglish") or ""
        if _TAMIL_RE.search(tanglish):
            issues.append(f"Tamil script in phrase {pid!r}: {tanglish!r}")

    return issues


def export_csv(lexicon_path: Path, out_path: Path) -> int:
    data = json.loads(lexicon_path.read_text(encoding="utf-8"))
    issues = validate_lexicon(data)
    if issues:
        for msg in issues:
            print(f"WARN: {msg}", file=sys.stderr)

    rows: list[dict[str, str]] = []

    for row in data.get("phrases", []):
        rows.append(
            {
                "kind": "phrase",
                "id": row.get("id", ""),
                "token": row.get("tanglish", ""),
                "phonetic": row.get("phonetic", ""),
                "gloss": row.get("gloss", ""),
                "category": row.get("category", ""),
                "rule_tag": row.get("rule_tag", ""),
                "note": row.get("note", ""),
            }
        )

    for row in data.get("tokens", []):
        rows.append(
            {
                "kind": "token",
                "id": "",
                "token": row.get("token", ""),
                "phonetic": row.get("phonetic", ""),
                "gloss": row.get("gloss", ""),
                "category": row.get("category", ""),
                "rule_tag": row.get("rule_tag", ""),
                "note": row.get("note", ""),
            }
        )

    fieldnames = ["kind", "id", "token", "phonetic", "gloss", "category", "rule_tag", "note"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} rows to {out_path}")
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export pronunciation lexicon to CSV")
    parser.add_argument(
        "--lexicon",
        type=Path,
        default=PRONUNCIATION_LEXICON_PATH,
        help="Source JSON lexicon",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output CSV path (default: alongside lexicon)",
    )
    args = parser.parse_args()
    out = args.out or args.lexicon.with_suffix(".csv")
    export_csv(args.lexicon, out)


if __name__ == "__main__":
    main()
