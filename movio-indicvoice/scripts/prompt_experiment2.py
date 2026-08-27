"""Throwaway experiment: retrieval-grounded few-shot from the gold pairs."""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

URL = "http://localhost:11434/api/chat"
GOLD = json.loads(
    (ROOT / "normalization" / "tanglish_gold_pairs.json").read_text(encoding="utf-8")
)

STOP = {
    "the", "a", "an", "is", "are", "am", "to", "of", "and", "but", "so", "in",
    "on", "at", "i", "me", "my", "he", "she", "it", "that", "this", "please",
    "for", "with", "will", "has", "have", "be", "you", "your",
}


def toks(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", (s or "").lower()) if w not in STOP}


def retrieve(text: str, k: int = 4) -> list[tuple[str, str]]:
    q = toks(text)
    scored = []
    for row in GOLD:
        en, ta = row.get("english", ""), row.get("tanglish", "")
        if not en or not ta:
            continue
        g = toks(en)
        if not g:
            continue
        # Jaccard, tie-broken by shorter example (crisper demonstration)
        score = len(q & g) / len(q | g)
        scored.append((score, -len(en), en, ta))
    scored.sort(reverse=True)
    return [(en, ta) for _, _, en, ta in scored[:k]][::-1]


SYSTEM = (
    "You are an English-to-Tanglish translator for a Chennai taxi phone call.\n"
    "Tanglish = spoken Chennai Tamil written in Latin script, keeping everyday "
    "English words (driver, OTP, airport, suitcase, gate, minutes, parking) in "
    "English.\n"
    "\n"
    "Rules:\n"
    "- Translate ONLY the sentence given to you.\n"
    "- Do not add information. Do not remove information.\n"
    "- Do not invent words, events, objects, locations, numbers, OTPs, times, "
    "people, or actions.\n"
    "- Do not continue the conversation.\n"
    "- Return exactly ONE translation, as one line of plain text.\n"
    "- No explanations, no alternatives, no labels, no quotes.\n"
    "- Keep every name, number, OTP, location, time, quantity and direction "
    "exactly as given.\n"
    "- The earlier turns are style examples only. Never copy their content."
)

SENTENCES = [
    "I'm standing near the security gate with a red suitcase, but the driver has "
    "stopped on the opposite side of the road, so please ask him to turn around "
    "and come to the main entrance.",
    "I am standing near the security gate with a red suitcase.",
    "The driver will arrive in five minutes.",
    "Please share the OTP 4821.",
    "I am waiting near the parking entrance.",
    "The driver is waiting near Guindy.",
    "I need to reach the airport before 7:30 PM.",
]


def run(model: str, text: str, k: int) -> tuple[str, float]:
    msgs = [{"role": "system", "content": SYSTEM}]
    for src, tgt in retrieve(text, k):
        msgs.append({"role": "user", "content": src})
        msgs.append({"role": "assistant", "content": tgt})
    msgs.append({"role": "user", "content": text})
    t0 = time.perf_counter()
    resp = requests.post(
        URL,
        json={
            "model": model,
            "messages": msgs,
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.0,
                "top_p": 0.9,
                "top_k": 40,
                "repeat_penalty": 1.1,
                "seed": 7,
                "num_predict": 180,
                "num_ctx": 4096,
            },
        },
        timeout=180,
    )
    resp.raise_for_status()
    out = (resp.json().get("message") or {}).get("content") or ""
    return out.strip(), (time.perf_counter() - t0) * 1000


def main() -> None:
    models = sys.argv[1:] or ["llama3.2:3b", "gemma3:4b"]
    for model in models:
        print("=" * 100)
        print(f"MODEL={model}  retrieval few-shot k=4")
        print("=" * 100)
        for s in SENTENCES:
            try:
                out, ms = run(model, s, 4)
            except Exception as exc:  # noqa: BLE001
                print(f"  SRC: {s}\n  ERROR {exc}\n")
                continue
            print(f"  SRC: {s}")
            print(f"  OUT: {out}")
            print(f"  {ms:.0f} ms\n")


if __name__ == "__main__":
    main()
