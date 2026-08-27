"""
Latency metric helpers.

TTFA and full-synthesis latency are ALWAYS reported as distinct figures —
never collapsed into a single "latency" number.
"""
from __future__ import annotations

import math
from typing import Iterable


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return xs[int(k)]
    return xs[f] * (c - k) + xs[c] * (k - f)


def summarize_latencies(ttfa_ms: list[float], full_ms: list[float], rtf: list[float]) -> dict:
    def block(vals: list[float]) -> dict:
        return {
            "p50": round(percentile(vals, 50), 2),
            "p95": round(percentile(vals, 95), 2),
            "p99": round(percentile(vals, 99), 2),
            "mean": round(sum(vals) / len(vals), 2) if vals else 0.0,
            "n": len(vals),
        }

    return {
        "ttfa_ms": block(ttfa_ms),
        "full_synthesis_ms": block(full_ms),
        "rtf": block(rtf),
    }


def print_comparison_table(by_backend: dict[str, dict]) -> None:
    headers = (
        "backend",
        "ttfa_p50",
        "ttfa_p95",
        "ttfa_p99",
        "full_p50",
        "full_p95",
        "full_p99",
        "rtf_p50",
    )
    print(" | ".join(headers))
    print("-+-".join("-" * len(h) for h in headers))
    for backend, summary in by_backend.items():
        row = [
            backend,
            str(summary["ttfa_ms"]["p50"]),
            str(summary["ttfa_ms"]["p95"]),
            str(summary["ttfa_ms"]["p99"]),
            str(summary["full_synthesis_ms"]["p50"]),
            str(summary["full_synthesis_ms"]["p95"]),
            str(summary["full_synthesis_ms"]["p99"]),
            str(summary["rtf"]["p50"]),
        ]
        print(" | ".join(row))
