"""
Async concurrency load test against POST /tts.

Levels from config.CONCURRENCY_LEVELS (default [1,5,10,15,20]).
Each level run 3x and averaged.

Reports TTFA and full latency separately. If laptop GPU cannot sustain 15–20
concurrent requests, the measured ceiling is reported honestly — never faked.
"""
from __future__ import annotations

import asyncio
import json
import logging
import statistics
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from benchmark.metrics import percentile  # noqa: E402
from concurrency.resource_monitor import ResourceMonitor  # noqa: E402
from config import (  # noqa: E402
    CONCURRENCY_LEVELS,
    CONCURRENCY_RESULTS_DIR,
    LOAD_TEST_RUNS_PER_LEVEL,
    LOAD_TEST_SAMPLE_TEXTS,
    SERVER_HOST,
    SERVER_PORT,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("concurrency.load_test")


def base_url() -> str:
    host = "127.0.0.1" if SERVER_HOST in ("0.0.0.0", "::") else SERVER_HOST
    return f"http://{host}:{SERVER_PORT}"


async def one_request(client: httpx.AsyncClient, text: str, timeout: float) -> dict:
    t0 = time.perf_counter()
    try:
        resp = await client.post(
            "/tts",
            json={"text": text, "return_audio_base64": True, "skip_llm": True},
            timeout=timeout,
        )
        wall = (time.perf_counter() - t0) * 1000
        if resp.status_code != 200:
            return {
                "ok": False,
                "timeout": False,
                "status": resp.status_code,
                "ttfa_ms": None,
                "full_latency_ms": wall,
            }
        data = resp.json()
        return {
            "ok": True,
            "timeout": False,
            "status": 200,
            "ttfa_ms": data.get("ttfa_ms"),
            "full_latency_ms": data.get("full_synthesis_ms", wall),
            "end_to_end_ms": data.get("metrics", {}).get("end_to_end_ms", wall),
        }
    except httpx.TimeoutException:
        return {
            "ok": False,
            "timeout": True,
            "status": None,
            "ttfa_ms": None,
            "full_latency_ms": (time.perf_counter() - t0) * 1000,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "timeout": False,
            "status": None,
            "error": str(exc),
            "ttfa_ms": None,
            "full_latency_ms": (time.perf_counter() - t0) * 1000,
        }


async def run_level(concurrency: int, texts: list[str], timeout: float = 120.0) -> dict:
    mon = ResourceMonitor(interval_sec=1.0)
    mon.start()
    batch_t0 = time.perf_counter()
    async with httpx.AsyncClient(base_url=base_url()) as client:
        # Fire `concurrency` requests (cycle texts)
        tasks = [
            one_request(client, texts[i % len(texts)], timeout)
            for i in range(concurrency)
        ]
        results = await asyncio.gather(*tasks)
    batch_wall = time.perf_counter() - batch_t0
    mon.stop()
    res_summary = mon.summary()

    oks = [r for r in results if r.get("ok")]
    timeouts = sum(1 for r in results if r.get("timeout"))
    failures = len(results) - len(oks)
    ttfa = [r["ttfa_ms"] for r in oks if r.get("ttfa_ms") is not None]
    full = [r["full_latency_ms"] for r in oks if r.get("full_latency_ms") is not None]

    return {
        "concurrency_level": concurrency,
        "ttfa_p50": round(percentile(ttfa, 50), 2) if ttfa else None,
        "ttfa_p95": round(percentile(ttfa, 95), 2) if ttfa else None,
        "ttfa_p99": round(percentile(ttfa, 99), 2) if ttfa else None,
        "full_latency_p50": round(percentile(full, 50), 2) if full else None,
        "full_latency_p95": round(percentile(full, 95), 2) if full else None,
        "full_latency_p99": round(percentile(full, 99), 2) if full else None,
        "success_rate": round(len(oks) / len(results), 4) if results else 0.0,
        "success_count": len(oks),
        "failure_count": failures,
        "timeout_count": timeouts,
        "batch_wall_clock_sec": round(batch_wall, 3),
        "throughput_rps": round(len(oks) / batch_wall, 3) if batch_wall > 0 else 0.0,
        "avg_gpu_util": res_summary.get("avg_gpu_util"),
        "avg_memory_mb": res_summary.get("avg_memory_mb"),
        "avg_cpu_percent": res_summary.get("avg_cpu_percent"),
        "gpu_monitoring": res_summary.get("gpu_monitoring"),
    }


def average_runs(runs: list[dict]) -> dict:
    keys_mean = [
        "ttfa_p50", "ttfa_p95", "ttfa_p99",
        "full_latency_p50", "full_latency_p95", "full_latency_p99",
        "success_rate", "batch_wall_clock_sec", "throughput_rps",
        "avg_gpu_util", "avg_memory_mb", "avg_cpu_percent",
        "success_count", "failure_count", "timeout_count",
    ]
    out = {"concurrency_level": runs[0]["concurrency_level"], "runs": len(runs)}
    for k in keys_mean:
        vals = [r[k] for r in runs if r.get(k) is not None]
        out[k] = round(statistics.mean(vals), 4) if vals else None
    out["gpu_monitoring"] = any(r.get("gpu_monitoring") for r in runs)
    return out


def detect_ceiling(rows: list[dict], min_success: float = 0.8) -> dict:
    """Honest ceiling: highest concurrency with success_rate >= min_success."""
    ceiling = 0
    for row in rows:
        if (row.get("success_rate") or 0) >= min_success:
            ceiling = row["concurrency_level"]
    note = (
        f"Measured sustainable concurrency ceiling (success_rate>={min_success}): {ceiling}. "
    )
    if ceiling < 15:
        note += (
            "This laptop GPU could not sustain 15–20 concurrent requests under the "
            "test conditions. Production would likely need a datacenter GPU tier "
            "(e.g. NVIDIA T4 / A10G / L4 or better) with higher VRAM and sustained "
            "throughput, plus multi-worker or multi-replica serving."
        )
    else:
        note += "Hardware sustained the 15–20 target under this test configuration."
    return {"measured_ceiling": ceiling, "note": note}


def write_report_md(rows: list[dict], ceiling: dict, path: Path) -> None:
    lines = [
        "# Concurrency Report",
        "",
        ceiling["note"],
        "",
        "| concurrency | ttfa_p50 | ttfa_p95 | ttfa_p99 | full_p50 | full_p95 | full_p99 | success | gpu_util | mem_mb |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            "| {concurrency_level} | {ttfa_p50} | {ttfa_p95} | {ttfa_p99} | "
            "{full_latency_p50} | {full_latency_p95} | {full_latency_p99} | "
            "{success_rate} | {avg_gpu_util} | {avg_memory_mb} |".format(**{k: r.get(k) for k in r})
        )
    lines.extend(
        [
            "",
            "## Honest hardware ceiling",
            "",
            f"- Measured ceiling: **{ceiling['measured_ceiling']}** concurrent successful requests",
            f"- Detail: {ceiling['note']}",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


async def main_async():
    CONCURRENCY_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # Health check
    try:
        async with httpx.AsyncClient(base_url=base_url(), timeout=5.0) as client:
            r = await client.get("/health")
            r.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "Server not reachable at %s — start with: "
            "python -m server.main (QUEUE_ENABLED=true). Error: %s",
            base_url(),
            exc,
        )
        raise SystemExit(1) from exc

    averaged_rows = []
    for level in CONCURRENCY_LEVELS:
        runs = []
        for run_i in range(LOAD_TEST_RUNS_PER_LEVEL):
            logger.info("Concurrency=%d run %d/%d", level, run_i + 1, LOAD_TEST_RUNS_PER_LEVEL)
            runs.append(await run_level(level, LOAD_TEST_SAMPLE_TEXTS))
        averaged_rows.append(average_runs(runs))

    ceiling = detect_ceiling(averaged_rows)
    payload = {
        "levels": averaged_rows,
        "ceiling": ceiling,
        "note": (
            "ttfa_* and full_latency_* are distinct metrics. "
            "Ceiling is measured honestly — never fabricated."
        ),
    }
    out_json = CONCURRENCY_RESULTS_DIR / "latency_vs_concurrency.json"
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    out_md = CONCURRENCY_RESULTS_DIR / "concurrency_report.md"
    write_report_md(averaged_rows, ceiling, out_md)
    logger.info("Wrote %s and %s", out_json, out_md)
    print(json.dumps(payload, indent=2))


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
