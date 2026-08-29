"""Audio conversion + energy VAD segmentation (16 kHz mono WAV)."""
from __future__ import annotations

import hashlib
import logging
import wave
from pathlib import Path

import numpy as np

from dataset_pipeline.config_loader import load_dataset_config

logger = logging.getLogger("dataset_pipeline.audio")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_mono_pcm16(path: Path, target_sr: int = 16000) -> tuple[np.ndarray, int]:
    """Load audio as float32 mono; resample to target_sr if needed."""
    suffix = path.suffix.lower()
    if suffix == ".wav":
        with wave.open(str(path), "rb") as wf:
            sr = wf.getframerate()
            ch = wf.getnchannels()
            sw = wf.getsampwidth()
            raw = wf.readframes(wf.getnframes())
        if sw != 2:
            raise ValueError(f"Only 16-bit PCM WAV supported for simple load: {path}")
        arr = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
        if ch > 1:
            arr = arr.reshape(-1, ch).mean(axis=1)
        arr = arr / 32768.0
    else:
        # Prefer soundfile / librosa if available
        try:
            import soundfile as sf

            arr, sr = sf.read(str(path), always_2d=False)
            arr = np.asarray(arr, dtype=np.float32)
            if arr.ndim > 1:
                arr = arr.mean(axis=1)
            sr = int(sr)
        except Exception:
            try:
                import librosa

                arr, sr = librosa.load(str(path), sr=None, mono=True)
                arr = np.asarray(arr, dtype=np.float32)
                sr = int(sr)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"Cannot decode {path}: {exc}") from exc

    if sr != target_sr:
        # Linear resample (lightweight; good enough for dataset prep)
        duration = len(arr) / float(sr)
        new_len = int(duration * target_sr)
        if new_len <= 0:
            return np.zeros(0, dtype=np.float32), target_sr
        x_old = np.linspace(0, 1, num=len(arr), endpoint=False)
        x_new = np.linspace(0, 1, num=new_len, endpoint=False)
        arr = np.interp(x_new, x_old, arr).astype(np.float32)
        sr = target_sr
    return arr, sr


def write_wav_pcm16(path: Path, audio: np.ndarray, sample_rate: int = 16000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(audio, -1.0, 1.0)
    pcm = (clipped * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())


def convert_to_wav_mono(src: Path, dest: Path, sample_rate: int | None = None) -> Path:
    ds = load_dataset_config()
    sr = sample_rate or int(ds.get("target_sample_rate") or 16000)
    audio, out_sr = load_mono_pcm16(src, target_sr=sr)
    write_wav_pcm16(dest, audio, sample_rate=out_sr)
    return dest


def rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio))))


def segment_speech(
    audio: np.ndarray,
    sample_rate: int = 16000,
    *,
    frame_ms: int = 30,
    energy_thresh: float = 0.015,
    min_speech_sec: float | None = None,
    max_speech_sec: float | None = None,
    pad_ms: int = 200,
) -> list[tuple[float, float]]:
    """
    Energy VAD → list of (start_sec, end_sec).

    Drops music-like long low-variance? Simple energy gate only — flags later.
    Avoids ultra-short fragments unless above min_speech_sec.
    """
    ds = load_dataset_config()
    min_speech_sec = min_speech_sec if min_speech_sec is not None else float(ds.get("min_utterance_sec") or 1.0)
    max_speech_sec = max_speech_sec if max_speech_sec is not None else float(ds.get("max_utterance_sec") or 18.0)

    frame = max(1, int(sample_rate * frame_ms / 1000))
    if audio.size < frame:
        return []

    energies = []
    for i in range(0, len(audio) - frame + 1, frame):
        energies.append(rms(audio[i : i + frame]))
    energies_a = np.asarray(energies, dtype=np.float32)
    speech = energies_a >= energy_thresh

    segments: list[tuple[int, int]] = []
    start = None
    for i, is_sp in enumerate(speech):
        if is_sp and start is None:
            start = i
        elif not is_sp and start is not None:
            segments.append((start, i))
            start = None
    if start is not None:
        segments.append((start, len(speech)))

    pad = int(pad_ms / frame_ms)
    out: list[tuple[float, float]] = []
    for a, b in segments:
        a2 = max(0, a - pad)
        b2 = min(len(speech), b + pad)
        t0 = a2 * frame / sample_rate
        t1 = b2 * frame / sample_rate
        dur = t1 - t0
        if dur < min_speech_sec:
            continue
        # Split overly long
        if dur > max_speech_sec:
            cur = t0
            while cur < t1:
                nxt = min(cur + max_speech_sec, t1)
                if nxt - cur >= min_speech_sec:
                    out.append((round(cur, 3), round(nxt, 3)))
                cur = nxt
        else:
            out.append((round(t0, 3), round(t1, 3)))
    return out


def slice_audio(audio: np.ndarray, sample_rate: int, start: float, end: float) -> np.ndarray:
    a = int(start * sample_rate)
    b = int(end * sample_rate)
    return audio[max(0, a) : min(len(audio), b)]
