"""
CLI entrypoint for the fine-tuning data collection pipeline.

Usage:
  python -m dataset_pipeline discover [--limit-queries N]
  python -m dataset_pipeline collect [--limit N]
  python -m dataset_pipeline process [--limit-media N]
  python -m dataset_pipeline verify [--limit N]
  python -m dataset_pipeline build
  python -m dataset_pipeline stats
  python -m dataset_pipeline baseline
  python -m dataset_pipeline run-all [--limit-queries N]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Project root on path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Movio/IndicVoice speech dataset pipeline")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_disc = sub.add_parser("discover", help="Discover YouTube candidates (CC preferred)")
    p_disc.add_argument("--limit-queries", type=int, default=None)
    p_disc.add_argument("--no-cc", action="store_true", help="Do not append creative commons to queries")

    p_col = sub.add_parser("collect", help="Acquire permitted audio / metadata / bootstrap corpora")
    p_col.add_argument("--limit", type=int, default=None)

    p_proc = sub.add_parser("process", help="VAD → STT → lang → Tanglish → quality → dedup")
    p_proc.add_argument("--limit-media", type=int, default=None)

    p_ver = sub.add_parser("verify", help="Human review CLI")
    p_ver.add_argument("--limit", type=int, default=25)
    p_ver.add_argument("--status", default="review")
    p_ver.add_argument("--sync-only", action="store_true", help="Only merge edits → verified/")

    p_build = sub.add_parser("build", help="Entity subset + video-level splits + shards")
    p_build.add_argument("--include-unverified", action="store_true")

    sub.add_parser("stats", help="Print / write dataset statistics")
    sub.add_parser("baseline", help="Run fixed baseline eval (no fine-tune)")

    p_all = sub.add_parser("run-all", help="discover → collect → process → build → stats → baseline")
    p_all.add_argument("--limit-queries", type=int, default=6)
    p_all.add_argument("--limit-collect", type=int, default=10)
    p_all.add_argument("--skip-discover", action="store_true")

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    from dataset_pipeline.paths import ensure_dirs

    ensure_dirs()

    if args.cmd == "discover":
        from dataset_pipeline.acquisition.discover import discover

        discover(prefer_cc=not args.no_cc, limit_queries=args.limit_queries)
        return 0

    if args.cmd == "collect":
        from dataset_pipeline.acquisition.collect import collect_all

        collect_all(limit=args.limit)
        return 0

    if args.cmd == "process":
        from dataset_pipeline.processing.process import process

        process(limit_media=args.limit_media)
        return 0

    if args.cmd == "verify":
        from dataset_pipeline.review.cli import review_cli, sync_verified

        if args.sync_only:
            sync_verified()
        else:
            review_cli(limit=args.limit, status=args.status)
        return 0

    if args.cmd == "build":
        from dataset_pipeline.build.entities import build_entity_subset
        from dataset_pipeline.build.shards import build_shards
        from dataset_pipeline.build.splits import build_splits
        from dataset_pipeline.review.cli import sync_verified

        sync_verified()
        build_entity_subset()
        build_splits(verified_only=not args.include_unverified)
        for sp in ("train", "validation", "test"):
            build_shards(sp)
        return 0

    if args.cmd == "stats":
        from dataset_pipeline.stats_report import print_stats

        print_stats()
        return 0

    if args.cmd == "baseline":
        from dataset_pipeline.baseline.run_baseline import run_baseline

        path = run_baseline()
        print(f"Baseline report: {path}")
        return 0

    if args.cmd == "run-all":
        from dataset_pipeline.acquisition.collect import collect_all
        from dataset_pipeline.acquisition.discover import discover
        from dataset_pipeline.baseline.run_baseline import run_baseline
        from dataset_pipeline.build.entities import build_entity_subset
        from dataset_pipeline.build.shards import build_shards
        from dataset_pipeline.build.splits import build_splits
        from dataset_pipeline.processing.process import process
        from dataset_pipeline.review.cli import sync_verified
        from dataset_pipeline.stats_report import print_stats

        if not args.skip_discover:
            discover(prefer_cc=True, limit_queries=args.limit_queries)
        collect_all(limit=args.limit_collect)
        process(limit_media=args.limit_collect)
        sync_verified()
        build_entity_subset()
        build_splits(verified_only=False)  # provisional until human verify
        for sp in ("train", "validation", "test"):
            build_shards(sp)
        print_stats()
        run_baseline()
        return 0

    parser.error(f"unknown command {args.cmd}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
