"""Canonical record schemas for the speech dataset pipeline."""
from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

QualityStatus = Literal["accepted", "review", "rejected"]
LanguageLabel = Literal["ta", "en", "ta-en", "other", "unknown"]
Difficulty = Literal["easy", "medium", "hard"]
Domain = Literal[
    "general_conversation",
    "transport",
    "directions",
    "travel",
    "customer_service",
    "shopping",
    "food",
    "payments",
    "locations",
    "time",
    "numbers",
    "phone_calls",
    "code_switching",
    "other",
]


def new_sample_id(prefix: str = "sample") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@dataclass
class SourceCandidate:
    source: str = "youtube"
    video_id: str = ""
    title: str = ""
    channel: str = ""
    url: str = ""
    license: str = "unknown"
    license_verified: bool = False
    usable_for_training: bool = False
    discovery_query: str = ""
    duration: float = 0.0
    language_guess: str = ""
    domain: str = "general_conversation"
    description: str = ""
    view_count: int = 0
    discovered_at: float = field(default_factory=time.time)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SourceCandidate":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class UtteranceRecord:
    id: str
    audio: str = ""
    source: str = "youtube"
    source_video_id: str = ""
    start: float = 0.0
    end: float = 0.0

    language: LanguageLabel = "unknown"
    transcript_raw: str = ""
    transcript_normalized: str = ""
    tanglish: str = ""
    translation_en: str = ""  # separate from Tanglish / transliteration
    transliteration: str = ""  # mechanical Latin if any; prefer tanglish field

    speaker_id: str = "spk_unknown"
    speaker_segment_count: int = 1
    domain: str = "general_conversation"

    duration: float = 0.0
    stt_confidence: float = 0.0
    quality_score: float = 0.0
    noise_level: str = "unknown"
    code_switching: bool = False
    difficulty: Difficulty = "medium"

    license: str = "unknown"
    license_verified: bool = False
    usable_for_training: bool = False

    status: QualityStatus = "review"
    verified: bool = False
    human_edited: bool = False

    discovery_query: str = ""
    audio_sha256: str = ""
    transcript_sha256: str = ""
    quality_flags: list[str] = field(default_factory=list)
    timestamps: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "UtteranceRecord":
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})
