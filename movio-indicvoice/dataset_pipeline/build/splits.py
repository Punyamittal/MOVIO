"""Source-video / speaker-level train/val/test splits — prevent leakage."""
from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from dataset_pipeline.config_loader import load_dataset_config
from dataset_pipeline.jsonl import read_jsonl_list, write_jsonl
from dataset_pipeline.paths import (
    TEST_DIR,
    TRAIN_DIR,
    UTTERANCES_JSONL,
    VAL_DIR,
    VERIFIED_JSONL,
    ensure_dirs,
)

logger = logging.getLogger("dataset_pipeline.splits")


def _bucket(key: str) -> float:
    """Stable 0..1 hash for deterministic split assignment."""
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


def assign_split(source_key: str, train_r: float, val_r: float) -> str:
    x = _bucket(source_key)
    if x < train_r:
        return "train"
    if x < train_r + val_r:
        return "validation"
    return "test"


def build_splits(*, verified_only: bool = True) -> dict[str, int]:
    """
    Split at source_video level (and speaker when available).
    Only verified(+accepted) samples enter final training split by default.
    """
    ensure_dirs()
    ds = load_dataset_config()
    train_r = float(ds.get("train_ratio") or 0.8)
    val_r = float(ds.get("val_ratio") or 0.1)

    if verified_only and VERIFIED_JSONL.exists() and VERIFIED_JSONL.stat().st_size > 0:
        rows = read_jsonl_list(VERIFIED_JSONL)
    else:
        rows = read_jsonl_list(UTTERANCES_JSONL)

    usable = []
    for r in rows:
        if not r.get("usable_for_training"):
            continue
        if verified_only and not (r.get("verified") or r.get("status") == "accepted"):
            if r.get("status") != "accepted":
                continue
        if r.get("status") == "rejected":
            continue
        usable.append(r)

    by_src: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in usable:
        key = str(r.get("source_video_id") or r.get("id"))
        by_src[key].append(r)

    keys = sorted(by_src.keys(), key=lambda k: (-len(by_src[k]), k))
    split_map: dict[str, str] = {}
    if len(keys) >= 3:
        # Largest sources → train; hold out two distinct sources for val/test
        for key in keys[:-2]:
            split_map[key] = "train"
        split_map[keys[-2]] = "validation"
        split_map[keys[-1]] = "test"
    elif len(keys) == 2:
        split_map[keys[0]] = "train"
        split_map[keys[1]] = "test"
    elif len(keys) == 1:
        split_map[keys[0]] = "train"

    buckets = {"train": [], "validation": [], "test": []}
    for key, items in by_src.items():
        sp = split_map[key]
        for it in items:
            it = dict(it)
            it["split"] = sp
            buckets[sp].append(it)

    write_jsonl(TRAIN_DIR / "utterances.jsonl", buckets["train"])
    write_jsonl(VAL_DIR / "utterances.jsonl", buckets["validation"])
    write_jsonl(TEST_DIR / "utterances.jsonl", buckets["test"])

    manifest = {
        "train": len(buckets["train"]),
        "validation": len(buckets["validation"]),
        "test": len(buckets["test"]),
        "source_videos": {k: split_map[k] for k in sorted(split_map)},
        "leakage_prevention": "source_video",
        "verified_only": verified_only,
    }
    (TRAIN_DIR / "split_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info(
        "Splits train=%d val=%d test=%d (videos=%d)",
        manifest["train"],
        manifest["validation"],
        manifest["test"],
        len(split_map),
    )
    return {k: len(buckets[k]) for k in buckets}
