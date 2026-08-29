"""
YouTube discovery via yt-dlp (optional). Prefer Creative Commons results.

Does not mass-download. Writes candidate metadata JSONL only.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from dataset_pipeline.config_loader import all_discovery_queries, load_dataset_config, load_languages_config, load_sources_config
from dataset_pipeline.io_util import bump_count, load_seen_video_ids, mark_video_seen, save_progress
from dataset_pipeline.jsonl import append_jsonl, read_jsonl_list
from dataset_pipeline.paths import CANDIDATES_DIR, ensure_dirs
from dataset_pipeline.schema import SourceCandidate

logger = logging.getLogger("dataset_pipeline.discover")

CANDIDATES_JSONL = CANDIDATES_DIR / "candidates.jsonl"

_DOMAIN_HINTS = {
    "taxi": "transport",
    "cab": "transport",
    "ride": "transport",
    "airport": "travel",
    "railway": "travel",
    "hotel": "travel",
    "food": "food",
    "delivery": "food",
    "payment": "payments",
    "otp": "payments",
    "traffic": "directions",
    "navigation": "directions",
    "customer": "customer_service",
    "support": "customer_service",
    "tanglish": "code_switching",
    "tamil english": "code_switching",
}


def _guess_domain(query: str, title: str) -> str:
    blob = f"{query} {title}".lower()
    for k, dom in _DOMAIN_HINTS.items():
        if k in blob:
            return dom
    if "interview" in blob or "vlog" in blob or "conversation" in blob:
        return "general_conversation"
    return "general_conversation"


def _guess_language(query: str, title: str) -> str:
    blob = f"{query} {title}".lower()
    if "tanglish" in blob or "tamil english" in blob or "tamil-english" in blob:
        return "ta-en"
    if "tamil" in blob:
        return "ta"
    if "english" in blob:
        return "en"
    return "unknown"


def _yt_dlp_available() -> bool:
    return shutil.which("yt-dlp") is not None or shutil.which("yt_dlp") is not None


def _run_yt_dlp_search(query: str, max_results: int) -> list[dict[str, Any]]:
    """Flat search; returns list of info dicts. Empty if yt-dlp missing/fails."""
    if not _yt_dlp_available():
        logger.warning("yt-dlp not on PATH — discovery will write query stubs only")
        return []
    search = f"ytsearch{max_results}:{query}"
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        "--no-download",
        "--ignore-errors",
        "--quiet",
        search,
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("yt-dlp search failed for %r: %s", query, exc)
        return []
    rows: list[dict[str, Any]] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _license_from_info(info: dict[str, Any]) -> tuple[str, bool, bool]:
    """
    Return (license_str, license_verified, usable_for_training).

    Conservative: only Creative Commons / public domain / explicit free licenses
    get usable_for_training=True. Everything else is metadata-only.
    """
    lic = (
        str(info.get("license") or info.get("licence") or "")
        or str((info.get("webpage_url") or ""))
    ).strip()
    # Some flat results omit license — check title/description heuristics only for CC search
    blob = " ".join(
        str(info.get(k) or "")
        for k in ("license", "licence", "description", "title", "categories")
    ).lower()
    cc = bool(
        re.search(r"creative\s*commons|cc[\s-]?by|cc0|public\s*domain", blob)
        or (lic and "creative" in lic.lower())
    )
    if cc:
        label = lic or "creative_commons_suspected"
        return label, False, True  # verified=false until human confirms
    if lic:
        return lic, False, False
    return "unknown", False, False


def discover(
    *,
    prefer_cc: bool | None = None,
    max_per_query: int | None = None,
    limit_queries: int | None = None,
) -> Path:
    """
    Discover YouTube candidates. Resumable via seen_video_ids.

    Writes dataset_pipeline/output/raw/candidates/candidates.jsonl
    """
    ensure_dirs()
    ds = load_dataset_config()
    src = load_sources_config()
    lang_cfg = load_languages_config()
    yt_cfg = src.get("youtube") or {}
    prefer_cc = prefer_cc if prefer_cc is not None else bool(yt_cfg.get("prefer_creative_commons", True))
    max_per_query = max_per_query or int(
        yt_cfg.get("max_results_per_query") or ds.get("max_discover_per_query") or 8
    )
    sleep_s = float(yt_cfg.get("sleep_between_queries_sec") or 1.5)
    cc_suffix = str(lang_cfg.get("creative_commons_suffix") or "creative commons")

    queries = all_discovery_queries(lang_cfg)
    if limit_queries:
        queries = queries[:limit_queries]

    seen = load_seen_video_ids()
    existing = {r.get("video_id") for r in read_jsonl_list(CANDIDATES_JSONL)}
    seen |= {x for x in existing if x}

    new_rows: list[dict[str, Any]] = []
    save_progress(stage="discover")

    for i, (bucket, query) in enumerate(queries):
        q = f"{query} {cc_suffix}".strip() if prefer_cc else query
        logger.info("[%d/%d] discover %s :: %s", i + 1, len(queries), bucket, q)
        infos = _run_yt_dlp_search(q, max_per_query)
        if not infos:
            # Stub candidate so the query is recorded for reproducibility
            stub = SourceCandidate(
                source="youtube",
                video_id=f"STUB_{abs(hash(q)) % 10_000_000:07d}",
                title=f"[undiscovered] {query}",
                url="",
                license="unknown",
                license_verified=False,
                usable_for_training=False,
                discovery_query=q,
                language_guess=_guess_language(query, ""),
                domain=_guess_domain(query, ""),
                notes="No yt-dlp results (missing tool, blocked, or empty). Metadata placeholder.",
            )
            if stub.video_id not in seen:
                new_rows.append(stub.to_dict())
                seen.add(stub.video_id)
            time.sleep(0.05)
            continue

        for info in infos:
            vid = str(info.get("id") or info.get("url") or "").strip()
            if not vid or vid in seen:
                continue
            title = str(info.get("title") or "")
            lic, verified, usable = _license_from_info(info)
            # Flat search rarely returns license — mark usable only if CC search + heuristic
            if prefer_cc and not usable:
                # Still record; collection step will treat as metadata-only
                usable = False
            cand = SourceCandidate(
                source="youtube",
                video_id=vid,
                title=title,
                channel=str(info.get("channel") or info.get("uploader") or ""),
                url=str(info.get("url") or info.get("webpage_url") or f"https://www.youtube.com/watch?v={vid}"),
                license=lic,
                license_verified=verified,
                usable_for_training=usable,
                discovery_query=q,
                duration=float(info.get("duration") or 0.0),
                language_guess=_guess_language(query, title),
                domain=_guess_domain(query, title),
                description=str(info.get("description") or "")[:500],
                view_count=int(info.get("view_count") or 0),
                notes=f"bucket={bucket}",
            )
            new_rows.append(cand.to_dict())
            seen.add(vid)
            mark_video_seen(vid)

        time.sleep(sleep_s)

    if new_rows:
        append_jsonl(CANDIDATES_JSONL, new_rows)
        bump_count("discovered", len(new_rows))
    save_progress(stage="discover_done", last_video_id=new_rows[-1]["video_id"] if new_rows else None)
    logger.info("Discover wrote %d new candidates → %s", len(new_rows), CANDIDATES_JSONL)
    return CANDIDATES_JSONL
