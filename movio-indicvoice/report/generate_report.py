"""
Populate report_template.md numeric tables from JSON result files → FINAL_REPORT.md.

Never fabricates narrative conclusions — leaves [FILL IN: your analysis here] intact.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    BENCHMARK_RESULTS_DIR,
    CONCURRENCY_RESULTS_DIR,
    COST_RESULTS_DIR,
    EVALUATION_RESULTS_DIR,
    OPTIMIZATION_RESULTS_DIR,
    REPORT_DIR,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("report.generate")


def _load(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _md_table(headers: list[str], rows: list[list]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join("" if v is None else str(v) for v in row) + " |")
    return "\n".join(lines)


def benchmark_table(data) -> str:
    if not data:
        return "_No benchmark/results/summary.json yet — run benchmark/run_benchmark.py._"
    rows = []
    comparison = data.get("comparison") or {}
    for backend, summary in comparison.items():
        rows.append(
            [
                backend,
                summary["ttfa_ms"]["p50"],
                summary["ttfa_ms"]["p95"],
                summary["ttfa_ms"]["p99"],
                summary["full_synthesis_ms"]["p50"],
                summary["full_synthesis_ms"]["p95"],
                summary["full_synthesis_ms"]["p99"],
                summary["rtf"]["p50"],
            ]
        )
    return _md_table(
        ["backend", "ttfa_p50", "ttfa_p95", "ttfa_p99", "full_p50", "full_p95", "full_p99", "rtf_p50"],
        rows,
    )


def quantization_table(data) -> str:
    if not data:
        return "_No optimization/results/quantization_comparison.json yet._"
    rows = []
    for name, stats in (data.get("precisions") or {}).items():
        rows.append(
            [
                name,
                stats.get("status"),
                stats.get("avg_generation_ms"),
                stats.get("avg_rtf"),
                stats.get("avg_file_size_bytes"),
            ]
        )
    note = "; ".join(data.get("notes") or []) or ""
    return _md_table(
        ["precision", "status", "avg_gen_ms", "avg_rtf", "avg_bytes"],
        rows,
    ) + (f"\n\nNotes: {note}" if note else "")


def compilation_table(data) -> str:
    if not data:
        return "_No optimization/results/compilation_comparison.json yet._"
    rows = [
        [
            data.get("before_avg_generation_ms"),
            data.get("after_avg_generation_ms"),
            data.get("warmup_ms"),
            data.get("steady_state_speedup"),
            data.get("compiled"),
        ]
    ]
    table = _md_table(
        ["before_ms", "after_ms", "warmup_ms", "speedup", "compiled"],
        rows,
    )
    if data.get("note"):
        table += f"\n\nNote: {data['note']}"
    return table


def concurrency_table(data) -> str:
    if not data:
        return "_No concurrency/results/latency_vs_concurrency.json yet._"
    rows = []
    for r in data.get("levels") or []:
        rows.append(
            [
                r.get("concurrency_level"),
                r.get("ttfa_p50"),
                r.get("ttfa_p95"),
                r.get("ttfa_p99"),
                r.get("full_latency_p50"),
                r.get("full_latency_p95"),
                r.get("full_latency_p99"),
                r.get("success_rate"),
                r.get("avg_gpu_util"),
                r.get("avg_memory_mb"),
            ]
        )
    return _md_table(
        [
            "concurrency",
            "ttfa_p50",
            "ttfa_p95",
            "ttfa_p99",
            "full_p50",
            "full_p95",
            "full_p99",
            "success",
            "gpu_util",
            "mem_mb",
        ],
        rows,
    )


def cost_table(data) -> str:
    if not data:
        return "_No cost_analysis/results/cost_summary.json yet._"
    rows = []
    for r in data.get("rows") or []:
        rows.append(
            [
                r.get("concurrency_level"),
                r.get("audio_minutes_generated_per_hour"),
                r.get("cost_per_generated_minute"),
                r.get("success_rate"),
                r.get("throughput_rps"),
            ]
        )
    return _md_table(
        ["concurrency", "audio_min/hour", "cost/min", "success", "rps"],
        rows,
    )


def wer_table(data) -> str:
    if not data:
        return "_No evaluation/results/wer_cer_scores.json yet._"
    agg = data.get("aggregate") or {}
    rows = [
        [
            agg.get("asr_backend"),
            agg.get("avg_wer_vs_raw"),
            agg.get("avg_cer_vs_raw"),
            agg.get("avg_wer_vs_normalized"),
            agg.get("avg_cer_vs_normalized"),
            agg.get("n"),
        ]
    ]
    table = _md_table(
        ["asr", "wer_raw", "cer_raw", "wer_norm", "cer_norm", "n"],
        rows,
    )
    if agg.get("limitation_note"):
        table += f"\n\n{agg['limitation_note']}"
    return table


def main():
    template = (REPORT_DIR / "report_template.md").read_text(encoding="utf-8")
    bench = _load(BENCHMARK_RESULTS_DIR / "summary.json")
    quant = _load(OPTIMIZATION_RESULTS_DIR / "quantization_comparison.json")
    compile_ = _load(OPTIMIZATION_RESULTS_DIR / "compilation_comparison.json")
    conc = _load(CONCURRENCY_RESULTS_DIR / "latency_vs_concurrency.json")
    cost = _load(COST_RESULTS_DIR / "cost_summary.json")
    wer = _load(EVALUATION_RESULTS_DIR / "wer_cer_scores.json")
    acceptance = _load(EVALUATION_RESULTS_DIR / "acceptance_results.json")

    replacements = {
        "<!-- AUTO:BENCHMARK_TABLE -->": benchmark_table(bench),
        "<!-- AUTO:QUANTIZATION_TABLE -->": quantization_table(quant),
        "<!-- AUTO:COMPILATION_TABLE -->": compilation_table(compile_),
        "<!-- AUTO:CONCURRENCY_TABLE -->": concurrency_table(conc),
        "<!-- AUTO:CONCURRENCY_CEILING -->": (
            (conc or {}).get("ceiling", {}).get("note")
            if conc
            else "_Run concurrency/load_test.py first._"
        ),
        "<!-- AUTO:COST_TABLE -->": cost_table(cost),
        "<!-- AUTO:COST_PER_HOUR -->": str(
            (cost or {}).get("hardware_cost_per_hour", "_unknown_")
        ),
        "<!-- AUTO:WER_CER_TABLE -->": wer_table(wer),
        "<!-- AUTO:ACCEPTANCE_SUMMARY -->": (
            (acceptance or {}).get("summary")
            if acceptance
            else "_Run evaluation/movio_acceptance.py first._"
        ),
    }
    out = template
    for k, v in replacements.items():
        out = out.replace(k, v)

    dest = REPORT_DIR / "FINAL_REPORT.md"
    dest.write_text(out, encoding="utf-8")
    logger.info("Wrote %s (narrative [FILL IN] sections left untouched)", dest)


if __name__ == "__main__":
    main()
