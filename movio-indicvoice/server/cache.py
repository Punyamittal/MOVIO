"""
Layered TTS audio cache with in-flight request coalescing.

Lookup hierarchy (callers enforce order):
  full utterance → clause → template/slot unit → TTS

Keys include normalized text, language, voice, pronunciation version,
TTS model version, and audio format so config changes invalidate correctly.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger("server.cache")

CacheLevel = str  # "full" | "clause" | "template"


@dataclass
class CacheKeyParts:
    text: str
    voice_id: str
    target_language: str = "tanglish"
    pronunciation_version: str = "0"
    tts_model_version: str = "unknown"
    audio_format: str = "wav"
    level: CacheLevel = "full"
    template_id: str | None = None


@dataclass
class LatencyTracker:
    count: int = 0
    total_ms: float = 0.0

    def add(self, ms: float) -> None:
        self.count += 1
        self.total_ms += ms

    @property
    def average(self) -> float:
        return (self.total_ms / self.count) if self.count else 0.0


@dataclass
class CacheMetrics:
    full_sentence_hits: int = 0
    full_sentence_misses: int = 0
    clause_hits: int = 0
    clause_misses: int = 0
    template_hits: int = 0
    template_misses: int = 0
    tts_calls_total: int = 0
    tts_calls_saved: int = 0
    lookup_latency: LatencyTracker = field(default_factory=LatencyTracker)
    tts_latency: LatencyTracker = field(default_factory=LatencyTracker)
    end_to_end_latency: LatencyTracker = field(default_factory=LatencyTracker)
    # Estimated from average observed TTS latency × hits
    time_saved_ms: float = 0.0

    def record_lookup(self, level: CacheLevel, hit: bool, lookup_ms: float) -> None:
        self.lookup_latency.add(lookup_ms)
        if level == "full":
            if hit:
                self.full_sentence_hits += 1
            else:
                self.full_sentence_misses += 1
        elif level == "clause":
            if hit:
                self.clause_hits += 1
            else:
                self.clause_misses += 1
        else:
            if hit:
                self.template_hits += 1
            else:
                self.template_misses += 1
        if hit:
            self.tts_calls_saved += 1
            avg_tts = self.tts_latency.average
            self.time_saved_ms += avg_tts if avg_tts > 0 else 0.0

    def record_tts(self, tts_ms: float) -> None:
        self.tts_calls_total += 1
        self.tts_latency.add(tts_ms)

    def record_e2e(self, e2e_ms: float) -> None:
        self.end_to_end_latency.add(e2e_ms)

    @property
    def hits(self) -> int:
        return self.full_sentence_hits + self.clause_hits + self.template_hits

    @property
    def misses(self) -> int:
        return self.full_sentence_misses + self.clause_misses + self.template_misses

    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total) if total else 0.0

    def as_dict(self) -> dict:
        return {
            "full_sentence_hits": self.full_sentence_hits,
            "full_sentence_misses": self.full_sentence_misses,
            "clause_hits": self.clause_hits,
            "clause_misses": self.clause_misses,
            "template_hits": self.template_hits,
            "template_misses": self.template_misses,
            "tts_calls_saved": self.tts_calls_saved,
            "tts_calls_total": self.tts_calls_total,
            "cache_hit_rate": round(self.hit_rate(), 4),
            "average_tts_latency": round(self.tts_latency.average, 2),
            "average_cache_lookup_latency": round(self.lookup_latency.average, 4),
            "average_end_to_end_latency": round(self.end_to_end_latency.average, 2),
            "time_saved_by_cache": round(self.time_saved_ms, 2),
            # Back-compat aliases
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hit_rate(), 4),
        }


class AudioCache:
    def __init__(self, max_entries: int = 256):
        self.max_entries = max_entries
        self._store: OrderedDict[str, bytes] = OrderedDict()
        self._lock = threading.RLock()
        self._inflight: dict[str, Future[bytes]] = {}
        self.metrics = CacheMetrics()
        # Legacy counters kept in sync for older callers
        self.hits = 0
        self.misses = 0

    @staticmethod
    def make_key(
        normalized_text: str,
        voice_style: str,
        *,
        target_language: str = "tanglish",
        pronunciation_version: str = "0",
        tts_model_version: str = "unknown",
        audio_format: str = "wav",
        level: CacheLevel = "full",
        template_id: str | None = None,
    ) -> str:
        parts = CacheKeyParts(
            text=normalized_text,
            voice_id=voice_style,
            target_language=target_language,
            pronunciation_version=pronunciation_version,
            tts_model_version=tts_model_version,
            audio_format=audio_format,
            level=level,
            template_id=template_id,
        )
        return AudioCache.key_from_parts(parts)

    @staticmethod
    def key_from_parts(parts: CacheKeyParts) -> str:
        payload = "|".join(
            [
                parts.level,
                parts.template_id or "",
                parts.target_language,
                parts.voice_id,
                parts.pronunciation_version,
                parts.tts_model_version,
                parts.audio_format,
                parts.text,
            ]
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def _level_for_legacy(self) -> CacheLevel:
        return "full"

    def get(
        self,
        normalized_text: str,
        voice_style: str,
        *,
        target_language: str = "tanglish",
        pronunciation_version: str = "0",
        tts_model_version: str = "unknown",
        audio_format: str = "wav",
        level: CacheLevel = "full",
        template_id: str | None = None,
    ) -> bytes | None:
        t0 = time.perf_counter()
        key = self.make_key(
            normalized_text,
            voice_style,
            target_language=target_language,
            pronunciation_version=pronunciation_version,
            tts_model_version=tts_model_version,
            audio_format=audio_format,
            level=level,
            template_id=template_id,
        )
        with self._lock:
            hit = key in self._store
            audio = None
            if hit:
                self._store.move_to_end(key)
                audio = self._store[key]
                self.hits += 1
            else:
                self.misses += 1
        lookup_ms = (time.perf_counter() - t0) * 1000
        self.metrics.record_lookup(level, hit, lookup_ms)
        if hit:
            logger.info("cache HIT level=%s rate=%.2f", level, self.hit_rate())
            return audio
        logger.info("cache MISS level=%s rate=%.2f", level, self.hit_rate())
        return None

    def put(
        self,
        normalized_text: str,
        voice_style: str,
        audio: bytes,
        *,
        target_language: str = "tanglish",
        pronunciation_version: str = "0",
        tts_model_version: str = "unknown",
        audio_format: str = "wav",
        level: CacheLevel = "full",
        template_id: str | None = None,
    ) -> None:
        key = self.make_key(
            normalized_text,
            voice_style,
            target_language=target_language,
            pronunciation_version=pronunciation_version,
            tts_model_version=tts_model_version,
            audio_format=audio_format,
            level=level,
            template_id=template_id,
        )
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
                self._store[key] = audio
            else:
                self._store[key] = audio
                while len(self._store) > self.max_entries:
                    self._store.popitem(last=False)

    def get_or_generate(
        self,
        normalized_text: str,
        voice_style: str,
        generate_fn: Callable[[], bytes],
        *,
        target_language: str = "tanglish",
        pronunciation_version: str = "0",
        tts_model_version: str = "unknown",
        audio_format: str = "wav",
        level: CacheLevel = "clause",
        template_id: str | None = None,
    ) -> tuple[bytes, bool]:
        """
        Cache lookup with in-flight coalescing.

        Concurrent misses for the same key share one TTS call.
        Returns (audio, cache_hit) where cache_hit is True only for store hits
        (waiters on an in-flight generate count as miss→shared, hit=False for
        the generator and True for waiters that arrive after put — waiters that
        join in-flight are recorded as hits for tts_calls_saved).
        """
        key = self.make_key(
            normalized_text,
            voice_style,
            target_language=target_language,
            pronunciation_version=pronunciation_version,
            tts_model_version=tts_model_version,
            audio_format=audio_format,
            level=level,
            template_id=template_id,
        )
        t0 = time.perf_counter()
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
                audio = self._store[key]
                self.hits += 1
                lookup_ms = (time.perf_counter() - t0) * 1000
                self.metrics.record_lookup(level, True, lookup_ms)
                return audio, True

            fut = self._inflight.get(key)
            is_leader = False
            if fut is None:
                fut = Future()
                self._inflight[key] = fut
                is_leader = True
            else:
                # Joiner: will reuse in-flight result (counts as saved TTS)
                self.hits += 1
                lookup_ms = (time.perf_counter() - t0) * 1000
                self.metrics.record_lookup(level, True, lookup_ms)

        if not is_leader:
            audio = fut.result()
            return audio, True

        self.misses += 1
        lookup_ms = (time.perf_counter() - t0) * 1000
        self.metrics.record_lookup(level, False, lookup_ms)
        try:
            tts_t0 = time.perf_counter()
            audio = generate_fn()
            tts_ms = (time.perf_counter() - tts_t0) * 1000
            self.metrics.record_tts(tts_ms)
            with self._lock:
                if key in self._store:
                    self._store.move_to_end(key)
                    self._store[key] = audio
                else:
                    self._store[key] = audio
                    while len(self._store) > self.max_entries:
                        self._store.popitem(last=False)
            fut.set_result(audio)
            return audio, False
        except Exception as exc:  # noqa: BLE001
            fut.set_exception(exc)
            raise
        finally:
            with self._lock:
                self._inflight.pop(key, None)

    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total) if total else 0.0

    def record_end_to_end(self, e2e_ms: float) -> None:
        self.metrics.record_e2e(e2e_ms)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self._inflight.clear()

    def stats(self) -> dict:
        base = self.metrics.as_dict()
        base.update(
            {
                "size": len(self._store),
                "max_entries": self.max_entries,
                "inflight": len(self._inflight),
            }
        )
        return base
