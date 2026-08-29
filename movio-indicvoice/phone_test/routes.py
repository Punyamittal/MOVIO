"""
FastAPI routes for the two-phone local test environment.

Half-duplex flow:
  IDLE → SPEAKER DETECTION → RECORD → ASR → LANG DETECT →
  TANGlish NORM → TRANSLATE → TARGET TTS → ECHO SUPPRESSION → IDLE

Reuses server.main._run_tts for translate/normalize/TTS (no duplicate engines).
"""
from __future__ import annotations

import asyncio
import base64
import logging
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from phone_test.fsm import ClaimResult, ProcessingState, new_utterance_id
from phone_test.lan import detect_lan_ips, pick_default_ip
from phone_test.lang_detect import detect_language_confident
from phone_test.sessions import Role, TestSession, UtteranceEvent, store
from phone_test import stt as stt_mod
from phone_test import vad as vad_mod

logger = logging.getLogger("phone_test.routes")

STATIC_DIR = Path(__file__).resolve().parent / "static"
router = APIRouter(tags=["phone-test"])

# session_id -> role -> WebSocket
_phone_ws: dict[str, dict[str, WebSocket]] = {}
# session_id -> set of dashboard websockets
_dash_ws: dict[str, set[WebSocket]] = {}
_ws_lock = asyncio.Lock()

# Serialize utterance processing per session (half-duplex)
_session_locks: dict[str, asyncio.Lock] = {}

TRANSLATE_RETRIES = 2
TTS_RETRIES = 2


class CreateSessionBody(BaseModel):
    input_a: str = "en"
    output_a: str = "tanglish"
    input_b: str = "tanglish"
    output_b: str = "en"
    debug: bool = True
    host: str | None = None


class LangBody(BaseModel):
    input_lang: str | None = None
    output_lang: str | None = None


class SimUtteranceBody(BaseModel):
    direction: str = Field(default="A→B", description="A→B or B→A (ASCII A->B also accepted)")
    text: str = Field(..., min_length=1)
    skip_stt: bool = True

    def normalized_direction(self) -> str:
        d = (self.direction or "").strip().replace("->", "→")
        if d in ("A→B", "B→A"):
            return d
        raise ValueError("direction must be A→B or B→A")


class RetryBody(BaseModel):
    utterance_id: str
    stage: str = "auto"  # auto | translate | tts


def _require_session(session_id: str) -> TestSession:
    s = store.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Invalid or expired session")
    return s


def _session_lock(session_id: str) -> asyncio.Lock:
    lock = _session_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_locks[session_id] = lock
    return lock


async def _broadcast_dashboard(session: TestSession, host_base: str | None = None) -> None:
    payload = {"type": "state", "state": session.public_state(host_base)}
    sockets = list(_dash_ws.get(session.id, set()))
    dead: list[WebSocket] = []
    for ws in sockets:
        try:
            await ws.send_json(payload)
        except Exception:  # noqa: BLE001
            dead.append(ws)
    if dead:
        async with _ws_lock:
            live = _dash_ws.get(session.id, set())
            for d in dead:
                live.discard(d)


async def _send_phone(session_id: str, role: Role, message: dict[str, Any]) -> bool:
    ws = _phone_ws.get(session_id, {}).get(role)
    if not ws:
        return False
    try:
        await ws.send_json(message)
        return True
    except Exception:  # noqa: BLE001
        return False


async def _broadcast_fsm(session: TestSession) -> None:
    snap = session.conversation.snapshot() if session.conversation else {}
    for role in ("A", "B"):
        phone = session.phone(role)  # type: ignore[arg-type]
        echo = bool(snap.get(f"echo_suppress_{role.lower()}"))
        phone.echo_suppress = echo
        phone.receiving = echo
        await _send_phone(
            session.id,
            role,  # type: ignore[arg-type]
            {
                "type": "session_state",
                "phase": snap.get("fsm_state", "IDLE"),
                "fsm_state": snap.get("fsm_state", "IDLE"),
                "active_speaker": snap.get("active_speaker"),
                "active_utterance_id": snap.get("active_utterance_id"),
                "echo_suppress": echo,
                "tts_target": snap.get("tts_target"),
                "you_may_speak": snap.get("fsm_state") == "IDLE"
                or snap.get("active_speaker") == role,
            },
        )
    await _broadcast_dashboard(session)


def _norm_lang(code: str | None) -> str:
    c = (code or "").lower().strip()
    if c in ("tamil", "ta-in"):
        return "ta"
    if c in ("english", "en-in"):
        return "en"
    return c


def _same_lang_family(a: str, b: str) -> bool:
    a, b = _norm_lang(a), _norm_lang(b)
    if not a or not b or a == "auto" or b == "auto":
        return False
    if a in ("uncertain", "unknown") or b in ("uncertain", "unknown"):
        return False
    if a == b:
        return True
    return {a, b} <= {"ta", "tanglish"}


def resolve_utterance_target(
    session: TestSession,
    from_role: Role,
    source_text: str,
    *,
    detected: str | None = None,
) -> str:
    """Pick a target that actually changes language (no EN→EN / TA→TA passthrough)."""
    speaker = session.phone(from_role)
    partner = session.partner(from_role)
    det = _norm_lang(detected) if detected else detect_language_confident(source_text or "").language
    for tgt in (
        _norm_lang(speaker.output_lang),
        _norm_lang(partner.input_lang),
        _norm_lang(partner.output_lang),
    ):
        if not tgt or tgt in ("auto", "none", "off", "uncertain", "unknown"):
            continue
        if _same_lang_family(tgt, det):
            continue
        return tgt
    if det in ("en", "unknown", "uncertain", ""):
        return "tanglish"
    return "en"


def _apply_phone_langs(
    phone,
    *,
    input_lang: str | None = None,
    output_lang: str | None = None,
) -> None:
    if input_lang:
        phone.input_lang = _norm_lang(input_lang) or phone.input_lang
    if output_lang:
        phone.output_lang = _norm_lang(output_lang) or phone.output_lang
    if _same_lang_family(phone.input_lang, phone.output_lang):
        if _norm_lang(phone.input_lang) in ("en", "auto"):
            phone.output_lang = "tanglish"
        else:
            phone.output_lang = "en"


async def _run_pipeline_text(
    text: str,
    target_lang: str,
    *,
    skip_translate: bool = False,
) -> dict[str, Any]:
    """Call existing TTS pipeline (translate + normalize + TTS)."""
    import os

    from config import DEFAULT_TTS_BACKEND, DEFAULT_VOICE_STYLE
    from server.main import _run_tts

    backend = os.getenv("PHONE_TEST_TTS_BACKEND") or (
        "edge_fast"
        if DEFAULT_TTS_BACKEND in ("win_sapi", "sapi", "turbo", "local")
        else DEFAULT_TTS_BACKEND
    )

    speak_text = text
    translated_text = text
    normalized_text = text
    detected_lang = ""
    translator_engine = "skipped"
    target = target_lang

    if skip_translate:
        # Still run normalizer + TTS via pipeline with same-language target
        # so Tanglish lexical cleanup still applies when useful.
        pass

    t0 = time.perf_counter()
    result = await _run_tts(
        speak_text,
        DEFAULT_VOICE_STYLE,
        skip_llm=True,
        chunked=False,
        backend=backend,
        target_lang=target_lang if not skip_translate else target_lang,
    )
    ms = (time.perf_counter() - t0) * 1000
    audio_b64 = base64.b64encode(result.audio).decode("ascii")
    fmt = getattr(result, "audio_format", "wav")
    return {
        "audio_b64": audio_b64,
        "audio_format": fmt,
        "source_text": text,
        "translated_text": result.translated_text or result.normalized_text or translated_text,
        "normalized_text": result.normalized_text or normalized_text,
        "detected_lang": result.detected_lang or detected_lang,
        "target_lang": result.target_lang or target,
        "translator_engine": result.translator_engine or translator_engine,
        "ttfa_ms": result.metrics_dict().get("ttfa_ms"),
        "full_synthesis_ms": result.metrics_dict().get("full_synthesis_ms"),
        "pipeline_ms": ms,
        "backend": result.backend,
        "skipped": bool(getattr(result, "translator_engine", "") in ("passthrough", "skip")),
    }


async def _translate_only(text: str, target_lang: str) -> dict[str, Any]:
    """Translate + normalize without TTS (for TTS-retry / error display)."""
    from server.main import _get_pipeline

    def _work() -> dict[str, Any]:
        pipe = _get_pipeline()
        spoken, _ok, flags, meta = pipe.preprocess(text, target_lang=target_lang)
        return {
            "translated_text": meta.get("translated_text") or spoken,
            "normalized_text": spoken,
            "detected_lang": meta.get("detected_lang") or "",
            "target_lang": meta.get("target_lang") or target_lang,
            "translator_engine": meta.get("translator_engine") or "",
            "flags": flags,
        }

    return await asyncio.to_thread(_work)


async def _tts_only(text: str, target_lang: str) -> dict[str, Any]:
    """Synthesize already-translated text."""
    import os

    from config import DEFAULT_TTS_BACKEND, DEFAULT_VOICE_STYLE
    from server.main import _run_tts

    backend = os.getenv("PHONE_TEST_TTS_BACKEND") or (
        "edge_fast"
        if DEFAULT_TTS_BACKEND in ("win_sapi", "sapi", "turbo", "local")
        else DEFAULT_TTS_BACKEND
    )
    t0 = time.perf_counter()
    # Use passthrough path: set target to match so translate is skipped inside preprocess
    result = await _run_tts(
        text,
        DEFAULT_VOICE_STYLE,
        skip_llm=True,
        chunked=False,
        backend=backend,
        target_lang=target_lang,
    )
    ms = (time.perf_counter() - t0) * 1000
    return {
        "audio_b64": base64.b64encode(result.audio).decode("ascii"),
        "audio_format": getattr(result, "audio_format", "wav"),
        "pipeline_ms": ms,
        "normalized_text": result.normalized_text or text,
        "translated_text": result.translated_text or text,
    }


async def process_utterance(
    session: TestSession,
    from_role: Role,
    *,
    audio: bytes | None = None,
    mime: str = "audio/wav",
    sample_rate: int = 16000,
    text_override: str | None = None,
    host_base: str | None = None,
    input_lang: str | None = None,
    output_lang: str | None = None,
    utterance_id: str | None = None,
    start_time: float | None = None,
    allow_without_claim: bool = False,
) -> UtteranceEvent:
    """
    Full half-duplex utterance path with edge-case handling.

    allow_without_claim: used by simulate / retry when floor already held.
    """
    ctrl = session.conversation
    partner_role: Role = "B" if from_role == "A" else "A"
    direction = f"{from_role}→{partner_role}"
    speaker = session.phone(from_role)
    if input_lang or output_lang:
        _apply_phone_langs(speaker, input_lang=input_lang, output_lang=output_lang)

    uid = utterance_id or new_utterance_id()
    t_start = start_time or time.time()
    stages: list[str] = []
    t_all = time.perf_counter()
    stt_ms = 0.0
    source_text = (text_override or "").strip()
    source_language = "uncertain"
    target_language = ""
    normalized_text = ""
    translation = ""
    lang_confidence = 0.0
    lang_uncertain = False
    translation_skipped = False
    retry_count = 0
    duration_sec = 0.0

    def dbg(msg: str) -> None:
        stages.append(msg)
        if session.debug:
            session.log(f"{direction} {msg}", utterance_id=uid)
            logger.info("[%s] %s %s", session.id, direction, msg)

    async def _finish_error(err: str, status: str = "ERROR") -> UtteranceEvent:
        ctrl.fail(err)
        total = time.perf_counter() - t_all
        ev = UtteranceEvent(
            utterance_id=uid,
            speaker_id=from_role,
            direction=direction,
            start_time=t_start,
            end_time=time.time(),
            source_language=source_language,
            target_language=target_language,
            transcript=source_text,
            normalized_text=normalized_text,
            translation=translation,
            processing_status=status,
            lang_confidence=lang_confidence,
            lang_uncertain=lang_uncertain,
            translation_skipped=translation_skipped,
            latency_sec=total,
            stt_ms=stt_ms,
            translate_tts_ms=0.0,
            stages=stages,
            error=err,
            retry_count=retry_count,
        )
        session.add_utterance(ev)
        await _send_phone(
            session.id,
            from_role,
            {
                "type": "utterance_result",
                "ok": False,
                "utterance_id": uid,
                "error": err,
                "transcript": source_text,
                "source_text": source_text,
                "translation": translation,
                "translated_text": translation,
                "processing_status": status,
                "retryable": True,
            },
        )
        await _send_phone(session.id, partner_role, {"type": "status", "phase": "idle"})
        ctrl.recover_idle("error_cleared")
        await _broadcast_fsm(session)
        return ev

    # --- Duplicate guard ---
    if ctrl.is_duplicate(uid):
        dbg(f"DUPLICATE skipped utterance_id={uid}")
        return UtteranceEvent(
            utterance_id=uid,
            speaker_id=from_role,
            direction=direction,
            start_time=t_start,
            end_time=time.time(),
            source_language="",
            target_language="",
            transcript=source_text,
            normalized_text="",
            translation="",
            processing_status="DUPLICATE",
            error="duplicate_utterance",
            stages=stages,
        )

    async with _session_lock(session.id):
        if not allow_without_claim:
            claim = ctrl.try_claim_speaker(from_role, utterance_id=uid)
            if claim == ClaimResult.OVERLAP_REJECTED:
                dbg("OVERLAP: interruption flagged, not mixed")
                await _send_phone(
                    session.id,
                    from_role,
                    {
                        "type": "overlap",
                        "utterance_id": uid,
                        "detail": "Other phone already speaking — your turn was flagged as interruption",
                    },
                )
                await _broadcast_fsm(session)
                return UtteranceEvent(
                    utterance_id=uid,
                    speaker_id=from_role,
                    direction=direction,
                    start_time=t_start,
                    end_time=time.time(),
                    source_language="",
                    target_language="",
                    transcript="",
                    normalized_text="",
                    translation="",
                    processing_status="OVERLAP",
                    interruption=True,
                    stages=stages,
                    error="overlap_rejected",
                )
            if claim == ClaimResult.ECHO_SUPPRESSED:
                dbg("ECHO_SUPPRESSED: mic heard own TTS — ignored")
                await _broadcast_fsm(session)
                return UtteranceEvent(
                    utterance_id=uid,
                    speaker_id=from_role,
                    direction=direction,
                    start_time=t_start,
                    end_time=time.time(),
                    source_language="",
                    target_language="",
                    transcript="",
                    normalized_text="",
                    translation="",
                    processing_status="ECHO_SUPPRESSED",
                    stages=stages,
                    error="echo_suppressed",
                )
            if claim == ClaimResult.BUSY:
                dbg("BUSY: floor held by other turn")
                await _send_phone(
                    session.id,
                    from_role,
                    {"type": "error", "detail": "Partner turn in progress — wait for IDLE", "retryable": True},
                )
                return UtteranceEvent(
                    utterance_id=uid,
                    speaker_id=from_role,
                    direction=direction,
                    start_time=t_start,
                    end_time=time.time(),
                    source_language="",
                    target_language="",
                    transcript="",
                    normalized_text="",
                    translation="",
                    processing_status="BUSY",
                    stages=stages,
                    error="busy",
                )
            if claim == ClaimResult.BARGE_IN:
                dbg("BARGE_IN: stopping partner TTS")
                await _send_phone(
                    session.id,
                    partner_role,
                    {"type": "stop_tts", "reason": "barge_in", "utterance_id": ctrl.interruption_of},
                )

        if not ctrl.begin_processing(uid, from_role):
            dbg("DUPLICATE at begin_processing")
            return await _finish_error("duplicate_utterance", "DUPLICATE")

        dbg("Audio received" if audio and not source_text else "Text utterance")
        await _broadcast_fsm(session)
        await _send_phone(session.id, from_role, {"type": "status", "phase": "processing", "fsm_state": "PROCESSING"})
        await _send_phone(
            session.id,
            partner_role,
            {"type": "status", "phase": "partner_speaking", "fsm_state": "PROCESSING"},
        )

        try:
            # --- VAD / noise gate (audio path) ---
            if not source_text:
                if not audio:
                    raise RuntimeError("No audio or text provided")
                gate = vad_mod.gate_audio(audio, mime=mime, sample_rate=sample_rate)
                duration_sec = gate.duration_sec
                dbg(
                    f"VAD gate accepted={gate.accepted} reason={gate.reason} "
                    f"dur={gate.duration_sec:.2f}s rms={gate.rms:.0f}"
                )
                if not gate.accepted:
                    raise RuntimeError(f"Speech not accepted ({gate.reason})")

                dbg("STT started")
                source_text, stt_ms = await asyncio.to_thread(
                    stt_mod.transcribe_bytes,
                    audio,
                    mime=mime,
                    sample_rate=sample_rate,
                    language_hint=speaker.input_lang,
                )
                dbg(f'STT completed: "{source_text}"')
                tg = vad_mod.gate_transcript(source_text, duration_sec=duration_sec)
                if not tg.accepted:
                    raise RuntimeError(f"Transcript rejected ({tg.reason})")

            if ctrl.should_cancel():
                dbg("Cancelled after ASR (barge-in)")
                ctrl.recover_idle("cancelled_after_asr")
                await _broadcast_fsm(session)
                return UtteranceEvent(
                    utterance_id=uid,
                    speaker_id=from_role,
                    direction=direction,
                    start_time=t_start,
                    end_time=time.time(),
                    source_language="",
                    target_language="",
                    transcript=source_text,
                    normalized_text="",
                    translation="",
                    processing_status="BARGE_IN",
                    stages=stages,
                    error="cancelled",
                )

            # --- Language detection ---
            lang = detect_language_confident(source_text)
            source_language = lang.language
            lang_confidence = lang.confidence
            lang_uncertain = lang.uncertain
            dbg(f"LANG {lang.label} confidence={lang.confidence}")

            if lang.uncertain:
                dbg("LOW confidence — marking UNCERTAIN, skipping auto-translation")
                target_language = resolve_utterance_target(
                    session, from_role, source_text, detected="en" if speaker.input_lang == "en" else speaker.output_lang
                )
                # Preserve ASR text; do not confidently mistranslate
                translation_skipped = True
                translation = ""
                normalized_text = source_text
                total = time.perf_counter() - t_all
                ev = UtteranceEvent(
                    utterance_id=uid,
                    speaker_id=from_role,
                    direction=direction,
                    start_time=t_start,
                    end_time=time.time(),
                    source_language="UNCERTAIN",
                    target_language=target_language,
                    transcript=source_text,
                    normalized_text=normalized_text,
                    translation="",
                    processing_status="ERROR",
                    lang_confidence=lang_confidence,
                    lang_uncertain=True,
                    translation_skipped=True,
                    latency_sec=total,
                    stt_ms=stt_ms,
                    stages=stages,
                    error="language_uncertain",
                )
                session.add_utterance(ev)
                ctrl.mark_processed(uid)
                await _send_phone(
                    session.id,
                    from_role,
                    {
                        "type": "utterance_result",
                        "ok": False,
                        "utterance_id": uid,
                        "error": "Language UNCERTAIN — translation withheld",
                        "transcript": source_text,
                        "source_text": source_text,
                        "processing_status": "ERROR",
                        "lang_uncertain": True,
                        "retryable": True,
                    },
                )
                # Still show transcript to partner as text (no TTS loop)
                await _send_phone(
                    session.id,
                    partner_role,
                    {
                        "type": "utterance_text",
                        "utterance_id": uid,
                        "transcript": source_text,
                        "detail": "Partner speech language uncertain — no TTS",
                    },
                )
                ctrl.recover_idle("uncertain_lang")
                await _broadcast_fsm(session)
                return ev

            target_language = resolve_utterance_target(
                session, from_role, source_text, detected=source_language
            )

            # --- Same language → skip translation ---
            if _same_lang_family(source_language, target_language):
                dbg(f"Same language family {source_language}≈{target_language} — skip translation")
                translation_skipped = True
                translation = source_text
                normalized_text = source_text
                # Still deliver TTS of original so partner hears it
                ctrl.begin_translating()
                await _broadcast_fsm(session)
                pipe = None
                last_tts_err = None
                for attempt in range(TTS_RETRIES + 1):
                    try:
                        if ctrl.should_cancel():
                            raise RuntimeError("cancelled")
                        pipe = await _run_pipeline_text(
                            source_text, target_language, skip_translate=True
                        )
                        translation = pipe["translated_text"] or source_text
                        normalized_text = pipe["normalized_text"] or source_text
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_tts_err = exc
                        retry_count += 1
                        dbg(f"TTS retry {attempt}: {exc}")
                if pipe is None:
                    dbg(f"TTS failed — showing text only: {last_tts_err}")
                    await _send_phone(
                        session.id,
                        partner_role,
                        {
                            "type": "tts_failed",
                            "utterance_id": uid,
                            "translated_text": translation or source_text,
                            "error": str(last_tts_err),
                            "retryable": True,
                        },
                    )
                    ctrl.mark_processed(uid)
                    ctrl.recover_idle("tts_failed_same_lang")
                    await _broadcast_fsm(session)
                    total = time.perf_counter() - t_all
                    ev = UtteranceEvent(
                        utterance_id=uid,
                        speaker_id=from_role,
                        direction=direction,
                        start_time=t_start,
                        end_time=time.time(),
                        source_language=source_language,
                        target_language=target_language,
                        transcript=source_text,
                        normalized_text=normalized_text,
                        translation=translation or source_text,
                        processing_status="ERROR",
                        translation_skipped=True,
                        lang_confidence=lang_confidence,
                        latency_sec=total,
                        stt_ms=stt_ms,
                        stages=stages,
                        error=f"tts_failed:{last_tts_err}",
                        retry_count=retry_count,
                    )
                    session.add_utterance(ev)
                    return ev
            else:
                # --- Translate + TTS with retries ---
                ctrl.begin_translating()
                await _broadcast_fsm(session)
                dbg(f"Translation + TTS started (target={target_language})")
                pipe = None
                last_err: Exception | None = None
                for attempt in range(TRANSLATE_RETRIES + 1):
                    try:
                        if ctrl.should_cancel():
                            raise RuntimeError("cancelled")
                        pipe = await _run_pipeline_text(source_text, target_language)
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_err = exc
                        retry_count += 1
                        dbg(f"Translate/TTS retry {attempt}: {exc}")
                        await asyncio.sleep(0.35 * (attempt + 1))

                if pipe is None:
                    # Preserve ASR; surface error; keep retryable
                    dbg(f"Translation failure — preserving ASR: {last_err}")
                    try:
                        meta = await _translate_only(source_text, target_language)
                        translation = meta.get("translated_text") or ""
                        normalized_text = meta.get("normalized_text") or source_text
                    except Exception:  # noqa: BLE001
                        translation = ""
                        normalized_text = source_text
                    total = time.perf_counter() - t_all
                    ev = UtteranceEvent(
                        utterance_id=uid,
                        speaker_id=from_role,
                        direction=direction,
                        start_time=t_start,
                        end_time=time.time(),
                        source_language=source_language,
                        target_language=target_language,
                        transcript=source_text,
                        normalized_text=normalized_text,
                        translation=translation,
                        processing_status="ERROR",
                        lang_confidence=lang_confidence,
                        latency_sec=total,
                        stt_ms=stt_ms,
                        stages=stages,
                        error=f"translation_failed:{last_err}",
                        retry_count=retry_count,
                    )
                    session.add_utterance(ev)
                    await _send_phone(
                        session.id,
                        from_role,
                        {
                            "type": "utterance_result",
                            "ok": False,
                            "utterance_id": uid,
                            "error": str(last_err),
                            "transcript": source_text,
                            "source_text": source_text,
                            "translation": translation,
                            "processing_status": "ERROR",
                            "retryable": True,
                        },
                    )
                    ctrl.recover_idle("translate_failed")
                    await _broadcast_fsm(session)
                    return ev

                translation = pipe["translated_text"]
                normalized_text = pipe["normalized_text"]
                dbg("Translation completed (Tanglish norm via pipeline)")
                dbg("TTS completed")

            if ctrl.should_cancel() or ctrl.is_replay_blocked(uid):
                dbg("TTS delivery cancelled / stale after disconnect")
                ctrl.mark_processed(uid)
                ctrl.recover_idle("stale_or_cancelled")
                await _broadcast_fsm(session)
                return UtteranceEvent(
                    utterance_id=uid,
                    speaker_id=from_role,
                    direction=direction,
                    start_time=t_start,
                    end_time=time.time(),
                    source_language=source_language,
                    target_language=target_language,
                    transcript=source_text,
                    normalized_text=normalized_text,
                    translation=translation,
                    processing_status="CANCELLED",
                    stages=stages,
                    error="cancelled_or_stale",
                )

            # --- Deliver TTS only to receiving phone ---
            ctrl.begin_tts(partner_role, uid)
            partner_phone = session.phone(partner_role)
            partner_phone.echo_suppress = True
            partner_phone.receiving = True
            await _broadcast_fsm(session)

            delivered = await _send_phone(
                session.id,
                partner_role,
                {
                    "type": "tts_audio",
                    "utterance_id": uid,
                    "audio_b64": pipe["audio_b64"],
                    "audio_format": pipe["audio_format"],
                    "source_text": source_text,
                    "transcript": source_text,
                    "translated_text": translation,
                    "normalized_text": normalized_text,
                    "direction": direction,
                    "target_lang": target_language,
                    "source_language": source_language,
                    "echo_suppress": True,
                    "latency_hint_ms": pipe["pipeline_ms"] + stt_ms,
                },
            )
            if delivered:
                dbg(f"Audio delivered to PHONE {partner_role} (echo_suppress=ON)")
            else:
                dbg(f"PHONE {partner_role} not connected — audio not delivered")
                # No receiver: show text on speaker side and return to idle
                partner_phone.echo_suppress = False
                partner_phone.receiving = False
                ctrl.mark_processed(uid)
                ctrl.recover_idle("partner_offline")

            total = time.perf_counter() - t_all
            ev = UtteranceEvent(
                utterance_id=uid,
                speaker_id=from_role,
                direction=direction,
                start_time=t_start,
                end_time=time.time(),
                source_language=source_language,
                target_language=target_language,
                transcript=source_text,
                normalized_text=normalized_text,
                translation=translation,
                processing_status="TTS_A" if partner_role == "A" else "TTS_B",
                lang_confidence=lang_confidence,
                lang_uncertain=lang_uncertain,
                translation_skipped=translation_skipped,
                latency_sec=total,
                stt_ms=stt_ms,
                translate_tts_ms=pipe["pipeline_ms"],
                stages=stages,
                retry_count=retry_count,
            )
            session.add_utterance(ev)
            session.log(
                f"{direction} done",
                utterance_id=uid,
                latency_sec=round(total, 3),
                source=source_text[:120],
                translation=(translation or "")[:120],
                target=target_language,
            )
            await _send_phone(
                session.id,
                from_role,
                {
                    "type": "utterance_result",
                    "ok": True,
                    "utterance_id": uid,
                    "source_text": source_text,
                    "transcript": source_text,
                    "translated_text": translation,
                    "translation": translation,
                    "normalized_text": normalized_text,
                    "source_language": source_language,
                    "target_lang": target_language,
                    "target_language": target_language,
                    "processing_status": ev.processing_status,
                    "latency_sec": round(total, 3),
                    "stt_ms": round(stt_ms, 1),
                    "pipeline_ms": round(pipe["pipeline_ms"], 1),
                    "translation_skipped": translation_skipped,
                },
            )
            # Speaker returns to idle UI; receiver stays in TTS until tts_done
            await _send_phone(
                session.id,
                from_role,
                {"type": "status", "phase": "idle", "fsm_state": ctrl.state.value},
            )
            if not delivered:
                await _broadcast_fsm(session)
            else:
                await _broadcast_dashboard(session)
            return ev

        except Exception as exc:  # noqa: BLE001
            err = str(exc)
            dbg(f"FAILED: {err}")
            logger.exception("Utterance failed %s", direction)
            return await _finish_error(err)


async def retry_utterance(session: TestSession, utterance_id: str, stage: str = "auto") -> UtteranceEvent | None:
    """Retry translate and/or TTS for a failed utterance without losing ASR text."""
    ev = session.find_utterance(utterance_id)
    if not ev or not ev.transcript:
        return None
    if session.conversation.is_duplicate(utterance_id) and ev.processing_status not in (
        "ERROR",
        "CANCELLED",
    ):
        # Allow retry of failed ones by removing from processed set
        pass
    session.conversation.processed_ids.discard(utterance_id)
    session.log(f"RETRY utterance {utterance_id} stage={stage}")

    from_role: Role = ev.speaker_id
    # Re-run from text (preserve ASR)
    return await process_utterance(
        session,
        from_role,
        text_override=ev.transcript,
        utterance_id=new_utterance_id(),  # new id to avoid duplicate loop; link via stages
        allow_without_claim=False,
        start_time=time.time(),
    )


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


@router.get("/test/")
@router.get("/test")
async def test_dashboard():
    path = STATIC_DIR / "dashboard.html"
    return FileResponse(path, media_type="text/html")


@router.get("/test/api/lan")
async def api_lan():
    ips = detect_lan_ips()
    return {
        "ips": ips,
        "default": pick_default_ip(ips),
        "note": "Phones must use a LAN IP, not localhost.",
    }


@router.get("/test/api/stt-status")
async def api_stt_status():
    return stt_mod.status()


@router.get("/test/api/qr.svg")
async def api_qr_svg(data: str = Query(..., min_length=1, max_length=2048)):
    try:
        import qrcode
        from qrcode.image.svg import SvgPathImage
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail="qrcode package missing — pip install qrcode[pil]",
        ) from exc

    img = qrcode.make(data, image_factory=SvgPathImage, box_size=10, border=2)
    raw = img.to_string()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    import re

    raw = re.sub(r'width="[^"]*"', 'width="200"', raw, count=1)
    raw = re.sub(r'height="[^"]*"', 'height="200"', raw, count=1)
    if 'fill="' not in raw:
        raw = raw.replace("<path ", '<path fill="#000000" ', 1)
    return Response(
        content=raw,
        media_type="image/svg+xml; charset=utf-8",
        headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"},
    )


@router.get("/test/api/qr.png")
async def api_qr_png(data: str = Query(..., min_length=1, max_length=2048)):
    try:
        import io

        import qrcode
    except ImportError as exc:
        raise HTTPException(
            status_code=500,
            detail="qrcode package missing — pip install qrcode[pil]",
        ) from exc

    qr = qrcode.QRCode(version=None, box_size=8, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(
        content=buf.getvalue(),
        media_type="image/png",
        headers={"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"},
    )


@router.post("/test/api/session")
async def api_create_session(body: CreateSessionBody):
    session = store.create(
        input_a=body.input_a,
        output_a=body.output_a,
        input_b=body.input_b,
        output_b=body.output_b,
        debug=body.debug,
    )
    host = (body.host or "").rstrip("/") or None
    return session.public_state(host)


@router.get("/test/api/session/active")
async def api_active_session(host: str | None = None):
    session = store.active()
    if not session:
        return JSONResponse({"session": None})
    return {"session": session.public_state(host)}


@router.get("/test/api/session/{session_id}")
async def api_get_session(session_id: str, host: str | None = None):
    session = _require_session(session_id)
    return session.public_state(host)


@router.delete("/test/api/session/{session_id}")
async def api_end_session(session_id: str):
    session = store.get(session_id)
    if session:
        session.log("SESSION ENDED")
        for role in ("A", "B"):
            await _send_phone(session_id, role, {"type": "session_ended"})  # type: ignore[arg-type]
    ok = store.end(session_id)
    async with _ws_lock:
        _phone_ws.pop(session_id, None)
        _dash_ws.pop(session_id, None)
    _session_locks.pop(session_id, None)
    return {"ok": ok}


@router.patch("/test/api/session/{session_id}/{role}/lang")
async def api_set_lang(session_id: str, role: str, body: LangBody):
    role_u = role.upper()
    if role_u not in ("A", "B"):
        raise HTTPException(status_code=400, detail="Role must be A or B")
    session = _require_session(session_id)
    phone = session.phone(role_u)  # type: ignore[arg-type]
    _apply_phone_langs(phone, input_lang=body.input_lang, output_lang=body.output_lang)
    session.log(f"PHONE {role_u} languages set", input=phone.input_lang, output=phone.output_lang)
    await _broadcast_dashboard(session)
    await _send_phone(
        session_id,
        role_u,  # type: ignore[arg-type]
        {
            "type": "lang",
            "input_lang": phone.input_lang,
            "output_lang": phone.output_lang,
        },
    )
    return session.public_state()


@router.post("/test/api/session/{session_id}/simulate")
async def api_simulate(session_id: str, body: SimUtteranceBody):
    session = _require_session(session_id)
    try:
        direction = body.normalized_direction()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    from_role: Role = "A" if direction.startswith("A") else "B"
    # Wait until idle so half-duplex simulate A then B works
    for _ in range(40):
        if session.conversation.state == ProcessingState.IDLE:
            break
        await asyncio.sleep(0.25)
    ev = await process_utterance(
        session,
        from_role,
        text_override=body.text if body.skip_stt else None,
        utterance_id=new_utterance_id(),
    )
    # Simulate has no real phone to send tts_done — force idle
    if session.conversation.state in (ProcessingState.TTS_A, ProcessingState.TTS_B):
        session.conversation.tts_finished(ev.utterance_id)
        await _broadcast_fsm(session)
    return {"ok": ev.error is None, "event": ev.to_dict(), "state": session.public_state()}


@router.post("/test/api/session/{session_id}/retry")
async def api_retry(session_id: str, body: RetryBody):
    session = _require_session(session_id)
    ev = await retry_utterance(session, body.utterance_id, body.stage)
    if not ev:
        raise HTTPException(status_code=404, detail="utterance not found")
    if session.conversation.state in (ProcessingState.TTS_A, ProcessingState.TTS_B):
        # If partner offline, clear TTS wait
        partner = "B" if ev.speaker_id == "A" else "A"
        if not session.phone(partner).connected:  # type: ignore[arg-type]
            session.conversation.tts_finished(ev.utterance_id)
            await _broadcast_fsm(session)
    return {"ok": ev.error is None, "event": ev.to_dict(), "state": session.public_state()}


@router.get("/test/{session_id}/{role}")
async def test_phone_page(session_id: str, role: str, token: str = Query("")):
    role_u = role.upper()
    if role_u not in ("A", "B"):
        raise HTTPException(status_code=400, detail="Role must be A or B")
    if session_id.lower() == "api":
        raise HTTPException(status_code=404, detail="Not found")
    session = store.get(session_id)
    if not session:
        return HTMLResponse(
            "<h1>Invalid or expired session</h1>"
            "<p>Scan a fresh QR code from the laptop dashboard.</p>",
            status_code=404,
        )
    if not session.validate_token(role_u, token):  # type: ignore[arg-type]
        return HTMLResponse(
            "<h1>Invalid pairing token</h1>"
            "<p>This QR belongs to the other phone, or the link is incomplete.</p>",
            status_code=403,
        )
    path = STATIC_DIR / "phone.html"
    return FileResponse(path, media_type="text/html")


# ---------------------------------------------------------------------------
# WebSockets
# ---------------------------------------------------------------------------


@router.websocket("/test/ws/dashboard/{session_id}")
async def ws_dashboard(ws: WebSocket, session_id: str):
    session = store.get(session_id)
    if not session:
        await ws.close(code=4404)
        return
    await ws.accept()
    async with _ws_lock:
        _dash_ws.setdefault(session_id, set()).add(ws)
    try:
        await ws.send_json({"type": "state", "state": session.public_state()})
        while True:
            msg = await ws.receive_json()
            mtype = msg.get("type")
            if mtype == "ping":
                await ws.send_json({"type": "pong"})
            elif mtype == "refresh":
                await ws.send_json({"type": "state", "state": session.public_state()})
            elif mtype == "end":
                await api_end_session(session_id)
                break
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("Dashboard WS error")
    finally:
        async with _ws_lock:
            _dash_ws.get(session_id, set()).discard(ws)


@router.websocket("/test/ws/phone/{session_id}/{role}")
async def ws_phone(ws: WebSocket, session_id: str, role: str, token: str = Query("")):
    role_u = role.upper()
    if role_u not in ("A", "B"):
        await ws.close(code=4400)
        return
    session = store.get(session_id)
    if not session:
        await ws.close(code=4404)
        return
    if not session.validate_token(role_u, token):  # type: ignore[arg-type]
        await ws.close(code=4403)
        return

    await ws.accept()
    phone = session.phone(role_u)  # type: ignore[arg-type]
    was_connected = phone.connected

    async with _ws_lock:
        bucket = _phone_ws.setdefault(session_id, {})
        old = bucket.get(role_u)
        if old is not None and old is not ws:
            try:
                await old.send_json(
                    {
                        "type": "replaced",
                        "detail": "Another connection took over this phone role",
                    }
                )
                await old.close(code=4000)
            except Exception:  # noqa: BLE001
                pass
        bucket[role_u] = ws

    phone.connected = True
    phone.last_seen = time.time()
    if was_connected:
        session.conversation.on_reconnect(role_u)  # type: ignore[arg-type]
        session.log(f"PHONE {role_u} RECONNECTED")
    else:
        session.log(f"PHONE {role_u} CONNECTED")
    await _broadcast_fsm(session)
    await ws.send_json(
        {
            "type": "hello",
            "role": role_u,
            "session_id": session_id,
            "input_lang": phone.input_lang,
            "output_lang": phone.output_lang,
            "partner": "B" if role_u == "A" else "A",
            "partner_connected": session.partner(role_u).connected,  # type: ignore[arg-type]
            "stt": stt_mod.status(),
            "fsm": session.conversation.snapshot(),
            "mode": "half_duplex_vad",
        }
    )

    try:
        while True:
            msg = await ws.receive_json()
            phone.last_seen = time.time()
            mtype = msg.get("type")

            if mtype == "ping":
                await ws.send_json({"type": "pong"})
                continue

            if mtype == "lang":
                _apply_phone_langs(
                    phone,
                    input_lang=str(msg["input_lang"]) if msg.get("input_lang") else None,
                    output_lang=str(msg["output_lang"]) if msg.get("output_lang") else None,
                )
                session.log(
                    f"PHONE {role_u} languages",
                    input=phone.input_lang,
                    output=phone.output_lang,
                )
                partner = session.partner(role_u)  # type: ignore[arg-type]
                partner.input_lang = phone.output_lang
                partner.output_lang = (
                    "en" if _norm_lang(phone.output_lang) in ("ta", "tanglish") else "tanglish"
                )
                await _send_phone(
                    session_id,
                    role_u,  # type: ignore[arg-type]
                    {
                        "type": "lang",
                        "input_lang": phone.input_lang,
                        "output_lang": phone.output_lang,
                    },
                )
                await _send_phone(
                    session_id,
                    partner.role,
                    {
                        "type": "lang",
                        "input_lang": partner.input_lang,
                        "output_lang": partner.output_lang,
                    },
                )
                await _broadcast_dashboard(session)
                continue

            if mtype == "mic":
                phone.mic_active = bool(msg.get("active"))
                await _broadcast_dashboard(session)
                continue

            if mtype == "speech_start":
                uid = str(msg.get("utterance_id") or new_utterance_id())
                is_barge = bool(msg.get("barge_in"))
                claim = session.conversation.try_claim_speaker(
                    role_u,  # type: ignore[arg-type]
                    utterance_id=uid,
                    is_barge_in=is_barge,
                )
                if claim == ClaimResult.BARGE_IN:
                    partner = "B" if role_u == "A" else "A"
                    await _send_phone(
                        session_id,
                        partner,  # type: ignore[arg-type]
                        {"type": "stop_tts", "reason": "barge_in", "by": role_u},
                    )
                await ws.send_json(
                    {
                        "type": "speech_ack",
                        "utterance_id": uid,
                        "claim": claim.value,
                        "fsm_state": session.conversation.state.value,
                    }
                )
                if claim == ClaimResult.OVERLAP_REJECTED:
                    await ws.send_json(
                        {
                            "type": "overlap",
                            "utterance_id": uid,
                            "detail": "Other phone already speaking",
                        }
                    )
                phone.mic_active = claim in (ClaimResult.ACCEPTED, ClaimResult.BARGE_IN)
                await _broadcast_fsm(session)
                continue

            if mtype == "barge_in":
                uid = str(msg.get("utterance_id") or new_utterance_id())
                claim = session.conversation.try_claim_speaker(
                    role_u,  # type: ignore[arg-type]
                    utterance_id=uid,
                    is_barge_in=True,
                )
                partner = "B" if role_u == "A" else "A"
                await _send_phone(
                    session_id,
                    partner,  # type: ignore[arg-type]
                    {"type": "stop_tts", "reason": "barge_in", "by": role_u},
                )
                await ws.send_json({"type": "speech_ack", "utterance_id": uid, "claim": claim.value})
                await _broadcast_fsm(session)
                continue

            if mtype == "tts_started":
                uid = str(msg.get("utterance_id") or "")
                phone.receiving = True
                phone.echo_suppress = True
                session.log(f"PHONE {role_u} TTS started", utterance_id=uid)
                await _broadcast_dashboard(session)
                continue

            if mtype == "tts_done":
                uid = str(msg.get("utterance_id") or "") or None
                phone.receiving = False
                phone.echo_suppress = False
                session.conversation.tts_finished(uid)
                session.log(f"PHONE {role_u} TTS done → IDLE", utterance_id=uid)
                await _broadcast_fsm(session)
                continue

            if mtype == "tts_failed":
                uid = str(msg.get("utterance_id") or "")
                phone.receiving = False
                phone.echo_suppress = False
                session.log(f"PHONE {role_u} TTS playback failed", utterance_id=uid)
                # Keep translated text available; free the floor
                session.conversation.tts_finished(uid or None)
                await _broadcast_fsm(session)
                continue

            if mtype == "audio_utterance":
                b64 = msg.get("audio_b64") or ""
                try:
                    audio = base64.b64decode(b64)
                except Exception as exc:  # noqa: BLE001
                    await ws.send_json({"type": "error", "detail": f"bad audio: {exc}"})
                    continue
                mime = str(msg.get("mime") or "audio/wav")
                sr = int(msg.get("sample_rate") or 16000)
                uid = str(msg.get("utterance_id") or new_utterance_id())
                start_t = float(msg.get("start_time") or time.time())
                phone.mic_active = False
                await process_utterance(
                    session,
                    role_u,  # type: ignore[arg-type]
                    audio=audio,
                    mime=mime,
                    sample_rate=sr,
                    utterance_id=uid,
                    start_time=start_t,
                    input_lang=str(msg["input_lang"]) if msg.get("input_lang") else None,
                    output_lang=str(msg["output_lang"]) if msg.get("output_lang") else None,
                )
                continue

            if mtype == "text_utterance":
                text = str(msg.get("text") or "").strip()
                if not text:
                    await ws.send_json({"type": "error", "detail": "text required"})
                    continue
                uid = str(msg.get("utterance_id") or new_utterance_id())
                await process_utterance(
                    session,
                    role_u,  # type: ignore[arg-type]
                    text_override=text,
                    utterance_id=uid,
                    input_lang=str(msg["input_lang"]) if msg.get("input_lang") else None,
                    output_lang=str(msg["output_lang"]) if msg.get("output_lang") else None,
                )
                continue

            if mtype == "retry_utterance":
                uid = str(msg.get("utterance_id") or "")
                if not uid:
                    await ws.send_json({"type": "error", "detail": "utterance_id required"})
                    continue
                await retry_utterance(session, uid, str(msg.get("stage") or "auto"))
                continue

    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        logger.exception("Phone WS error role=%s", role_u)
    finally:
        async with _ws_lock:
            bucket = _phone_ws.get(session_id, {})
            if bucket.get(role_u) is ws:
                bucket.pop(role_u, None)
        phone.connected = False
        phone.mic_active = False
        phone.receiving = False
        phone.echo_suppress = False
        # Block stale TTS replay for in-flight utterance
        if session.conversation.active_utterance_id:
            session.conversation.block_stale_replay(session.conversation.active_utterance_id)
        session.conversation.on_disconnect(role_u)  # type: ignore[arg-type]
        session.log(f"PHONE {role_u} DISCONNECTED")
        await _broadcast_fsm(session)


def mount_phone_test(app) -> None:
    """Attach phone-test routes to the main FastAPI app (once)."""
    if getattr(app.state, "phone_test_mounted", False):
        return
    app.include_router(router)
    app.state.phone_test_mounted = True
    logger.info("Phone-test routes mounted at /test/")
