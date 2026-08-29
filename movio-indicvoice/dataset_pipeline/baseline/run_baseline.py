"""
Baseline evaluation BEFORE fine-tuning.

Runs existing translation/Tanglish/normalization on a fixed eval set covering
Tamil, Tanglish, code-switch, numbers/OTP, locations, long/short sentences.
Does not start fine-tuning.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dataset_pipeline.paths import BASELINE_DIR, ensure_dirs

logger = logging.getLogger("dataset_pipeline.baseline")

FIXED_EVAL: list[dict[str, Any]] = [
    {"id": "base_ta_01", "kind": "normal_tamil", "text": "உங்கள் டிரைவர் ஐந்து நிமிடங்களில் வந்துவிடுவார்."},
    {"id": "base_te_01", "kind": "chennai_tanglish", "text": "Unga driver 5 minutes la vandhuruvaanga."},
    {"id": "base_cs_01", "kind": "code_switch", "text": "Pickup point enga irukku?"},
    {"id": "base_cs_02", "kind": "code_switch", "text": "Please wait pannunga near main entrance."},
    {"id": "base_cs_03", "kind": "code_switch", "text": "Main entrance pakkathula nikkiren."},
    {"id": "base_otp", "kind": "otp", "text": "Your OTP is 4821 — share with driver only."},
    {"id": "base_num", "kind": "numbers", "text": "Fare estimate Guindy to Airport roughly ₹450."},
    {"id": "base_loc", "kind": "locations", "text": "Naan Velachery main road la wait pannitu irukken."},
    {"id": "base_long", "kind": "long", "text": "Book a cab for tomorrow 9 AM from Velachery to Guindy and share live location with the driver."},
    {"id": "base_short", "kind": "short", "text": "Okay saar."},
    {"id": "base_en", "kind": "indian_english", "text": "Your driver will arrive in five minutes. Please share the OTP."},
    {"id": "base_nav", "kind": "directions", "text": "Take a left after T Nagar bus terminus and stop near the signal."},
]


def run_baseline() -> Path:
    ensure_dirs()
    from normalization.deterministic_normalizer import normalize
    from normalization.language_translator import detect_language, translate
    from normalization.translation_validator import validate_translation

    results = []
    t0 = time.perf_counter()
    for item in FIXED_EVAL:
        text = item["text"]
        detected = detect_language(text)
        # Tanglish speak-as (Movio default path)
        tr = translate(text, target_lang="tanglish")
        norm = normalize(tr.text)
        val = validate_translation(text, tr.text)
        results.append(
            {
                "id": item["id"],
                "kind": item["kind"],
                "input": text,
                "detected_lang": detected,
                "translated_tanglish": tr.text,
                "normalized": norm,
                "translator_engine": tr.engine,
                "skipped": tr.skipped,
                "validation_ok": val.ok if hasattr(val, "ok") else getattr(val, "passed", True),
                "validation_flags": list(getattr(val, "flags", []) or []),
            }
        )

    # Optional TTS latency sample on one phrase (may be slow)
    tts_info: dict[str, Any] = {"ran": False}
    try:
        import asyncio
        from server.main import _run_tts

        async def _one() -> dict[str, Any]:
            t1 = time.perf_counter()
            r = await _run_tts(
                "Unga driver 5 minutes la vandhuruvaanga.",
                "neutral",
                skip_llm=True,
                chunked=False,
                target_lang="tanglish",
            )
            return {
                "ran": True,
                "latency_sec": round(time.perf_counter() - t1, 3),
                "backend": r.backend,
                "audio_bytes": len(r.audio or b""),
                "ttfa_ms": r.metrics_dict().get("ttfa_ms"),
            }

        tts_info = asyncio.run(_one())
    except Exception as exc:  # noqa: BLE001
        tts_info = {"ran": False, "error": str(exc)}

    report = {
        "baseline_model": "movio-indicvoice current (no fine-tune)",
        "note": "STT WER and MOS require audio fixtures / human scoring — see evaluation/",
        "n_items": len(results),
        "elapsed_sec": round(time.perf_counter() - t0, 3),
        "items": results,
        "tts_sample": tts_info,
        "metrics_available_now": {
            "translation_engine_distribution": _count(results, "translator_engine"),
            "detected_lang_distribution": _count(results, "detected_lang"),
            "validation_fail_count": sum(1 for r in results if not r.get("validation_ok")),
        },
        "follow_up": [
            "Run evaluation/asr_wer_cer.py once verified audio test set exists",
            "Fill evaluation/mos_scoring_template.csv for Tanglish naturalness / TTS pronunciation",
            "Do not fine-tune until verified dataset quality checks pass",
        ],
    }
    out = BASELINE_DIR / "baseline_report.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (BASELINE_DIR / "fixed_eval_set.json").write_text(
        json.dumps(FIXED_EVAL, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("Baseline written → %s", out)
    return out


def _count(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        k = str(r.get(key) or "?")
        out[k] = out.get(k, 0) + 1
    return out
