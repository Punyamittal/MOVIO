"""
WebSocket clause/sentence streaming for TTS.

IMPORTANT DISTINCTION:
  This is PIPELINED / CHUNKED streaming — the input text is split into
  clauses/sentences, each chunk is synthesized fully, then audio is sent over
  the WebSocket as that chunk becomes ready.

  This is NOT true token-level / autoregressive audio-token streaming.
"""
from __future__ import annotations

import base64
import logging
import re
import time
from typing import AsyncIterator, Callable, Iterator

logger = logging.getLogger("server.websocket_stream")

# Sentence ends, then clause commas before a capital / Tamil letter.
_SPLIT_RE = re.compile(
    r"(?<=[.!?؟।])\s+"
    r"|(?<=,)\s+(?=[A-Zஉஅஆஇஈஉஊஎஏஐஒஓஔக-ஹ])"
)
# Soft split for long Tanglish runs without punctuation.
_SOFT_SPLIT_RE = re.compile(
    r"\s+(?=(?:and|but|so|then|OTP|driver|cab|traffic|please|unga|naan)\b)",
    re.IGNORECASE,
)


def split_clauses(text: str, max_chars: int = 90) -> list[str]:
    """Split into short speakable chunks for faster TTFA (first chunk first)."""
    text = text.strip()
    if not text:
        return []
    parts = [p.strip() for p in _SPLIT_RE.split(text) if p and p.strip()]
    if not parts:
        parts = [text]

    out: list[str] = []
    for part in parts:
        if len(part) <= max_chars:
            out.append(part)
            continue
        soft = [p.strip() for p in _SOFT_SPLIT_RE.split(part) if p and p.strip()]
        if len(soft) == 1 and len(soft[0]) > max_chars:
            # Last resort: pack words into ~max_chars buckets
            words = soft[0].split()
            buf: list[str] = []
            n = 0
            for w in words:
                add = len(w) + (1 if buf else 0)
                if buf and n + add > max_chars:
                    out.append(" ".join(buf))
                    buf = [w]
                    n = len(w)
                else:
                    buf.append(w)
                    n += add
            if buf:
                out.append(" ".join(buf))
        else:
            for s in soft:
                if len(s) <= max_chars:
                    out.append(s)
                else:
                    out.extend(split_clauses(s, max_chars=max_chars))
    return out or [text]


def _is_wav(raw: bytes) -> bool:
    return len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WAVE"


def _is_mp3(raw: bytes) -> bool:
    if len(raw) < 3:
        return False
    if raw[:3] == b"ID3":
        return True
    return raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0


def _silence_float(sr: int, gap_ms: float):
    import numpy as np

    n = max(0, int(sr * (gap_ms / 1000.0)))
    return np.zeros(n, dtype=np.float32)


def _decode_audio(raw: bytes) -> tuple[object, int]:
    """Decode WAV (soundfile) or MP3 (pydub) to float32 mono + sample rate."""
    import io
    import numpy as np

    if _is_wav(raw):
        import soundfile as sf

        data, rate = sf.read(io.BytesIO(raw), dtype="float32")
        arr = np.asarray(data, dtype=np.float32)
        if arr.ndim > 1:
            arr = arr.mean(axis=1)
        return arr.reshape(-1), int(rate)

    if _is_mp3(raw):
        try:
            from pydub import AudioSegment

            seg = AudioSegment.from_file(io.BytesIO(raw), format="mp3")
            seg = seg.set_channels(1)
            samples = np.array(seg.get_array_of_samples(), dtype=np.float32)
            samples /= float(1 << (8 * seg.sample_width - 1))
            return samples.reshape(-1), int(seg.frame_rate)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"MP3 decode failed (install pydub): {exc}") from exc

    import soundfile as sf

    data, rate = sf.read(io.BytesIO(raw), dtype="float32")
    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim > 1:
        arr = arr.mean(axis=1)
    return arr.reshape(-1), int(rate)


def concat_wavs(parts: list[bytes], gap_ms: float = 0.0) -> bytes:
    """
    Concatenate audio blobs into one WAV.

    Inserts `gap_ms` of silence between parts to avoid clicks / abrupt joins.
    Accepts WAV or MP3 inputs; output is always WAV for consistent stitching.
    """
    if not parts:
        return b""
    if len(parts) == 1 and gap_ms <= 0 and _is_wav(parts[0]):
        return parts[0]
    try:
        import io
        import numpy as np
        import soundfile as sf

        arrays = []
        sr = None
        for i, raw in enumerate(parts):
            data, rate = _decode_audio(raw)
            if sr is None:
                sr = rate
            elif rate != sr:
                logger.warning("sample-rate mismatch %s vs %s — keeping first", rate, sr)
            arrays.append(np.asarray(data, dtype=np.float32).reshape(-1))
            if gap_ms > 0 and i < len(parts) - 1:
                arrays.append(_silence_float(int(sr or rate), gap_ms))
        merged = np.concatenate(arrays) if arrays else np.zeros(0, dtype=np.float32)
        peak = float(np.max(np.abs(merged))) if merged.size else 0.0
        if peak > 1e-6 and peak > 1.0:
            merged = merged / peak
        buf = io.BytesIO()
        sf.write(buf, merged, int(sr or 22050), format="WAV", subtype="PCM_16")
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        logger.warning("concat_wavs soundfile path failed (%s); trying wave fallback", exc)
        return _concat_wav_stdlib(parts, gap_ms=gap_ms)


def _concat_wav_stdlib(parts: list[bytes], gap_ms: float = 0.0) -> bytes:
    """Pure-stdlib WAV concat when soundfile/numpy are unavailable."""
    import io
    import struct
    import wave

    if not parts:
        return b""
    if len(parts) == 1 and gap_ms <= 0:
        return parts[0]
    try:
        frames: list[bytes] = []
        params = None
        for i, raw in enumerate(parts):
            if not _is_wav(raw):
                logger.warning("wave fallback cannot decode non-WAV part; returning first")
                return parts[0]
            with wave.open(io.BytesIO(raw), "rb") as wf:
                if params is None:
                    params = wf.getparams()
                frames.append(wf.readframes(wf.getnframes()))
                if gap_ms > 0 and i < len(parts) - 1:
                    n = int(params.framerate * (gap_ms / 1000.0))
                    frames.append(b"\x00\x00" * n * params.nchannels)
        assert params is not None
        buf = io.BytesIO()
        with wave.open(buf, "wb") as out:
            out.setparams(params)
            out.writeframes(b"".join(frames))
        return buf.getvalue()
    except Exception as exc:  # noqa: BLE001
        logger.warning("concat_wavs fallback to first part only: %s", exc)
        return parts[0]


async def stream_tts_chunks(
    text: str,
    voice_style: str,
    synthesize_fn: Callable[[str, str], object],
) -> AsyncIterator[dict]:
    """
    Yields dict messages:
      {"type": "chunk", "index": i, "text": ..., "audio_b64": ..., "ttfa_ms": ...}
      {"type": "done", "chunk_count": n, "full_synthesis_ms": ...}
    """
    chunks = split_clauses(text)
    t0 = time.perf_counter()
    first_audio_at = None
    for i, chunk in enumerate(chunks):
        result = synthesize_fn(chunk, voice_style)
        if hasattr(result, "audio"):
            audio = result.audio
            metrics = result.metrics_dict() if hasattr(result, "metrics_dict") else {}
        else:
            audio = result
            metrics = {}
        now = time.perf_counter()
        if first_audio_at is None:
            first_audio_at = now
        yield {
            "type": "chunk",
            "index": i,
            "text": chunk,
            "audio_b64": base64.b64encode(audio).decode("ascii"),
            "ttfa_ms": round((first_audio_at - t0) * 1000, 2) if i == 0 else None,
            "chunk_metrics": metrics,
        }
    yield {
        "type": "done",
        "chunk_count": len(chunks),
        "full_synthesis_ms": round((time.perf_counter() - t0) * 1000, 2),
        "ttfa_ms": round((first_audio_at - t0) * 1000, 2) if first_audio_at else None,
    }


def sync_chunk_iter(
    chunks: list[str],
    voice_style: str,
    synthesize_fn: Callable[[str, str], bytes],
) -> Iterator[tuple[int, str, bytes]]:
    for i, chunk in enumerate(chunks):
        yield i, chunk, synthesize_fn(chunk, voice_style)
