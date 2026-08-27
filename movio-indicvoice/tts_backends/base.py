"""Abstract TTS backend interface."""
from __future__ import annotations

from abc import ABC, abstractmethod


class TTSBackend(ABC):
    name: str = "base"

    @abstractmethod
    def synthesize(self, text: str, voice_style: str) -> bytes:
        """Synthesize speech and return WAV/PCM bytes."""

    def warmup(self) -> None:
        """Optional warmup for compile/cache."""
        return None
