"""
Fine-tuning speech dataset collection pipeline for IndicVoice / Movio.

Separated from runtime TTS/server and from optional text-only sourcing/.
Does NOT overwrite sourcing/output, data_generation/output, or benchmark/data.
"""
from __future__ import annotations

__version__ = "0.1.0"
