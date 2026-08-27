"""
ASR-based WER/CER evaluation for synthesized audio.

Tries ai4bharat/indicwhisper first; falls back to openai/whisper (base/small).

Reports WER/CER against TWO references per sentence:
  (1) original raw input text
  (2) Tanglish-normalized text actually sent to TTS

A naive WER against raw Tanglish input will look artificially bad even for
correct speech — hence the dual reference. WER/CER is inherently noisier for
Tanglish since ASR models also struggle with code-mixed audio — known limitation,
not a hidden flaw.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    ASR_FALLBACK_MODEL,
    ASR_PRIMARY_MODEL,
    BENCHMARK_DATA_DIR,
    BENCHMARK_RESULTS_DIR,
    DATA_GEN_OUTPUT_DIR,
    DEFAULT_VOICE_STYLE,
    EVALUATION_RESULTS_DIR,
)
from server.pipeline import TTSPipeline  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluation.asr_wer_cer")


def load_items(limit: int = 25) -> list[dict]:
    for path in (
        DATA_GEN_OUTPUT_DIR / "combined_benchmark_reviewed.json",
        DATA_GEN_OUTPUT_DIR / "combined_benchmark.json",
        BENCHMARK_DATA_DIR / "offline_sentences.json",
    ):
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))[:limit]
    return []


def load_asr():
    # Try IndicWhisper-style first
    try:
        import torch
        from transformers import pipeline as hf_pipeline

        device = 0 if torch.cuda.is_available() else -1
        asr = hf_pipeline(
            "automatic-speech-recognition",
            model=ASR_PRIMARY_MODEL,
            device=device,
        )
        logger.info("Loaded ASR primary: %s", ASR_PRIMARY_MODEL)
        return ("hf", asr)
    except Exception as exc:  # noqa: BLE001
        logger.warning("IndicWhisper/primary ASR unavailable (%s) — falling back", exc)

    try:
        import whisper

        model_name = ASR_FALLBACK_MODEL.replace("openai/whisper-", "")
        model = whisper.load_model(model_name)
        logger.info("Loaded ASR fallback: whisper %s", model_name)
        return ("whisper", model)
    except Exception as exc:  # noqa: BLE001
        logger.error("No ASR available: %s", exc)
        return (None, None)


def transcribe(kind, model, wav_path: Path) -> str:
    if kind == "hf":
        out = model(str(wav_path))
        return (out.get("text") or "").strip()
    if kind == "whisper":
        result = model.transcribe(str(wav_path))
        return (result.get("text") or "").strip()
    return ""


def score_pair(hypothesis: str, reference: str) -> dict:
    from jiwer import cer, wer

    if not reference.strip():
        return {"wer": None, "cer": None}
    return {
        "wer": float(wer(reference, hypothesis)),
        "cer": float(cer(reference, hypothesis)),
    }


def main(limit: int = 25):
    EVALUATION_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    items = load_items(limit)
    kind, asr = load_asr()

    pipe = TTSPipeline(skip_llm=False)  # use full preprocess when Ollama up; soft-falls back
    # Prefer skip_llm for deterministic offline eval of normalizer path
    pipe.skip_llm = True

    audio_dir = EVALUATION_RESULTS_DIR / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for i, item in enumerate(items):
        text = item["text"]
        result = pipe.run(text, DEFAULT_VOICE_STYLE)
        wav_path = audio_dir / f"{i}.wav"
        wav_path.write_bytes(result.audio)

        hyp = ""
        if kind and asr is not None:
            hyp = transcribe(kind, asr, wav_path)
        else:
            logger.warning("Skipping ASR for index %d — no model", i)

        raw_scores = score_pair(hyp, text) if hyp else {"wer": None, "cer": None}
        norm_scores = score_pair(hyp, result.normalized_text) if hyp else {"wer": None, "cer": None}
        rows.append(
            {
                "index": i,
                "raw_text": text,
                "normalized_text": result.normalized_text,
                "hypothesis": hyp,
                "wer_vs_raw": raw_scores["wer"],
                "cer_vs_raw": raw_scores["cer"],
                "wer_vs_normalized": norm_scores["wer"],
                "cer_vs_normalized": norm_scores["cer"],
            }
        )

    def avg(key: str):
        vals = [r[key] for r in rows if r[key] is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    aggregate = {
        "n": len(rows),
        "asr_backend": kind,
        "avg_wer_vs_raw": avg("wer_vs_raw"),
        "avg_cer_vs_raw": avg("cer_vs_raw"),
        "avg_wer_vs_normalized": avg("wer_vs_normalized"),
        "avg_cer_vs_normalized": avg("cer_vs_normalized"),
        "limitation_note": (
            "WER/CER is noisier for Tanglish because ASR models also struggle with "
            "code-mixed audio. Dual references (raw vs normalized) are required for "
            "fair interpretation. This is a known limitation, not a hidden flaw."
        ),
    }
    out = {"aggregate": aggregate, "per_sentence": rows}
    path = EVALUATION_RESULTS_DIR / "wer_cer_scores.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Wrote %s", path)
    print(json.dumps(aggregate, indent=2))


if __name__ == "__main__":
    main()
