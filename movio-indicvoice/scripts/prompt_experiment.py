"""Throwaway prompt/model experiment for English -> Tanglish.

Not part of the pipeline. Used to pick the prompt shape and model before
wiring the real translator.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

URL = "http://localhost:11434/api/chat"

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

SYSTEM = (
    "You are an English-to-Tanglish translator for a Chennai taxi voice call.\n"
    "Tanglish = spoken Chennai Tamil written in Latin script, keeping common "
    "English words (driver, OTP, airport, suitcase, gate, minutes) as English.\n"
    "\n"
    "Rules:\n"
    "- Translate ONLY the sentence given to you.\n"
    "- Do not add information. Do not remove information.\n"
    "- Do not invent words, events, objects, locations, numbers, OTPs, times, "
    "people, or actions.\n"
    "- Do not continue the conversation.\n"
    "- Return exactly ONE translation, as one line of plain text.\n"
    "- No explanations, no alternatives, no labels, no quotes, no English "
    "restatement.\n"
    "- Keep every name, number, OTP, location, time, quantity and direction "
    "exactly as given."
)

FEWSHOT = [
    ("I am waiting near the security gate.",
     "Naan security gate pakkathula wait pannitu irukken."),
    ("The driver has arrived.", "Driver vandhutaanga."),
    ("Please ask the driver to wait near the main entrance.",
     "Driver-a main entrance pakkathula wait panna sollunga."),
    ("I have two suitcases with me.", "En kitta rendu suitcase irukku."),
]


def build_messages(text: str, fewshot: bool) -> list[dict]:
    msgs = [{"role": "system", "content": SYSTEM}]
    if fewshot:
        for src, tgt in FEWSHOT:
            msgs.append({"role": "user", "content": src})
            msgs.append({"role": "assistant", "content": tgt})
    msgs.append({"role": "user", "content": text})
    return msgs


def run(model: str, text: str, fewshot: bool) -> tuple[str, float]:
    t0 = time.perf_counter()
    resp = requests.post(
        URL,
        json={
            "model": model,
            "messages": build_messages(text, fewshot),
            "stream": False,
            "options": {
                "temperature": 0.0,
                "top_p": 0.9,
                "top_k": 40,
                "repeat_penalty": 1.1,
                "seed": 7,
                "num_predict": 160,
                "num_ctx": 2048,
            },
        },
        timeout=120,
    )
    resp.raise_for_status()
    out = (resp.json().get("message") or {}).get("content") or ""
    return out.strip(), (time.perf_counter() - t0) * 1000


def main() -> None:
    models = sys.argv[1:] or ["llama3.2:3b", "gemma3:4b", "qwen3:4b"]
    for model in models:
        for fewshot in (False, True):
            print("=" * 100)
            print(f"MODEL={model}  FEWSHOT={fewshot}")
            print("=" * 100)
            for s in SENTENCES:
                try:
                    out, ms = run(model, s, fewshot)
                except Exception as exc:  # noqa: BLE001
                    print(f"  {s}\n    ERROR {exc}")
                    continue
                print(f"  SRC: {s}")
                print(f"  OUT: {out}")
                print(f"  {ms:.0f} ms")
                print()


if __name__ == "__main__":
    main()
