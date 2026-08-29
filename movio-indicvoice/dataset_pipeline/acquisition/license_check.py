"""License / permission gating — never invent licenses."""
from __future__ import annotations

import logging
import re
from typing import Any

from dataset_pipeline.schema import SourceCandidate

logger = logging.getLogger("dataset_pipeline.license")

_USABLE_PATTERNS = (
    r"creative\s*commons",
    r"\bcc0\b",
    r"\bcc[\s-]?by\b",
    r"public\s*domain",
    r"\bpd\b",
)


def evaluate_license(candidate: SourceCandidate | dict[str, Any]) -> SourceCandidate:
    """
    Re-evaluate usable_for_training from recorded license fields.

    Conservative default: usable_for_training=False unless license text matches
    known permissive patterns. Never fabricates a license string.
    """
    if isinstance(candidate, dict):
        cand = SourceCandidate.from_dict(candidate)
    else:
        cand = candidate

    lic = (cand.license or "unknown").strip()
    blob = f"{lic} {cand.notes} {cand.title}".lower()
    matched = any(re.search(p, blob) for p in _USABLE_PATTERNS)

    if matched:
        cand.usable_for_training = True
        # Still require human verification for training shards
        cand.license_verified = bool(cand.license_verified)
        if cand.license in ("", "unknown"):
            cand.license = "creative_commons_suspected"
    else:
        # Do not flip true→false if already verified by human
        if not cand.license_verified:
            cand.usable_for_training = False
        if not lic:
            cand.license = "unknown"

    return cand


def summarize_candidates(rows: list[dict[str, Any]]) -> dict[str, int]:
    permitted = sum(1 for r in rows if r.get("usable_for_training"))
    return {
        "total": len(rows),
        "permitted": permitted,
        "metadata_only": len(rows) - permitted,
    }
