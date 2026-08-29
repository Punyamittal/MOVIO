"""Human verification CLI — corrections are never overwritten by automation."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from dataset_pipeline.jsonl import read_jsonl_list, write_jsonl
from dataset_pipeline.paths import (
    HUMAN_EDITS_JSONL,
    REVIEW_DIR,
    UTTERANCES_JSONL,
    VERIFIED_JSONL,
    ensure_dirs,
)
from dataset_pipeline.schema import UtteranceRecord

logger = logging.getLogger("dataset_pipeline.review")


def _append_edit(edit: dict[str, Any]) -> None:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    with HUMAN_EDITS_JSONL.open("a", encoding="utf-8") as f:
        f.write(json.dumps(edit, ensure_ascii=False) + "\n")


def _load_merged() -> list[dict[str, Any]]:
    """Apply human edits on top of clean utterances."""
    rows = {r["id"]: r for r in read_jsonl_list(UTTERANCES_JSONL) if r.get("id")}
    for edit in read_jsonl_list(HUMAN_EDITS_JSONL):
        uid = edit.get("id")
        if not uid or uid not in rows:
            continue
        base = rows[uid]
        if edit.get("action") == "reject":
            base["status"] = "rejected"
            base["verified"] = True
        elif edit.get("action") == "accept":
            base["status"] = "accepted"
            base["verified"] = True
        elif edit.get("action") == "edit":
            for k in ("transcript_raw", "transcript_normalized", "tanglish", "translation_en", "language", "domain"):
                if k in edit and edit[k] is not None:
                    base[k] = edit[k]
            base["human_edited"] = True
            base["verified"] = True
            base["status"] = edit.get("status") or "accepted"
        rows[uid] = base
    return list(rows.values())


def sync_verified() -> Path:
    ensure_dirs()
    merged = _load_merged()
    verified = [r for r in merged if r.get("verified") or r.get("status") == "accepted"]
    write_jsonl(VERIFIED_JSONL, verified)
    write_jsonl(UTTERANCES_JSONL, merged)  # persist status updates; human_edited preserved
    return VERIFIED_JSONL


def review_cli(limit: int = 25, status: str = "review") -> None:
    ensure_dirs()
    rows = [r for r in read_jsonl_list(UTTERANCES_JSONL) if r.get("status") == status and not r.get("verified")]
    rows = rows[:limit]
    if not rows:
        print(f"No samples with status={status} awaiting review.")
        return

    print("=" * 60)
    print("HUMAN VERIFICATION  [A]ccept  [R]eject  [E]dit  [S]kip  [Q]uit")
    print("Human corrections are saved and never overwritten by later auto runs.")
    print("=" * 60)

    for i, r in enumerate(rows, 1):
        print("\n" + "-" * 60)
        print(f"[{i}/{len(rows)}] id={r.get('id')}  lang={r.get('language')}  conf={r.get('stt_confidence')}")
        print(f"source={r.get('source')} video={r.get('source_video_id')} domain={r.get('domain')}")
        print(f"audio={r.get('audio') or '(none)'}")
        print(f"quality={r.get('quality_score')} flags={r.get('quality_flags')}")
        print(f"RAW:   {r.get('transcript_raw')}")
        print(f"NORM:  {r.get('transcript_normalized')}")
        print(f"TANGL: {r.get('tanglish')}")
        print(f"EN:    {r.get('translation_en')}")
        choice = input("Choice [A/R/E/S/Q]: ").strip().lower()
        if choice == "q":
            break
        if choice == "s" or choice == "":
            continue
        if choice == "a":
            _append_edit({"id": r["id"], "action": "accept"})
            print("Accepted.")
        elif choice == "r":
            _append_edit({"id": r["id"], "action": "reject"})
            print("Rejected.")
        elif choice == "e":
            new_raw = input("transcript_raw (blank=keep): ").strip()
            new_tang = input("tanglish (blank=keep): ").strip()
            edit: dict[str, Any] = {"id": r["id"], "action": "edit", "status": "accepted"}
            if new_raw:
                edit["transcript_raw"] = new_raw
                edit["transcript_normalized"] = new_raw
            if new_tang:
                edit["tanglish"] = new_tang
            _append_edit(edit)
            print("Edited + accepted.")
        else:
            print("Unknown — skipped.")

    sync_verified()
    print(f"Verified file updated: {VERIFIED_JSONL}")
