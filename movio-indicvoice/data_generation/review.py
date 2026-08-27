"""
CLI reviewer for generated Tanglish sentences.

Commands: keep / edit / delete / quit
Writes combined_benchmark_reviewed.json
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import DATA_GEN_OUTPUT_DIR  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("data_generation.review")


def load_items(path: Path) -> list[dict]:
    if not path.exists():
        # Fall back to hand-written offline benchmark so review is never blocked
        fallback = Path(__file__).resolve().parents[1] / "benchmark" / "data" / "offline_sentences.json"
        logger.warning("%s missing — loading offline benchmark %s", path, fallback)
        return json.loads(fallback.read_text(encoding="utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))


def review(input_name: str = "combined_benchmark.json") -> Path:
    in_path = DATA_GEN_OUTPUT_DIR / input_name
    items = load_items(in_path)
    kept: list[dict] = []

    print("Reviewer: [k]eep  [e]dit  [d]elete  [q]uit")
    print(f"Loaded {len(items)} items from {in_path}")

    i = 0
    while i < len(items):
        item = items[i]
        print(f"\n[{i + 1}/{len(items)}] category={item.get('category')} mix={item.get('language_mix')}")
        print(item.get("text", ""))
        cmd = input("> ").strip().lower()
        if cmd in ("q", "quit"):
            # Keep remaining as-is so partial review still saves usable data
            kept.extend(items[i:])
            break
        if cmd in ("d", "delete"):
            i += 1
            continue
        if cmd in ("e", "edit"):
            new_text = input("new text: ").strip()
            if new_text:
                item = dict(item)
                item["text"] = new_text
            kept.append(item)
            i += 1
            continue
        # default keep
        kept.append(item)
        i += 1

    DATA_GEN_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_GEN_OUTPUT_DIR / "combined_benchmark_reviewed.json"
    out.write_text(json.dumps(kept, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {len(kept)} items → {out}")
    return out


if __name__ == "__main__":
    review()
