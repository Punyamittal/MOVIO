"""
Optional Hugging Face dataset loader for Tanglish reference sentences.

HARD RULE: This module must NEVER block the core pipeline.
Downstream must NOT depend on sourcing/output existing.

Loads community-datasets/tamilmixsentiment (~15,744 Tamil-English code-switched
sentences), samples 500–1000 rows, saves as text.

No Reddit — API access effectively closed to new developers as of 2026
(manual approval, most apps denied, .json endpoints shut down May 2026).
Do not build any Reddit integration.
"""
from __future__ import annotations

import logging
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import SOURCING_OUTPUT_DIR  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sourcing.hf")

DATASET_ID = "community-datasets/tamilmixsentiment"
SAMPLE_MIN = 500
SAMPLE_MAX = 1000


def load_and_sample(sample_size: int | None = None, seed: int = 42) -> Path:
    """Sample Tanglish sentences and write to sourcing/output. Soft-fails on errors."""
    SOURCING_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SOURCING_OUTPUT_DIR / "hf_tamilmixsentiment.txt"

    if sample_size is None:
        sample_size = random.randint(SAMPLE_MIN, SAMPLE_MAX)
    sample_size = max(SAMPLE_MIN, min(SAMPLE_MAX, sample_size))

    try:
        from datasets import load_dataset
    except ImportError:
        logger.warning(
            "datasets library not installed; skipping HF load. "
            "Core pipeline continues with benchmark/data/."
        )
        return out_path

    try:
        ds = load_dataset(DATASET_ID, split="train")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to load %s: %s — skipping", DATASET_ID, exc)
        return out_path

    # Prefer common text column names
    text_col = None
    for candidate in ("text", "sentence", "content", "review"):
        if candidate in ds.column_names:
            text_col = candidate
            break
    if text_col is None:
        text_col = ds.column_names[0]
        logger.warning("Using first column as text: %s", text_col)

    n = min(sample_size, len(ds))
    rng = random.Random(seed)
    indices = rng.sample(range(len(ds)), n)
    lines = []
    for idx in indices:
        row = ds[idx]
        val = row[text_col]
        if val is None:
            continue
        lines.append(str(val).strip())

    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote %d sentences to %s", len(lines), out_path)
    return out_path


if __name__ == "__main__":
    load_and_sample()
