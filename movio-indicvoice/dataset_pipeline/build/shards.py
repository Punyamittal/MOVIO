"""Deterministic shard builder."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from dataset_pipeline.config_loader import load_dataset_config
from dataset_pipeline.jsonl import read_jsonl_list, write_jsonl
from dataset_pipeline.paths import AUDIO_DIR, OUTPUT_DIR, SHARDS_DIR, TRAIN_DIR, ensure_dirs

logger = logging.getLogger("dataset_pipeline.shards")


def build_shards(split: str = "train") -> Path:
    ensure_dirs()
    ds = load_dataset_config()
    shard_size = int(ds.get("shard_size") or 250)
    src = {
        "train": TRAIN_DIR / "utterances.jsonl",
        "validation": OUTPUT_DIR / "validation" / "utterances.jsonl",
        "test": OUTPUT_DIR / "test" / "utterances.jsonl",
    }[split]
    rows = read_jsonl_list(src)
    shard_root = SHARDS_DIR / split
    if shard_root.exists():
        # Do not delete blindly — write into new numbered shards only if empty pattern
        pass
    shard_root.mkdir(parents=True, exist_ok=True)

    # Clear only shard_* children for this split rebuild (not other splits)
    for child in shard_root.glob("shard_*"):
        if child.is_dir():
            shutil.rmtree(child)

    n_shards = 0
    for i in range(0, max(1, len(rows)), shard_size):
        chunk = rows[i : i + shard_size]
        name = f"shard_{n_shards:03d}"
        sdir = shard_root / name
        audio_dir = sdir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        meta_rows = []
        for r in chunk:
            r2 = dict(r)
            ap = r.get("audio") or ""
            if ap:
                src_audio = Path(ap)
                if not src_audio.is_absolute():
                    src_audio = OUTPUT_DIR / ap
                if src_audio.exists():
                    dest = audio_dir / src_audio.name
                    shutil.copy2(src_audio, dest)
                    r2["audio"] = f"audio/{src_audio.name}"
            meta_rows.append(r2)
        write_jsonl(sdir / "metadata.jsonl", meta_rows)
        stats = {
            "split": split,
            "shard": name,
            "count": len(meta_rows),
            "languages": _count(meta_rows, "language"),
            "domains": _count(meta_rows, "domain"),
            "status": _count(meta_rows, "status"),
        }
        (sdir / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
        (sdir / "verification.json").write_text(
            json.dumps(
                {
                    "all_verified": all(bool(r.get("verified")) for r in meta_rows) if meta_rows else False,
                    "human_edited": sum(1 for r in meta_rows if r.get("human_edited")),
                    "usable_for_training": sum(1 for r in meta_rows if r.get("usable_for_training")),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        n_shards += 1

    if not rows:
        # empty placeholder shard
        sdir = shard_root / "shard_000"
        sdir.mkdir(parents=True, exist_ok=True)
        (sdir / "audio").mkdir(exist_ok=True)
        write_jsonl(sdir / "metadata.jsonl", [])
        (sdir / "stats.json").write_text(json.dumps({"count": 0}), encoding="utf-8")
        (sdir / "verification.json").write_text(json.dumps({"all_verified": False}), encoding="utf-8")

    logger.info("Built %d shards for %s → %s", n_shards or 1, split, shard_root)
    return shard_root


def _count(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        k = str(r.get(key) or "unknown")
        out[k] = out.get(k, 0) + 1
    return out
