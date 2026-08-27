"""Measure whether num_ctx changes force an Ollama runner reload."""
from __future__ import annotations

import time

import requests


def once(label: str, **opts) -> None:
    t0 = time.perf_counter()
    body = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": "llama3.2:3b",
            "keep_alive": -1,
            "stream": False,
            "messages": [
                {"role": "user", "content": "Tanglish only: Driver waiting near gate."}
            ],
            "options": opts,
        },
        timeout=120,
    ).json()
    ms = (time.perf_counter() - t0) * 1000
    print(
        f"{label}: {ms:.0f}ms "
        f"load={body.get('load_duration', 0)/1e6:.0f}ms "
        f"prompt={body.get('prompt_eval_duration', 0)/1e6:.0f}ms "
        f"eval={body.get('eval_duration', 0)/1e6:.0f}ms"
    )
    print(" ", (body.get("message") or {}).get("content", "")[:70])


def main() -> None:
    once("ctx4096", num_predict=64, num_ctx=4096, temperature=0)
    once("ctx4096b", num_predict=64, num_ctx=4096, temperature=0)
    once("ctx2048", num_predict=64, num_ctx=2048, temperature=0)
    once("ctx2048b", num_predict=64, num_ctx=2048, temperature=0)
    once("ctx4096c", num_predict=64, num_ctx=4096, temperature=0)


if __name__ == "__main__":
    main()
