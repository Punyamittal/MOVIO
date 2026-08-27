"""
Scan sourcing/output/ for common Tanglish code-mix suffixes and untranslated loanwords.

Optional utility only — core pipeline does not depend on its output.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import SOURCING_OUTPUT_DIR  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sourcing.patterns")

SUFFIX_PATTERNS = {
    "-la": re.compile(r"\b\w+la\b", re.IGNORECASE),
    "-nu": re.compile(r"\b\w+nu\b", re.IGNORECASE),
    "-pannunga": re.compile(r"\b\w*pannunga\b", re.IGNORECASE),
    "-irukku": re.compile(r"\b\w*irukku\b", re.IGNORECASE),
}

# Common transport-domain English loanwords often left untranslated in Tanglish
LOANWORD_PATTERN = re.compile(
    r"\b(cab|driver|otp|pickup|drop|location|traffic|booking|payment|cancel|"
    r"airport|station|google|maps|upi|gpay|fare|toll|eta)\b",
    re.IGNORECASE,
)


def extract_patterns(input_dir: Path | None = None) -> Path:
    input_dir = input_dir or SOURCING_OUTPUT_DIR
    SOURCING_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SOURCING_OUTPUT_DIR / "extracted_patterns.json"

    if not input_dir.exists():
        logger.warning("sourcing/output missing — writing empty pattern report")
        out_path.write_text(json.dumps({"suffixes": {}, "loanwords": {}}, indent=2), encoding="utf-8")
        return out_path

    texts: list[str] = []
    for path in input_dir.glob("*.txt"):
        texts.append(path.read_text(encoding="utf-8", errors="ignore"))

    if not texts:
        logger.warning("No .txt files in %s — empty pattern report", input_dir)
        out_path.write_text(json.dumps({"suffixes": {}, "loanwords": {}}, indent=2), encoding="utf-8")
        return out_path

    blob = "\n".join(texts)
    suffix_counts: dict[str, int] = {}
    suffix_examples: dict[str, list[str]] = {}
    for name, pattern in SUFFIX_PATTERNS.items():
        matches = pattern.findall(blob)
        suffix_counts[name] = len(matches)
        suffix_examples[name] = list(dict.fromkeys(matches))[:20]

    loan_counter = Counter(m.lower() for m in LOANWORD_PATTERN.findall(blob))

    report = {
        "suffix_counts": suffix_counts,
        "suffix_examples": suffix_examples,
        "loanwords": dict(loan_counter.most_common(50)),
        "source_files": [p.name for p in input_dir.glob("*.txt")],
    }
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Wrote pattern report to %s", out_path)
    return out_path


if __name__ == "__main__":
    extract_patterns()
