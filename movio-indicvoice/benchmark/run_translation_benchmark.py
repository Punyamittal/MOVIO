"""
Benchmark English → Tanglish translation across Ollama models and settings.

Measures, per model:
  translation latency (p50 / mean), tokens per second, hallucination rate,
  entity preservation, semantic (concept) preservation, retry rate.

Two suites are used deliberately:
  adversarial  the sentences from the bug report, none of which have an exact
               gold pair — this is the honest quality signal.
  heldout      sentences with no gold pair at all, so translation memory
               cannot flatter the score.

Usage:
  python -m benchmark.run_translation_benchmark
  python -m benchmark.run_translation_benchmark --models llama3.2:3b gemma3:4b
  python -m benchmark.run_translation_benchmark --settings
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import BENCHMARK_RESULTS_DIR  # noqa: E402
from normalization.tanglish_translator import (  # noqa: E402
    clear_cache,
    exact_gold,
    translate_to_tanglish,
)
from normalization.translation_validator import (  # noqa: E402
    concepts_in,
    extract_entities,
    validate_translation,
)

ADVERSARIAL = [
    "I am standing near the security gate with a red suitcase.",
    "The driver will arrive in five minutes.",
    "Please share the OTP 4821.",
    "I am waiting near the parking entrance.",
    "The driver is waiting near Guindy.",
    "I need to reach the airport before 7:30 PM.",
    "The driver has arrived.",
    "I am waiting near the security gate.",
    "The OTP is 4821.",
    "I need to reach the airport.",
    "Please wait for five minutes.",
    "I'm standing near the security gate with a red suitcase, but the driver has "
    "stopped on the opposite side of the road, so please ask him to turn around "
    "and come to the main entrance.",
]

HELDOUT = [
    "My flight lands at 9:15 PM, so please send the cab at 8 PM.",
    "There are three of us and we have four bags.",
    "The lift is not working, so I will take five more minutes.",
    "Tell the driver the gate number is 12.",
    "I left my phone charger in the car.",
    "Can you cancel the booking, please?",
    "The road near the temple is closed today.",
    "My name is Karthik and I am wearing a blue shirt.",
    "Please come to the second floor pickup point.",
    "The fare shown in the app is 340 rupees.",
]


@dataclass
class Case:
    source: str
    output: str
    ok: bool
    flags: list[str]
    engine: str
    attempts: int
    latency_ms: float
    hallucinated: bool
    entities_kept: bool
    concepts_kept: bool
    in_gold: bool


@dataclass
class ModelReport:
    model: str
    suite: str
    n: int = 0
    mean_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    tokens_per_sec: float = 0.0
    hallucination_rate: float = 0.0
    entity_preservation: float = 0.0
    concept_preservation: float = 0.0
    validation_pass_rate: float = 0.0
    retry_rate: float = 0.0
    fallback_rate: float = 0.0
    gold_hit_rate: float = 0.0
    cases: list[Case] = field(default_factory=list)


_HALLUCINATION_FLAGS = (
    "concept_added",
    "number_invented",
    "time_invented",
    "name_invented",
    "code_invented",
    "repeated_token",
    "repeated_phrase",
    "duplicate_clause",
    "meta_output",
    "multi_line_output",
    "meaning_loss",
)

_ENTITY_FLAGS = (
    "number_invented",
    "number_missing",
    "time_invented",
    "time_missing",
    "name_invented",
    "code_invented",
    "code_missing",
)


def evaluate(source: str, output: str) -> tuple[bool, bool, bool, list[str]]:
    report = validate_translation(source, output)
    flags = report.flags
    hallucinated = any(f.startswith(_HALLUCINATION_FLAGS) for f in flags)

    src_ent = extract_entities(source, is_source=True)
    entities_kept = not any(f.startswith(_ENTITY_FLAGS) for f in flags)
    if src_ent.is_empty():
        entities_kept = not any(
            f.startswith(("number_invented", "time_invented", "code_invented")) for f in flags
        )

    src_concepts = concepts_in(source)
    out_concepts = concepts_in(output)
    concepts_kept = (
        not src_concepts or len(src_concepts & out_concepts) / len(src_concepts) >= 0.5
    )
    return hallucinated, entities_kept, concepts_kept, flags


def run_suite(
    model: str,
    sentences: list[str],
    suite: str,
    *,
    temperature: float | None = None,
    fewshot_k: int | None = None,
    max_retries: int | None = None,
) -> ModelReport:
    clear_cache()
    rep = ModelReport(model=model, suite=suite, n=len(sentences))
    latencies: list[float] = []
    total_words = 0
    total_sec = 0.0

    print(f"[{model}] {suite}: {len(sentences)} sentence(s)", flush=True)
    for i, s in enumerate(sentences, 1):
        t0 = time.perf_counter()
        res = translate_to_tanglish(
            s,
            model=model,
            temperature=temperature,
            fewshot_k=fewshot_k,
            max_retries=max_retries,
            use_cache=False,
        )
        elapsed = (time.perf_counter() - t0) * 1000
        hallucinated, ent_ok, con_ok, flags = evaluate(s, res.text)
        print(
            f"  [{i}/{len(sentences)}] {elapsed:7.0f}ms "
            f"{'PASS' if res.ok else 'FAIL'} ({res.engine})",
            flush=True,
        )
        latencies.append(elapsed)
        total_words += len(res.text.split())
        total_sec += elapsed / 1000.0
        rep.cases.append(
            Case(
                source=s,
                output=res.text,
                ok=res.ok,
                flags=flags,
                engine=res.engine,
                attempts=res.attempts,
                latency_ms=round(elapsed, 1),
                hallucinated=hallucinated,
                entities_kept=ent_ok,
                concepts_kept=con_ok,
                in_gold=exact_gold(s) is not None,
            )
        )

    n = max(1, len(rep.cases))
    rep.mean_latency_ms = round(statistics.fmean(latencies), 1)
    rep.p50_latency_ms = round(statistics.median(latencies), 1)
    rep.p95_latency_ms = round(sorted(latencies)[max(0, int(0.95 * len(latencies)) - 1)], 1)
    # Words/sec is the practical proxy — Ollama token counts vary by tokenizer.
    rep.tokens_per_sec = round(total_words / total_sec, 2) if total_sec else 0.0
    rep.hallucination_rate = round(sum(c.hallucinated for c in rep.cases) / n, 3)
    rep.entity_preservation = round(sum(c.entities_kept for c in rep.cases) / n, 3)
    rep.concept_preservation = round(sum(c.concepts_kept for c in rep.cases) / n, 3)
    rep.validation_pass_rate = round(sum(c.ok for c in rep.cases) / n, 3)
    rep.retry_rate = round(sum(c.attempts > 1 for c in rep.cases) / n, 3)
    rep.fallback_rate = round(
        sum(c.engine.startswith("fallback") for c in rep.cases) / n, 3
    )
    rep.gold_hit_rate = round(sum(c.in_gold for c in rep.cases) / n, 3)
    return rep


def print_report(rep: ModelReport, verbose: bool) -> None:
    print(f"\n--- {rep.model}  [{rep.suite}]  n={rep.n} ---")
    print(f"  latency mean/p50/p95 : {rep.mean_latency_ms} / {rep.p50_latency_ms} / {rep.p95_latency_ms} ms")
    print(f"  words per second     : {rep.tokens_per_sec}")
    print(f"  hallucination rate   : {rep.hallucination_rate:.1%}")
    print(f"  entity preservation  : {rep.entity_preservation:.1%}")
    print(f"  concept preservation : {rep.concept_preservation:.1%}")
    print(f"  validation pass      : {rep.validation_pass_rate:.1%}")
    print(f"  retry rate           : {rep.retry_rate:.1%}")
    print(f"  fallback rate        : {rep.fallback_rate:.1%}")
    print(f"  exact gold available : {rep.gold_hit_rate:.1%}")
    if verbose:
        for c in rep.cases:
            mark = "ok  " if c.ok else "FAIL"
            print(f"    [{mark}] {c.source}")
            print(f"           -> {c.output}")
            if c.flags:
                print(f"           flags: {','.join(c.flags)}")


def _save(out_path: Path, reports: list[ModelReport], settings: list[dict]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {"models": [asdict(r) for r in reports], "settings_sweep": settings},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", nargs="*", default=["llama3.2:3b", "gemma3:4b"])
    ap.add_argument("--suite", choices=["adversarial", "heldout", "both"], default="both")
    ap.add_argument("--settings", action="store_true", help="sweep temperature / few-shot k")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--out", default=str(BENCHMARK_RESULTS_DIR / "translation_benchmark.json"))
    args = ap.parse_args()

    suites: list[tuple[str, list[str]]] = []
    if args.suite in ("adversarial", "both"):
        suites.append(("adversarial", ADVERSARIAL))
    if args.suite in ("heldout", "both"):
        suites.append(("heldout", HELDOUT))

    out_path = Path(args.out)
    reports: list[ModelReport] = []
    settings_reports: list[dict] = []

    # Saved after every suite: a long sweep that gets interrupted still leaves
    # usable numbers behind.
    for model in args.models:
        for name, sentences in suites:
            rep = run_suite(model, sentences, name)
            reports.append(rep)
            print_report(rep, args.verbose)
            _save(out_path, reports, settings_reports)

    if args.settings:
        print("\n=== generation settings sweep (heldout) ===", flush=True)
        for model in args.models:
            for temp in (0.0, 0.3, 0.8):
                for k in (0, 4):
                    rep = run_suite(
                        model, HELDOUT, f"temp={temp} k={k}", temperature=temp, fewshot_k=k
                    )
                    settings_reports.append(
                        {
                            "model": model,
                            "temperature": temp,
                            "fewshot_k": k,
                            "hallucination_rate": rep.hallucination_rate,
                            "entity_preservation": rep.entity_preservation,
                            "validation_pass_rate": rep.validation_pass_rate,
                            "p50_latency_ms": rep.p50_latency_ms,
                        }
                    )
                    print(
                        f"  {model:<16} temp={temp:<4} k={k}  "
                        f"pass={rep.validation_pass_rate:.0%}  "
                        f"halluc={rep.hallucination_rate:.0%}  "
                        f"entity={rep.entity_preservation:.0%}  "
                        f"p50={rep.p50_latency_ms:.0f}ms",
                        flush=True,
                    )
                    _save(out_path, reports, settings_reports)

    _save(out_path, reports, settings_reports)
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
