"""
Core TTS pipeline: normalizer → lexicon → tanglish_llm → validator → TTS.

Cache hierarchy (when AudioCache is attached):
  Normalize + pronunciation
       ↓
  Full utterance cache?  → HIT → return
       ↓ MISS
  Clause split → (optional) template/slot decompose
       ↓
  Per-unit cache with in-flight coalescing
       ↓
  TTS only for misses → stitch → store full utterance
"""
from __future__ import annotations

import hashlib
import inspect
import json
import logging
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterator

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    CACHE_STITCH_GAP_MS,
    CLAUSE_CACHE_ENABLED,
    DEFAULT_TARGET_LANG,
    DEFAULT_TTS_BACKEND,
    DEFAULT_VOICE_STYLE,
    PRONUNCIATION_LEXICON_PATH,
    TEMPLATE_CACHE_ENABLED,
    TRANSLATOR_ENABLED,
)
from normalization.deterministic_normalizer import apply_lexicon, normalize  # noqa: E402
from normalization.language_translator import (  # noqa: E402
    detect_language,
    translate as translate_text,
)
from normalization.pronunciation_rules import flatten_lexicon_entries  # noqa: E402
from normalization.speakability import (  # noqa: E402
    is_latin_only_backend,
    latin_safe_lexicon,
    prepare_for_tanglish_tts,
    resolve_speak_target,
)
from normalization.tanglish_llm_layer import apply_tanglish_layer  # noqa: E402
from normalization.validator import validate  # noqa: E402
from server.templates import SynthUnit, get_template_registry  # noqa: E402
from server.websocket_stream import concat_wavs, split_clauses  # noqa: E402
from tts_backends.base import TTSBackend  # noqa: E402
from tts_backends.indic_f5 import IndicF5Backend  # noqa: E402


logger = logging.getLogger("server.pipeline")


@dataclass
class TimingBreakdown:
    request_received: float
    normalization_complete: float = 0.0
    tts_started: float = 0.0
    first_audio_generated: float = 0.0
    first_audio_sent: float = 0.0
    generation_complete: float = 0.0
    response_complete: float = 0.0

    def preprocessing_ms(self) -> float:
        return (self.normalization_complete - self.request_received) * 1000

    def ttfa_ms(self) -> float:
        """Time to first audio byte/chunk — DISTINCT from full synthesis latency."""
        return (self.first_audio_generated - self.request_received) * 1000

    def full_synthesis_ms(self) -> float:
        """Full synthesis latency — DISTINCT from TTFA."""
        return (self.generation_complete - self.tts_started) * 1000

    def end_to_end_ms(self) -> float:
        return (self.response_complete - self.request_received) * 1000


@dataclass
class PipelineResult:
    audio: bytes
    original_text: str
    normalized_text: str
    backend: str
    voice_style: str
    timing: TimingBreakdown
    validator_ok: bool
    validator_flags: list[str] = field(default_factory=list)
    cache_hit: bool = False
    audio_duration_sec: float = 0.0
    rtf: float = 0.0
    chunk_count: int = 1
    translated_text: str = ""
    detected_lang: str = ""
    target_lang: str = ""
    translator_engine: str = ""
    audio_format: str = "wav"
    cache_level: str = ""
    units_synthesized: int = 0
    units_from_cache: int = 0

    def metrics_dict(self) -> dict:
        t = self.timing
        return {
            "backend": self.backend,
            "cache_hit": self.cache_hit,
            "cache_level": self.cache_level,
            "preprocessing_ms": round(t.preprocessing_ms(), 2),
            "ttfa_ms": round(t.ttfa_ms(), 2),
            "full_synthesis_ms": round(t.full_synthesis_ms(), 2),
            "end_to_end_ms": round(t.end_to_end_ms(), 2),
            "audio_duration_sec": round(self.audio_duration_sec, 3),
            "rtf": round(self.rtf, 4),
            "validator_ok": self.validator_ok,
            "validator_flags": self.validator_flags,
            "normalized_text": self.normalized_text,
            "chunk_count": self.chunk_count,
            "units_synthesized": self.units_synthesized,
            "units_from_cache": self.units_from_cache,
            "translated_text": self.translated_text,
            "detected_lang": self.detected_lang,
            "target_lang": self.target_lang,
            "translator_engine": self.translator_engine,
            "audio_format": self.audio_format,
        }


def load_lexicon(path: Path = PRONUNCIATION_LEXICON_PATH) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def pronunciation_version(lexicon: dict | None = None, path: Path = PRONUNCIATION_LEXICON_PATH) -> str:
    """Stable fingerprint of pronunciation + gold pairs for cache invalidation."""
    from normalization.tanglish_translator import gold_pairs_version  # noqa: E402

    if lexicon is None:
        if path.exists():
            raw = path.read_bytes()
        else:
            raw = b""
    else:
        # Exclude meta keys from identity
        clean = {k: v for k, v in lexicon.items() if not str(k).startswith("_")}
        raw = json.dumps(clean, sort_keys=True, ensure_ascii=False).encode("utf-8")
    raw = raw + gold_pairs_version().encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def get_backend(name: str | None = None) -> TTSBackend:
    name = (name or DEFAULT_TTS_BACKEND).lower()
    if name in ("win_sapi", "sapi", "turbo", "local"):
        from tts_backends.win_sapi import WinSapiBackend

        return WinSapiBackend()
    if name in ("indic_f5", "f5"):
        return IndicF5Backend()
    # Default / unknown → edge_fast (low-latency neural). If edge-tts is
    # missing, fall back to Windows SAPI instead of shipping silent audio.
    from tts_backends.edge_fast import EdgeFastBackend

    try:
        import edge_tts  # noqa: F401
        import aiohttp  # noqa: F401
    except ImportError:
        logger.warning(
            "edge-tts missing — falling back to win_sapi (pip install edge-tts)"
        )
        from tts_backends.win_sapi import WinSapiBackend

        return WinSapiBackend()
    return EdgeFastBackend()


def voice_style_for_target(voice_style: str | None, target_lang: str | None) -> str:
    """Prefer a Tamil Edge voice when speaking Tanglish/Tamil (avoid English neural)."""
    style = (voice_style or DEFAULT_VOICE_STYLE).strip()
    tgt = (target_lang or "").lower().strip()
    if tgt not in ("tanglish", "ta", "tamil", "ta-in"):
        return style or DEFAULT_VOICE_STYLE
    lower = style.lower()
    if any(k in lower for k in ("divya", "rohit", "neerja", "prabhat", "english", "en-in")):
        return DEFAULT_VOICE_STYLE
    if not any(k in lower for k in ("jaya", "kavitha", "pallavi", "valluvar", "tamil", "ta-in")):
        return DEFAULT_VOICE_STYLE
    return style or DEFAULT_VOICE_STYLE


def estimate_wav_duration(audio: bytes) -> float:
    try:
        import io
        import soundfile as sf

        info = sf.info(io.BytesIO(audio))
        return float(info.duration)
    except Exception:  # noqa: BLE001
        try:
            import io
            import wave

            with wave.open(io.BytesIO(audio), "rb") as wf:
                return wf.getnframes() / float(wf.getframerate() or 22050)
        except Exception:  # noqa: BLE001
            return max(0.0, (len(audio) - 44) / (22050 * 2))


class TTSPipeline:
    def __init__(
        self,
        backend: TTSBackend | None = None,
        cache: object | None = None,
        skip_llm: bool = False,
        target_lang: str | None = None,
        translate_enabled: bool | None = None,
        clause_cache: bool | None = None,
        template_cache: bool | None = None,
        stitch_gap_ms: float | None = None,
    ):
        self.backend = backend or get_backend()
        self.cache = cache
        self.skip_llm = skip_llm
        self.target_lang = target_lang or DEFAULT_TARGET_LANG
        self.translate_enabled = (
            TRANSLATOR_ENABLED if translate_enabled is None else translate_enabled
        )
        self.lexicon = load_lexicon()
        self.pronunciation_version = pronunciation_version(self.lexicon)
        self.templates = get_template_registry()
        self.clause_cache_enabled = CLAUSE_CACHE_ENABLED if clause_cache is None else clause_cache
        self.template_cache_enabled = (
            TEMPLATE_CACHE_ENABLED if template_cache is None else template_cache
        )
        self.stitch_gap_ms = CACHE_STITCH_GAP_MS if stitch_gap_ms is None else stitch_gap_ms

    def _cache_identity(self, target_lang: str | None) -> dict:
        backend_name = getattr(self.backend, "name", "unknown")
        audio_format = getattr(self.backend, "audio_format", "wav")
        # Recompute each request so gold/lexicon edits invalidate audio cache
        # without requiring a full process restart.
        return {
            "target_language": (target_lang or self.target_lang or "tanglish"),
            "pronunciation_version": pronunciation_version(self.lexicon),
            "tts_model_version": f"{backend_name}:{audio_format}",
            "audio_format": audio_format,
        }

    def preprocess(
        self,
        text: str,
        target_lang: str | None = None,
    ) -> tuple[str, bool, list[str], dict]:
        """
        Order: translate → deterministic normalize → optional Tanglish LLM → validate.
        Returns (final_text, ok, flags, translate_meta).

        Latin-only backends (Windows SAPI without Indic voice):
        keep Tanglish as Latin code-mix (phoneticized); rewrite pure Tamil
        script to English; skip Tamil-script lexicon entries.
        """
        requested = target_lang or self.target_lang
        backend_name = getattr(self.backend, "name", "")
        detected = detect_language(text or "")
        has_indic = False
        if is_latin_only_backend(backend_name):
            try:
                from tts_backends.win_sapi import has_indic_voice

                has_indic = bool(has_indic_voice())
            except Exception:  # noqa: BLE001
                has_indic = False
        tgt = resolve_speak_target(
            backend_name, requested, detected, has_indic_os_voice=has_indic
        )
        # Phonetic / latin-safe path only when SAPI has no Indic voice
        latin_only = is_latin_only_backend(backend_name) and not has_indic

        tr = translate_text(text, target_lang=tgt, enabled=self.translate_enabled)
        meta = {
            "plain_text": "",
            "translated_text": tr.text,
            "detected_lang": tr.detected_lang or detected,
            "target_lang": tr.target_lang,
            "translator_engine": tr.engine,
            "requested_target_lang": requested,
            "speak_adapted": latin_only and tgt != (requested or "").lower(),
            "indic_os_voice": has_indic,
        }
        if tr.audit is not None:
            meta["tanglish_audit"] = tr.audit
        logger.info(
            "preprocess translate engine=%s target=%s text_len=%d",
            tr.engine,
            tr.target_lang,
            len(tr.text or ""),
        )
        lex_raw = load_lexicon()
        lex_flat = flatten_lexicon_entries(lex_raw)
        lex = latin_safe_lexicon(lex_flat) if latin_only else lex_flat
        # Kept apart so template matching can see the plain spelling: the
        # lexicon rewrites "driver" to "dryvur", which no template matches.
        det_plain = normalize(tr.text)
        det = apply_lexicon(det_plain, lex_flat) if lex_flat else det_plain
        # Gold pairs are human-verified — never re-run the Tanglish LLM on them.
        skip_tanglish_llm = tr.engine == "gold"
        if (
            self.skip_llm
            or skip_tanglish_llm
            or tr.target_lang not in ("tanglish", "auto")
            or latin_only
        ):
            spoken = det
        else:
            spoken = apply_tanglish_layer(det)
        if tr.target_lang in ("tanglish", "auto"):
            spoken = prepare_for_tanglish_tts(
                spoken,
                backend_name=backend_name,
                lexicon=lex,
            )
        result = validate(text, spoken)
        # Only offer the plain text when the lexicon was the sole difference;
        # any later rewrite would leave the two texts out of step.
        if spoken == det and result.text == spoken:
            meta["plain_text"] = det_plain
        return result.text, result.ok, result.flags, meta

    def _raw_synth(
        self,
        text: str,
        voice_style: str,
        on_first_audio: Callable[[bytes], None] | None = None,
    ) -> bytes:
        first_done = False

        def _mark_first(chunk: bytes) -> None:
            nonlocal first_done
            if not first_done:
                first_done = True
                if on_first_audio:
                    on_first_audio(chunk)

        synth = getattr(self.backend, "synthesize")
        try:
            accepts_cb = "on_first_audio" in inspect.signature(synth).parameters
        except (TypeError, ValueError):
            accepts_cb = False
        if accepts_cb:
            audio = synth(text, voice_style, on_first_audio=_mark_first)
        else:
            audio = synth(text, voice_style)
            _mark_first(audio)
        return audio

    def _unit_level(self, unit: SynthUnit) -> str:
        if unit.kind in ("static", "dynamic") and unit.template_id:
            return "template"
        return "clause"

    def _synth_unit(
        self,
        unit: SynthUnit,
        voice_style: str,
        identity: dict,
        on_first_audio: Callable[[bytes], None] | None = None,
    ) -> tuple[bytes, bool]:
        """Synthesize one phrase-sized unit with coalesced cache."""
        level = self._unit_level(unit)
        if self.cache is None:
            return self._raw_synth(unit.text, voice_style, on_first_audio=on_first_audio), False

        get_or_gen = getattr(self.cache, "get_or_generate", None)
        if get_or_gen is None:
            # Legacy cache API
            hit = self.cache.get(unit.text, voice_style)  # type: ignore[attr-defined]
            if hit is not None:
                if on_first_audio:
                    on_first_audio(hit)
                return hit, True
            audio = self._raw_synth(unit.text, voice_style, on_first_audio=on_first_audio)
            self.cache.put(unit.text, voice_style, audio)  # type: ignore[attr-defined]
            return audio, False

        def _gen() -> bytes:
            return self._raw_synth(unit.text, voice_style, on_first_audio=on_first_audio)

        audio, hit = get_or_gen(
            unit.text,
            voice_style,
            _gen,
            target_language=identity["target_language"],
            pronunciation_version=identity["pronunciation_version"],
            tts_model_version=identity["tts_model_version"],
            audio_format=identity["audio_format"],
            level=level,
            template_id=unit.template_id,
        )
        if hit and on_first_audio:
            on_first_audio(audio)
        return audio, hit

    def _synth_one(
        self,
        text: str,
        voice_style: str,
        on_first_audio: Callable[[bytes], None] | None = None,
        identity: dict | None = None,
    ) -> tuple[bytes, bool, float | None]:
        """Synthesize one clause (legacy entry); returns (audio, cache_hit, first_audio_perf)."""
        first_perf: float | None = None

        def _mark(chunk: bytes) -> None:
            nonlocal first_perf
            if first_perf is None:
                first_perf = time.perf_counter()
            if on_first_audio:
                on_first_audio(chunk)

        unit = SynthUnit(text=text, kind="clause")
        ident = identity or self._cache_identity(None)
        audio, hit = self._synth_unit(unit, voice_style, ident, on_first_audio=_mark)
        return audio, hit, first_perf

    def _decompose_utterance(self, normalized: str, plain: str = "") -> list[SynthUnit]:
        clauses = split_clauses(normalized)
        if not clauses:
            return []
        if not self.clause_cache_enabled:
            return [SynthUnit(text=normalized, kind="clause")]
        if not self.template_cache_enabled:
            return [SynthUnit(text=c, kind="clause") for c in clauses]

        # Templates are written in plain spelling, but the text we speak has
        # been through the pronunciation lexicon. Match on the plain clause,
        # then phoneticise each unit so the audio still matches the utterance.
        plain_clauses = split_clauses(plain) if plain and plain != normalized else []
        if len(plain_clauses) != len(clauses):
            plain_clauses = []
        lex = flatten_lexicon_entries(load_lexicon()) if plain_clauses else {}

        units: list[SynthUnit] = []
        for i, clause in enumerate(clauses):
            match = self.templates.match(plain_clauses[i]) if plain_clauses else None
            if match is not None:
                units.extend(
                    replace(u, text=apply_lexicon(u.text, lex)) if lex else u
                    for u in match.units
                )
                continue
            units.extend(self.templates.decompose(clause))
        return units

    def _peek_cached(self, unit: SynthUnit, voice_style: str, identity: dict) -> bool:
        if self.cache is None:
            return False
        get = getattr(self.cache, "get", None)
        if get is None:
            return False
        # Peek without double-counting metrics: use store directly when possible
        key_fn = getattr(self.cache, "make_key", None)
        store = getattr(self.cache, "_store", None)
        if key_fn is not None and store is not None:
            key = key_fn(
                unit.text,
                voice_style,
                target_language=identity["target_language"],
                pronunciation_version=identity["pronunciation_version"],
                tts_model_version=identity["tts_model_version"],
                audio_format=identity["audio_format"],
                level=self._unit_level(unit),
                template_id=unit.template_id,
            )
            with getattr(self.cache, "_lock"):
                return key in store
        try:
            return (
                get(
                    unit.text,
                    voice_style,
                    target_language=identity["target_language"],
                    pronunciation_version=identity["pronunciation_version"],
                    tts_model_version=identity["tts_model_version"],
                    audio_format=identity["audio_format"],
                    level=self._unit_level(unit),
                    template_id=unit.template_id,
                )
                is not None
            )
        except TypeError:
            return get(unit.text, voice_style) is not None

    def _plan_units_for_cache(
        self,
        units: list[SynthUnit],
        voice_style: str,
        identity: dict,
    ) -> list[SynthUnit]:
        """
        Naturalness-first planning:
        - If any template unit is already cached → stitch (reuse static/dynamic).
        - If all cold → synthesize the whole reconstructed clause once (1 TTS),
          then eagerly warm static units so later slot variants can stitch.
        """
        if not units or not self.template_cache_enabled:
            return units
        out: list[SynthUnit] = []
        i = 0
        while i < len(units):
            u = units[i]
            if u.kind in ("static", "dynamic") and u.template_id:
                j = i
                group: list[SynthUnit] = []
                while j < len(units) and units[j].template_id == u.template_id:
                    group.append(units[j])
                    j += 1
                if any(self._peek_cached(g, voice_style, identity) for g in group):
                    out.extend(group)
                else:
                    joined = " ".join(g.text.rstrip(" .") for g in group).strip()
                    if not joined.endswith("."):
                        joined += "."
                    out.append(
                        SynthUnit(
                            text=joined,
                            kind="clause",
                            template_id=u.template_id,
                        )
                    )
                    # Remember static units to warm after this request
                    for g in group:
                        if g.kind == "static":
                            out.append(
                                SynthUnit(
                                    text=g.text,
                                    kind="static",
                                    template_id=g.template_id,
                                    slot_name="__warm_only__",
                                )
                            )
                i = j
            else:
                out.append(u)
                i += 1
        return out

    def _is_warm_only(self, unit: SynthUnit) -> bool:
        return unit.slot_name == "__warm_only__"

    def _result(
        self,
        *,
        audio: bytes,
        text: str,
        normalized: str,
        timing: TimingBreakdown,
        v_ok: bool,
        v_flags: list[str],
        cache_hit: bool,
        chunk_count: int,
        meta: dict,
        rtf: float = 0.0,
        cache_level: str = "",
        units_synthesized: int = 0,
        units_from_cache: int = 0,
    ) -> PipelineResult:
        duration = estimate_wav_duration(audio)
        return PipelineResult(
            audio=audio,
            original_text=text,
            normalized_text=normalized,
            backend=getattr(self.backend, "name", "unknown"),
            voice_style="",
            timing=timing,
            validator_ok=v_ok,
            validator_flags=v_flags,
            cache_hit=cache_hit,
            audio_duration_sec=duration,
            rtf=rtf,
            chunk_count=chunk_count,
            translated_text=meta.get("translated_text", ""),
            detected_lang=meta.get("detected_lang", ""),
            target_lang=meta.get("target_lang", ""),
            translator_engine=meta.get("translator_engine", ""),
            audio_format=getattr(self.backend, "audio_format", "wav"),
            cache_level=cache_level,
            units_synthesized=units_synthesized,
            units_from_cache=units_from_cache,
        )

    def iter_chunks(
        self,
        text: str,
        voice_style: str | None = None,
        target_lang: str | None = None,
    ) -> Iterator[dict]:
        voice_style = voice_style or DEFAULT_VOICE_STYLE
        t0 = time.perf_counter()
        normalized, v_ok, v_flags, meta = self.preprocess(text, target_lang=target_lang)
        voice_style = voice_style_for_target(voice_style, meta.get("target_lang") or target_lang)
        identity = self._cache_identity(meta.get("target_lang") or target_lang)
        units = self._decompose_utterance(normalized, meta.get("plain_text") or "")
        logger.info("Chunked TTS into %d unit(s)", len(units))
        first_ms = None
        for i, unit in enumerate(units):
            first_perf: float | None = None

            def _mark(chunk: bytes) -> None:
                nonlocal first_perf
                if first_perf is None:
                    first_perf = time.perf_counter()

            audio, hit = self._synth_unit(unit, voice_style, identity, on_first_audio=_mark)
            now = first_perf or time.perf_counter()
            if first_ms is None:
                first_ms = (now - t0) * 1000
            yield {
                "index": i,
                "text": unit.text,
                "kind": unit.kind,
                "template_id": unit.template_id,
                "audio": audio,
                "cache_hit": hit,
                "ttfa_ms": round(first_ms, 2) if i == 0 else None,
                "normalized_text": normalized,
                "validator_ok": v_ok,
                "validator_flags": v_flags,
                "chunk_count": len(units),
                "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                **meta,
            }

    def run(
        self,
        text: str,
        voice_style: str | None = None,
        on_first_audio: Callable[[bytes], None] | None = None,
        chunked: bool = True,
        target_lang: str | None = None,
    ) -> PipelineResult:
        # Layered cache path is always used when cache is present and clause
        # cache is enabled — even if caller asked for single-shot.
        # Exception: MP3 backends (edge_fast) cannot stitch without pydub, and
        # the fallback returns only the FIRST clause — that is the incomplete
        # sentence users hear. Prefer one full-utterance synth for MP3.
        if (
            self.cache is not None
            and self.clause_cache_enabled
            and getattr(self.backend, "audio_format", "wav") != "mp3"
        ):
            return self.run_chunked(
                text, voice_style, on_first_audio=on_first_audio, target_lang=target_lang
            )
        if chunked and getattr(self.backend, "audio_format", "wav") != "mp3":
            return self.run_chunked(
                text, voice_style, on_first_audio=on_first_audio, target_lang=target_lang
            )
        return self._run_single(
            text, voice_style, on_first_audio=on_first_audio, target_lang=target_lang
        )

    def run_chunked(
        self,
        text: str,
        voice_style: str | None = None,
        on_first_audio: Callable[[bytes], None] | None = None,
        target_lang: str | None = None,
    ) -> PipelineResult:
        voice_style = voice_style or DEFAULT_VOICE_STYLE
        timing = TimingBreakdown(request_received=time.perf_counter())

        normalized_probe, v_ok, v_flags, meta = self.preprocess(text, target_lang=target_lang)
        voice_style = voice_style_for_target(voice_style, meta.get("target_lang") or target_lang)
        identity = self._cache_identity(meta.get("target_lang") or target_lang)
        timing.normalization_complete = time.perf_counter()

        # --- Full utterance cache (fastest path) ---
        if self.cache is not None:
            full_kwargs = dict(
                target_language=identity["target_language"],
                pronunciation_version=identity["pronunciation_version"],
                tts_model_version=identity["tts_model_version"],
                audio_format=identity["audio_format"],
                level="full",
            )
            get = self.cache.get
            try:
                full_hit = get(normalized_probe, voice_style, **full_kwargs)  # type: ignore[misc]
            except TypeError:
                full_hit = get(normalized_probe, voice_style)  # type: ignore[misc]
            if full_hit is not None:
                timing.tts_started = time.perf_counter()
                timing.first_audio_generated = timing.tts_started
                timing.generation_complete = timing.tts_started
                timing.first_audio_sent = timing.tts_started
                if on_first_audio:
                    on_first_audio(full_hit)
                timing.response_complete = time.perf_counter()
                if hasattr(self.cache, "record_end_to_end"):
                    self.cache.record_end_to_end(timing.end_to_end_ms())  # type: ignore[attr-defined]
                res = self._result(
                    audio=full_hit,
                    text=text,
                    normalized=normalized_probe,
                    timing=timing,
                    v_ok=v_ok,
                    v_flags=v_flags,
                    cache_hit=True,
                    chunk_count=1,
                    meta=meta,
                    cache_level="full",
                    units_from_cache=1,
                )
                res.voice_style = voice_style
                return res

        timing.tts_started = time.perf_counter()
        units = self._decompose_utterance(normalized_probe, meta.get("plain_text") or "")
        units = self._plan_units_for_cache(units, voice_style, identity)
        logger.info(
            "Layered TTS: %d unit(s) after full miss (clause=%s template=%s)",
            len(units),
            self.clause_cache_enabled,
            self.template_cache_enabled,
        )
        parts: list[bytes] = []
        from_cache = 0
        synthesized = 0
        speak_units = [u for u in units if not self._is_warm_only(u)]
        warm_only = [u for u in units if self._is_warm_only(u)]
        for i, unit in enumerate(speak_units):
            cb = on_first_audio if i == 0 else None
            first_perf: float | None = None

            def _mark(chunk: bytes, _cb=cb) -> None:
                nonlocal first_perf
                if first_perf is None:
                    first_perf = time.perf_counter()
                if _cb:
                    _cb(chunk)

            audio, hit = self._synth_unit(unit, voice_style, identity, on_first_audio=_mark)
            if hit:
                from_cache += 1
            else:
                synthesized += 1
            parts.append(audio)
            if i == 0:
                timing.first_audio_generated = first_perf or time.perf_counter()
                timing.first_audio_sent = timing.first_audio_generated

        gap = self.stitch_gap_ms if len(parts) > 1 else 0.0
        audio = concat_wavs(parts, gap_ms=gap)
        timing.generation_complete = time.perf_counter()

        # Warm static prefixes after audible audio is ready (excluded from full_synthesis_ms)
        for unit in warm_only:
            if not self._peek_cached(unit, voice_style, identity):
                self._synth_unit(unit, voice_style, identity)
                synthesized += 1

        if self.cache is not None:
            put = self.cache.put
            try:
                put(
                    normalized_probe,
                    voice_style,
                    audio,
                    target_language=identity["target_language"],
                    pronunciation_version=identity["pronunciation_version"],
                    tts_model_version=identity["tts_model_version"],
                    audio_format=identity["audio_format"],
                    level="full",
                )
            except TypeError:
                put(normalized_probe, voice_style, audio)  # type: ignore[misc]

        duration = estimate_wav_duration(audio)
        synth = max(timing.full_synthesis_ms() / 1000.0, 1e-6)
        rtf = synth / duration if duration > 0 else 0.0
        timing.response_complete = time.perf_counter()
        if hasattr(self.cache, "record_end_to_end") and self.cache is not None:
            self.cache.record_end_to_end(timing.end_to_end_ms())  # type: ignore[attr-defined]

        all_cached = synthesized == 0 and from_cache > 0
        level = "template" if any(u.template_id for u in speak_units) else "clause"
        res = self._result(
            audio=audio,
            text=text,
            normalized=normalized_probe,
            timing=timing,
            v_ok=v_ok,
            v_flags=v_flags,
            cache_hit=all_cached,
            chunk_count=len(speak_units),
            meta=meta,
            rtf=rtf,
            cache_level=level if not all_cached or level else "clause",
            units_synthesized=synthesized,
            units_from_cache=from_cache,
        )
        res.voice_style = voice_style
        res.audio_duration_sec = duration
        # Stitched output is WAV even if backend emits MP3 units
        if len(parts) > 1:
            res.audio_format = "wav"
        return res

    def _run_single(
        self,
        text: str,
        voice_style: str | None = None,
        on_first_audio: Callable[[bytes], None] | None = None,
        target_lang: str | None = None,
    ) -> PipelineResult:
        voice_style = voice_style or DEFAULT_VOICE_STYLE
        timing = TimingBreakdown(request_received=time.perf_counter())

        normalized, v_ok, v_flags, meta = self.preprocess(text, target_lang=target_lang)
        voice_style = voice_style_for_target(voice_style, meta.get("target_lang") or target_lang)
        identity = self._cache_identity(meta.get("target_lang") or target_lang)
        timing.normalization_complete = time.perf_counter()

        cache_hit = False
        audio: bytes | None = None
        first_perf: float | None = None
        if self.cache is not None:
            get = self.cache.get
            try:
                audio = get(
                    normalized,
                    voice_style,
                    target_language=identity["target_language"],
                    pronunciation_version=identity["pronunciation_version"],
                    tts_model_version=identity["tts_model_version"],
                    audio_format=identity["audio_format"],
                    level="full",
                )
            except TypeError:
                audio = get(normalized, voice_style)  # type: ignore[misc]
            if audio is not None:
                cache_hit = True
                timing.tts_started = time.perf_counter()
                timing.first_audio_generated = timing.tts_started
                timing.generation_complete = timing.tts_started
                if on_first_audio:
                    on_first_audio(audio)
                    timing.first_audio_sent = time.perf_counter()
                else:
                    timing.first_audio_sent = timing.first_audio_generated

        if audio is None:
            timing.tts_started = time.perf_counter()

            def _mark(chunk: bytes) -> None:
                nonlocal first_perf
                if first_perf is None:
                    first_perf = time.perf_counter()
                    timing.first_audio_generated = first_perf
                    if on_first_audio:
                        on_first_audio(chunk)
                        timing.first_audio_sent = time.perf_counter()
                    else:
                        timing.first_audio_sent = first_perf

            audio = self._raw_synth(normalized, voice_style, on_first_audio=_mark)
            if timing.first_audio_generated == 0.0:
                timing.first_audio_generated = time.perf_counter()
                timing.first_audio_sent = timing.first_audio_generated
            timing.generation_complete = time.perf_counter()
            if self.cache is not None:
                put = self.cache.put
                try:
                    put(
                        normalized,
                        voice_style,
                        audio,
                        target_language=identity["target_language"],
                        pronunciation_version=identity["pronunciation_version"],
                        tts_model_version=identity["tts_model_version"],
                        audio_format=identity["audio_format"],
                        level="full",
                    )
                except TypeError:
                    put(normalized, voice_style, audio)  # type: ignore[misc]

        duration = estimate_wav_duration(audio)
        synth_s = max(timing.full_synthesis_ms() / 1000.0, 1e-6)
        rtf = synth_s / duration if duration > 0 else 0.0
        timing.response_complete = time.perf_counter()
        if hasattr(self.cache, "record_end_to_end") and self.cache is not None:
            self.cache.record_end_to_end(timing.end_to_end_ms())  # type: ignore[attr-defined]
        res = self._result(
            audio=audio,
            text=text,
            normalized=normalized,
            timing=timing,
            v_ok=v_ok,
            v_flags=v_flags,
            cache_hit=cache_hit,
            chunk_count=1,
            meta=meta,
            rtf=rtf,
            cache_level="full" if cache_hit else "",
            units_from_cache=1 if cache_hit else 0,
            units_synthesized=0 if cache_hit else 1,
        )
        res.voice_style = voice_style
        res.audio_duration_sec = duration
        res.audio_format = getattr(self.backend, "audio_format", "wav")
        return res


def preview_tts_text(
    text: str,
    *,
    target_lang: str = "tanglish",
    backend_name: str = "edge_fast",
) -> tuple[str, dict[str, Any]]:
    """Full translate → normalize → phonetic path used by POST /tts (no audio)."""
    pipe = TTSPipeline(
        backend=get_backend(backend_name),
        cache=None,
        skip_llm=True,
    )
    spoken, ok, flags, meta = pipe.preprocess(text, target_lang=target_lang)
    meta = dict(meta)
    meta["validator_ok"] = ok
    meta["validator_flags"] = flags
    return spoken, meta


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pipe = TTSPipeline(skip_llm=True)
    result = pipe.run("Your OTP is 4821", chunked=False)
    print(json.dumps(result.metrics_dict(), indent=2))
    print(f"audio bytes={len(result.audio)}")
