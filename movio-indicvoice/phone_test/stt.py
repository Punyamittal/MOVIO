"""
Thin STT adapter for phone-test mode.

Reuses the same ASR stack as evaluation/asr_wer_cer.py:
  1) ai4bharat/indicwhisper (HF pipeline) when available
  2) openai-whisper fallback (already in requirements.txt)

No fake transcripts — if ASR cannot load, callers get a clear error.
"""
from __future__ import annotations

import io
import logging
import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np

from config import ASR_FALLBACK_MODEL, ASR_PRIMARY_MODEL

logger = logging.getLogger("phone_test.stt")

_lock = threading.Lock()
_kind: str | None = None
_model: Any = None
_load_error: str | None = None


def _whisper_lang(code: str | None) -> str | None:
    if not code:
        return None
    c = code.lower().strip()
    if c in ("auto", "tanglish", ""):
        return None  # let whisper detect; Tanglish ≈ English+Tamil mix
    if c in ("ta", "tamil", "ta-in"):
        return "ta"
    if c in ("en", "english", "en-in"):
        return "en"
    return None


def ensure_loaded() -> tuple[str | None, Any]:
    global _kind, _model, _load_error
    with _lock:
        if _model is not None:
            return _kind, _model
        if _load_error and _kind is None and _model is None:
            # Allow one retry after failure by clearing — keep last error visible
            pass

        try:
            import torch
            from transformers import pipeline as hf_pipeline

            device = 0 if torch.cuda.is_available() else -1
            asr = hf_pipeline(
                "automatic-speech-recognition",
                model=ASR_PRIMARY_MODEL,
                device=device,
            )
            _kind, _model = "hf", asr
            _load_error = None
            logger.info("Phone-test STT loaded primary: %s", ASR_PRIMARY_MODEL)
            return _kind, _model
        except Exception as exc:  # noqa: BLE001
            logger.warning("Primary ASR unavailable (%s) — trying whisper", exc)

        try:
            import whisper

            model_name = ASR_FALLBACK_MODEL.replace("openai/whisper-", "")
            model = whisper.load_model(model_name)
            _kind, _model = "whisper", model
            _load_error = None
            logger.info("Phone-test STT loaded whisper: %s", model_name)
            return _kind, _model
        except Exception as exc:  # noqa: BLE001
            _load_error = str(exc)
            _kind, _model = None, None
            logger.error("No ASR available for phone-test: %s", exc)
            return None, None


def status() -> dict[str, Any]:
    kind, model = ensure_loaded()
    return {
        "ready": model is not None,
        "backend": kind,
        "primary_model": ASR_PRIMARY_MODEL,
        "fallback_model": ASR_FALLBACK_MODEL,
        "error": _load_error,
    }


def _pcm16_wav_bytes(pcm: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def audio_bytes_to_wav_path(
    audio: bytes,
    *,
    mime: str = "audio/wav",
    sample_rate: int = 16000,
) -> Path:
    """Write incoming browser audio to a temp file Whisper/HF can read."""
    suffix = ".wav"
    raw = audio
    mime_l = (mime or "").lower()

    if mime_l in ("audio/pcm", "audio/l16", "application/octet-stream") or mime_l.endswith("pcm"):
        raw = _pcm16_wav_bytes(audio, sample_rate=sample_rate)
        suffix = ".wav"
    elif "webm" in mime_l:
        suffix = ".webm"
    elif "ogg" in mime_l:
        suffix = ".ogg"
    elif "mp4" in mime_l or "m4a" in mime_l:
        suffix = ".m4a"
    elif "mpeg" in mime_l or "mp3" in mime_l:
        suffix = ".mp3"
    else:
        # Assume WAV / RIFF
        if not audio[:4] == b"RIFF":
            # treat as raw pcm16le mono
            raw = _pcm16_wav_bytes(audio, sample_rate=sample_rate)
        suffix = ".wav"

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(raw)
    tmp.close()
    return Path(tmp.name)


def transcribe_file(
    path: Path,
    *,
    language_hint: str | None = None,
) -> tuple[str, float]:
    """Return (text, stt_ms). Raises RuntimeError if ASR unavailable."""
    kind, model = ensure_loaded()
    if model is None:
        raise RuntimeError(
            _load_error
            or "STT unavailable — install openai-whisper or ai4bharat/indicwhisper"
        )

    lang = _whisper_lang(language_hint)
    t0 = time.perf_counter()

    if kind == "hf":
        kwargs: dict[str, Any] = {}
        if lang:
            kwargs["generate_kwargs"] = {"language": lang, "task": "transcribe"}
        out = model(str(path), **kwargs)
        text = (out.get("text") or "").strip()
    elif kind == "whisper":
        opts: dict[str, Any] = {"task": "transcribe"}
        if lang:
            opts["language"] = lang
        # fp16 only when CUDA
        try:
            import torch

            opts["fp16"] = bool(torch.cuda.is_available())
        except Exception:  # noqa: BLE001
            opts["fp16"] = False
        result = model.transcribe(str(path), **opts)
        text = (result.get("text") or "").strip()
    else:
        raise RuntimeError(f"Unknown STT backend: {kind}")

    ms = (time.perf_counter() - t0) * 1000
    return text, ms


def transcribe_bytes(
    audio: bytes,
    *,
    mime: str = "audio/wav",
    sample_rate: int = 16000,
    language_hint: str | None = None,
) -> tuple[str, float]:
    path = audio_bytes_to_wav_path(audio, mime=mime, sample_rate=sample_rate)
    try:
        return transcribe_file(path, language_hint=language_hint)
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def rms_energy_pcm16(pcm: bytes) -> float:
    if not pcm:
        return 0.0
    arr = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if arr.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(arr * arr)))
