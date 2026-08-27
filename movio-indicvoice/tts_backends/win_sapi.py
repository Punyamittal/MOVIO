"""
Ultra-low-latency local TTS via Windows SAPI (win32com).

Typical TTFA on a laptop: ~20–150 ms (no network).
Quality is OS-voice (not neural); use edge_fast for neural Tamil/Tanglish.

Requires: Windows + pip install pywin32

Most Windows installs only ship English voices (Zira/David). Tamil/Indic
packs are optional — call has_indic_voice() before relying on local Tamil.
"""
from __future__ import annotations

import logging
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tts_backends.base import TTSBackend  # noqa: E402

logger = logging.getLogger("tts.win_sapi")
_LOCK = threading.Lock()

_INDIC_HINTS = (
    "tamil",
    "ta-in",
    "ta_in",
    "hindi",
    "hi-in",
    "telugu",
    "kannada",
    "malayalam",
    "indic",
)
_FEMALE_HINTS = ("zira", "hazel", "susan", "eva", "helena", "catherine", "female")
_MALE_HINTS = ("david", "mark", "george", "james", "richard", "male")


def _voice_desc(voice) -> str:
    try:
        return str(voice.GetDescription())
    except Exception:  # noqa: BLE001
        return ""


def _list_voice_descriptions() -> list[str]:
    try:
        import win32com.client

        speaker = win32com.client.Dispatch("SAPI.SpVoice")
        return [_voice_desc(v) for v in speaker.GetVoices()]
    except Exception as exc:  # noqa: BLE001
        logger.debug("SAPI voice enumerate failed: %s", exc)
        return []


def has_indic_voice() -> bool:
    """True if any installed SAPI voice looks Tamil/Indic."""
    for desc in _list_voice_descriptions():
        low = desc.lower()
        if any(h in low for h in _INDIC_HINTS):
            return True
    return False


def _wants_male(voice_style: str) -> bool:
    s = (voice_style or "").lower()
    return any(k in s for k in ("rohit", "male", "valluvar", "prabhat", "david"))


def _wants_indic(voice_style: str) -> bool:
    s = (voice_style or "").lower()
    return any(k in s for k in ("jaya", "kavitha", "tamil", "pallavi", "valluvar", "indic"))


def _pick_voice(speaker, voice_style: str):
    """Prefer Indic when requested; else female/male English OS voice."""
    voices = list(speaker.GetVoices())
    if not voices:
        return None

    scored: list[tuple[int, object]] = []
    want_indic = _wants_indic(voice_style)
    want_male = _wants_male(voice_style)

    for v in voices:
        desc = _voice_desc(v).lower()
        score = 0
        is_indic = any(h in desc for h in _INDIC_HINTS)
        if want_indic and is_indic:
            score += 100
            if "tamil" in desc or "ta-in" in desc or "ta_in" in desc:
                score += 50
        if want_male and any(h in desc for h in _MALE_HINTS):
            score += 10
        if not want_male and any(h in desc for h in _FEMALE_HINTS):
            score += 10
        if not want_indic and is_indic:
            score -= 5  # don't surprise English requests with Indic
        scored.append((score, v))

    scored.sort(key=lambda t: t[0], reverse=True)
    return scored[0][1] if scored else None


class WinSapiBackend(TTSBackend):
    name = "win_sapi"

    def __init__(self, device: str | None = None):
        self.device = device or "cpu"
        self._mock = False
        self._ready = False
        self._speaker = None

    def warmup(self) -> None:
        self._ensure()
        if self._mock:
            return
        try:
            self.synthesize("OTP four eight two one.", "jaya")
            logger.info(
                "Windows SAPI warmup complete (indic_voice=%s)",
                has_indic_voice(),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Windows SAPI warmup failed: %s", exc)

    def _ensure(self) -> None:
        if self._ready or self._mock:
            return
        try:
            import win32com.client  # noqa: F401

            self._ready = True
        except ImportError:
            logger.warning("pywin32 missing — win_sapi mock. pip install pywin32")
            self._mock = True
            self._ready = True

    def synthesize(self, text: str, voice_style: str) -> bytes:
        self._ensure()
        text = (text or "").strip()
        if not text:
            return _silent_wav(0.2)
        if self._mock:
            return _silent_wav(max(0.5, min(5.0, len(text) * 0.04)))

        import win32com.client

        out = Path(tempfile.gettempdir()) / f"movio_sapi_{threading.get_ident()}.wav"
        with _LOCK:
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            stream = win32com.client.Dispatch("SAPI.SpFileStream")
            try:
                picked = _pick_voice(speaker, voice_style)
                if picked is not None:
                    speaker.Voice = picked
            except Exception:  # noqa: BLE001
                pass
            speaker.Rate = 2  # slightly faster delivery
            try:
                stream.Open(str(out), 3, False)  # SSFMCreateForWrite
                speaker.AudioOutputStream = stream
                speaker.Speak(text)
            finally:
                try:
                    stream.Close()
                except Exception:  # noqa: BLE001
                    pass

        data = out.read_bytes()
        try:
            out.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        if len(data) < 44:
            raise RuntimeError("SAPI produced empty WAV")
        return data


def _silent_wav(duration_sec: float = 1.0, sr: int = 22050) -> bytes:
    import struct
    import wave
    import io

    n = int(duration_sec * sr)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack("<" + "h" * n, *([0] * n)))
    return buf.getvalue()


def get_backend() -> WinSapiBackend:
    return WinSapiBackend()
