"""
Voice-activity and utterance-acceptance gates for two-phone mode.

Combines energy, duration, and (optional) transcript length so background
noise is rejected while short replies like "yes" / "okay" still pass.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np

from phone_test.stt import rms_energy_pcm16

# PCM16 mono @ 16 kHz
MIN_SPEECH_SEC = 0.18  # allow "yes", "no", "okay", "where?"
MAX_SPEECH_SEC = 45.0
MIN_RMS = 280.0  # absolute PCM16 RMS floor (noise gate)
MIN_PEAK = 900.0
SHORT_REPLY_RE = re.compile(
    r"^\s*(yes|no|yeah|yep|nope|ok|okay|oki|oh|ah|hmm|huh|hai|illa|sari|"
    r"where|when|what|who|why|how|thanks|thank you|bye|"
    r"ஆம்|இல்லை|சரி|ஓகே|எங்க|எங்கே)\s*[.?!]*\s*$",
    re.IGNORECASE,
)


@dataclass
class AudioGateResult:
    accepted: bool
    reason: str
    duration_sec: float
    rms: float
    peak: float


def pcm16_stats(pcm: bytes) -> tuple[float, float, float]:
    """Return (duration_sec, rms, peak) for 16-bit mono PCM @ 16 kHz."""
    if not pcm:
        return 0.0, 0.0, 0.0
    arr = np.frombuffer(pcm, dtype=np.int16)
    if arr.size == 0:
        return 0.0, 0.0, 0.0
    duration = arr.size / 16000.0
    rms = float(np.sqrt(np.mean(arr.astype(np.float32) ** 2)))
    peak = float(np.max(np.abs(arr)))
    return duration, rms, peak


def wav_payload_to_pcm16(audio: bytes, mime: str = "audio/wav") -> bytes:
    """Extract PCM16 frames from a WAV blob; pass through raw PCM."""
    mime_l = (mime or "").lower()
    if mime_l in ("audio/pcm", "audio/l16") or mime_l.endswith("pcm"):
        return audio
    if len(audio) >= 44 and audio[:4] == b"RIFF":
        # Find 'data' chunk
        i = 12
        while i + 8 <= len(audio):
            chunk_id = audio[i : i + 4]
            chunk_size = int.from_bytes(audio[i + 4 : i + 8], "little")
            if chunk_id == b"data":
                return audio[i + 8 : i + 8 + chunk_size]
            i += 8 + chunk_size
        return audio[44:]
    return audio


def gate_audio(
    audio: bytes,
    *,
    mime: str = "audio/wav",
    sample_rate: int = 16000,
) -> AudioGateResult:
    """Reject obvious noise / empty clips before ASR."""
    if sample_rate != 16000:
        # Client always downsamples to 16 kHz; reject unexpected rates.
        return AudioGateResult(False, f"unsupported_sample_rate:{sample_rate}", 0.0, 0.0, 0.0)

    pcm = wav_payload_to_pcm16(audio, mime=mime)
    duration, rms, peak = pcm16_stats(pcm)

    if duration <= 0.02:
        return AudioGateResult(False, "empty_audio", duration, rms, peak)
    if duration > MAX_SPEECH_SEC:
        return AudioGateResult(False, "too_long", duration, rms, peak)
    if duration < MIN_SPEECH_SEC:
        return AudioGateResult(False, "too_short", duration, rms, peak)
    if rms < MIN_RMS and peak < MIN_PEAK:
        return AudioGateResult(False, "below_noise_floor", duration, rms, peak)
    return AudioGateResult(True, "ok", duration, rms, peak)


def gate_transcript(text: str, *, duration_sec: float = 0.0) -> AudioGateResult:
    """
    Post-ASR acceptance. Short replies are allowed even if barely above
    MIN_SPEECH_SEC; empty / garbage transcripts are rejected.
    """
    t = (text or "").strip()
    if not t:
        return AudioGateResult(False, "empty_transcript", duration_sec, 0.0, 0.0)
    # Very short duration + non-short-reply → likely noise hallucination
    if duration_sec and duration_sec < MIN_SPEECH_SEC * 0.9 and not SHORT_REPLY_RE.match(t):
        if len(t) > 12:
            return AudioGateResult(False, "noise_hallucination", duration_sec, 0.0, 0.0)
    return AudioGateResult(True, "ok", duration_sec, 0.0, 0.0)


def energy_ok(pcm: bytes) -> bool:
    return rms_energy_pcm16(pcm) >= MIN_RMS
