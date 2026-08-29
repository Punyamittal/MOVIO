"""Resumable progress / seen-id tracking."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from dataset_pipeline.paths import PROGRESS_PATH, SEEN_VIDEO_IDS_PATH, ensure_dirs


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_progress() -> dict[str, Any]:
    ensure_dirs()
    return _read_json(
        PROGRESS_PATH,
        {
            "stage": "init",
            "updated_at": time.time(),
            "counts": {},
            "last_video_id": None,
            "last_sample_index": 0,
        },
    )


def save_progress(**updates: Any) -> dict[str, Any]:
    ensure_dirs()
    prog = load_progress()
    prog.update(updates)
    prog["updated_at"] = time.time()
    _write_json(PROGRESS_PATH, prog)
    return prog


def bump_count(key: str, n: int = 1) -> None:
    prog = load_progress()
    counts = prog.setdefault("counts", {})
    counts[key] = int(counts.get(key, 0)) + n
    save_progress(counts=counts)


def load_seen_video_ids() -> set[str]:
    ensure_dirs()
    data = _read_json(SEEN_VIDEO_IDS_PATH, {"ids": []})
    return set(data.get("ids") or [])


def mark_video_seen(video_id: str) -> None:
    ids = load_seen_video_ids()
    ids.add(video_id)
    _write_json(SEEN_VIDEO_IDS_PATH, {"ids": sorted(ids)})
