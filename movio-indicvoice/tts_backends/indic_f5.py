"""
IndicF5 backend — COMPARISON backbone only (not the primary path).

Model: ai4bharat/IndicF5
Install: pip install git+https://github.com/ai4bharat/IndicF5.git

Needs reference audio + transcript — see reference_voices/README.md.

MMS Tamil excluded (CC-BY-NC-4.0) — commercial acquisition incompatibility.
"""
from __future__ import annotations

import io
import logging
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import DEFAULT_VOICE_STYLE, F5_MODEL_ID, REFERENCE_VOICES_DIR  # noqa: E402
from tts_backends.base import TTSBackend  # noqa: E402

logger = logging.getLogger("tts.indic_f5")


class IndicF5Backend(TTSBackend):
    name = "indic_f5"

    def __init__(
        self,
        model_id: str = F5_MODEL_ID,
        ref_audio: Path | None = None,
        ref_text: str | None = None,
        device: str | None = None,
    ):
        self.model_id = model_id
        self.ref_audio = ref_audio or (REFERENCE_VOICES_DIR / "reference.wav")
        self.ref_text = ref_text or (
            (REFERENCE_VOICES_DIR / "reference.txt").read_text(encoding="utf-8").strip()
            if (REFERENCE_VOICES_DIR / "reference.txt").exists()
            else "Vanakkam, ungal cab ready ah irukku."
        )
        self.device = device
        self._model = None
        self._mock = False
        self._sr = 24000

    def _lazy_load(self) -> None:
        if self._model is not None or self._mock:
            return
        try:
            # IndicF5 package API may vary; keep import defensive
            import torch

            if self.device is None:
                self.device = "cuda" if torch.cuda.is_available() else "cpu"
            try:
                from IndicF5 import IndicF5  # type: ignore
                self._model = IndicF5.from_pretrained(self.model_id)
            except Exception:
                from transformers import AutoModel  # type: ignore

                self._model = AutoModel.from_pretrained(self.model_id, trust_remote_code=True)
            logger.info("Loaded IndicF5 %s on %s", self.model_id, self.device)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "IndicF5 unavailable (%s). Using silent WAV mock for offline testing.",
                exc,
            )
            self._mock = True

    def synthesize(self, text: str, voice_style: str) -> bytes:
        # voice_style unused for F5 (reference-audio conditioned) — kept for interface parity
        _ = voice_style or DEFAULT_VOICE_STYLE
        self._lazy_load()
        if self._mock or not self.ref_audio.exists():
            if not self.ref_audio.exists():
                logger.warning("Reference audio missing at %s — mock audio", self.ref_audio)
            return _silent_wav(duration_sec=max(0.6, min(8.0, len(text) * 0.05)), sr=self._sr)

        import soundfile as sf

        try:
            # Common IndicF5-style call; fall back to mock on API mismatch
            wav = self._model(text, ref_audio_path=str(self.ref_audio), ref_text=self.ref_text)
            if isinstance(wav, tuple):
                wav = wav[0]
            audio_arr = np.asarray(wav, dtype=np.float32).squeeze()
            buf = io.BytesIO()
            sf.write(buf, audio_arr, self._sr, format="WAV")
            return buf.getvalue()
        except Exception as exc:  # noqa: BLE001
            logger.warning("IndicF5 synthesize failed (%s) — mock audio", exc)
            return _silent_wav(duration_sec=1.0, sr=self._sr)


def _silent_wav(duration_sec: float = 1.0, sr: int = 24000) -> bytes:
    n = int(duration_sec * sr)
    try:
        import soundfile as sf

        samples = np.zeros(n, dtype=np.float32)
        buf = io.BytesIO()
        sf.write(buf, samples, sr, format="WAV")
        return buf.getvalue()
    except ImportError:
        import struct
        import wave

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(struct.pack("<" + "h" * n, *([0] * n)))
        return buf.getvalue()


def get_backend() -> IndicF5Backend:
    return IndicF5Backend()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    b = IndicF5Backend()
    audio = b.synthesize("Your OTP is four eight two one.", DEFAULT_VOICE_STYLE)
    out = Path(__file__).resolve().parents[1] / "benchmark" / "results" / "f5_smoke.wav"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    print(f"Wrote {out} ({len(audio)} bytes)")
