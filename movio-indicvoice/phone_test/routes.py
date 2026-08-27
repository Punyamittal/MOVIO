"""
FastAPI routes for the two-phone local test environment.

Mounted onto the existing movio-indicvoice server — reuses POST/WS TTS pipeline
via server.main._run_tts (no duplicate translation/TTS logic).
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

from phone_test.lan import detect_lan_ips, pick_default_ip
from phone_test.sessions import Role, TestSession, UtteranceEvent, store
from phone_test import stt as stt_mod

logger = logging.getLogger("phone_test.routes")

STATIC_DIR = Path(__file__).resolve().parent / "static"
router = APIRouter(tags=["phone-test"])

# session_id -> role -> WebSocket
_phone_ws: dict[str, dict[str, WebSocket]] = {}
# session_id -> set of dashboard websockets
_dash_ws: dict[str, set[WebSocket]] = {}
_ws_lock = asyncio.Lock()


class CreateSessionBody(BaseModel):
    input_a: str = "en"
    output_a: str = "tanglish"
    input_b: str = "tanglish"
    output_b: str = "en"
    debug: bool = True
    host: str | None = None  # e.g. http://192.168.1.10:8001


class LangBody(BaseModel):
    input_lang: str | None = None
    output_lang: str | None = None


class SimUtteranceBody(BaseModel):
    direction: str = Field(default="A→B", description="A→B or B→A (ASCII A->B also accepted)")
    text: str = Field(..., min_length=1)
    # When set, skip STT and feed this text directly into translate→TTS
    skip_stt: bool = True

    def normalized_direction(self) -> str:
        d = (self.direction or "").strip().replace("->", "→")
        if d in ("A→B", "B→A"):
            return d
        raise ValueError("direction must be A→B or B→A")


def _require_session(session_id: str) -> TestSession:
    s = store.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="Invalid or expired session")
    return s


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
    if a == b:
        return True
    return {a, b} <= {"ta", "tanglish"}


def resolve_utterance_target(
    session: TestSession,
    from_role: Role,
    source_text: str,
) -> str:
    """Pick a target that actually changes language (no EN→EN / TA→TA passthrough)."""
    from normalization.language_translator import detect_language

    speaker = session.phone(from_role)
    partner = session.partner(from_role)
    detected = detect_language(source_text or "")
    for tgt in (
        _norm_lang(speaker.output_lang),
        _norm_lang(partner.input_lang),
        _norm_lang(partner.output_lang),
    ):
        if not tgt or tgt in ("auto", "none", "off"):
            continue
        if _same_lang_family(tgt, detected):
            continue
        return tgt
    if detected in ("en", "unknown", ""):
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
) -> dict[str, Any]:
    """Call existing TTS pipeline (translate + normalize + TTS)."""
    import os

    from config import DEFAULT_TTS_BACKEND, DEFAULT_VOICE_STYLE
    from server.main import _run_tts

    # Prefer edge_fast for phone-test: reliable off the main thread + Tamil voices.
    # Override with PHONE_TEST_TTS_BACKEND=win_sapi|edge_fast|indic_f5
    backend = os.getenv("PHONE_TEST_TTS_BACKEND") or (
        "edge_fast"
        if DEFAULT_TTS_BACKEND in ("win_sapi", "sapi", "turbo", "local")
        else DEFAULT_TTS_BACKEND
    )

    t0 = time.perf_counter()
    result = await _run_tts(
        text,
        DEFAULT_VOICE_STYLE,
        skip_llm=True,
        chunked=False,
        backend=backend,
        target_lang=target_lang,
    )
    ms = (time.perf_counter() - t0) * 1000
    audio_b64 = base64.b64encode(result.audio).decode("ascii")
    fmt = getattr(result, "audio_format", "wav")
    return {
        "audio_b64": audio_b64,
        "audio_format": fmt,
        "source_text": text,
        "translated_text": result.translated_text or result.normalized_text,
        "normalized_text": result.normalized_text,
        "detected_lang": result.detected_lang,
        "target_lang": result.target_lang,
        "translator_engine": result.translator_engine,
        "ttfa_ms": result.metrics_dict().get("ttfa_ms"),
        "full_synthesis_ms": result.metrics_dict().get("full_synthesis_ms"),
        "pipeline_ms": ms,
        "backend": result.backend,
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
) -> UtteranceEvent:
    partner_role: Role = "B" if from_role == "A" else "A"
    direction = f"{from_role}→{partner_role}"
    speaker = session.phone(from_role)
    if input_lang or output_lang:
        _apply_phone_langs(speaker, input_lang=input_lang, output_lang=output_lang)
    stages: list[str] = []
    t_all = time.perf_counter()

    def dbg(msg: str) -> None:
        stages.append(msg)
        if session.debug:
            session.log(f"{direction} {msg}")
            logger.info("[%s] %s %s", session.id, direction, msg)

    dbg("Audio received" if audio else "Text utterance")
    await _broadcast_dashboard(session, host_base)
    await _send_phone(session.id, from_role, {"type": "status", "phase": "processing"})
    await _send_phone(
        session.id,
        partner_role,
        {"type": "status", "phase": "partner_speaking"},
    )

    source_text = (text_override or "").strip()
    stt_ms = 0.0
    err: str | None = None

    try:
        if not source_text:
            if not audio:
                raise RuntimeError("No audio or text provided")
            dbg("STT started")
            source_text, stt_ms = await asyncio.to_thread(
                stt_mod.transcribe_bytes,
                audio,
                mime=mime,
                sample_rate=sample_rate,
                language_hint=speaker.input_lang,
            )
            dbg(f'STT completed: "{source_text}"')
            if not source_text.strip():
                raise RuntimeError("STT returned empty transcript (silence or unclear audio)")

        target_lang = resolve_utterance_target(session, from_role, source_text)
        dbg(f"Translation + TTS started (target={target_lang})")
        pipe = await _run_pipeline_text(source_text, target_lang)
        dbg("Translation completed")
        dbg("TTS completed")

        delivered = await _send_phone(
            session.id,
            partner_role,
            {
                "type": "tts_audio",
                "audio_b64": pipe["audio_b64"],
                "audio_format": pipe["audio_format"],
                "source_text": source_text,
                "translated_text": pipe["translated_text"],
                "normalized_text": pipe["normalized_text"],
                "direction": direction,
                "target_lang": target_lang,
                "latency_hint_ms": pipe["pipeline_ms"] + stt_ms,
            },
        )
        if delivered:
            dbg(f"Audio delivered to PHONE {partner_role}")
        else:
            dbg(f"PHONE {partner_role} not connected — audio not delivered")

        total = time.perf_counter() - t_all
        ev = UtteranceEvent(
            direction=direction,
            source_text=source_text,
            translated_text=pipe["translated_text"],
            normalized_text=pipe["normalized_text"],
            latency_sec=total,
            stt_ms=stt_ms,
            translate_tts_ms=pipe["pipeline_ms"],
            stages=stages,
            error=None,
        )
        session.add_utterance(ev)
        session.log(
            f"{direction} done",
            latency_sec=round(total, 3),
            source=source_text[:120],
            translation=(pipe["translated_text"] or "")[:120],
            target=target_lang,
        )
        await _send_phone(
            session.id,
            from_role,
            {
                "type": "utterance_result",
                "ok": True,
                "source_text": source_text,
                "translated_text": pipe["translated_text"],
                "target_lang": target_lang,
                "latency_sec": round(total, 3),
                "stt_ms": round(stt_ms, 1),
                "pipeline_ms": round(pipe["pipeline_ms"], 1),
            },
        )
        await _send_phone(session.id, from_role, {"type": "status", "phase": "idle"})
        await _send_phone(session.id, partner_role, {"type": "status", "phase": "idle"})
        await _broadcast_dashboard(session, host_base)
        return ev

    except Exception as exc:  # noqa: BLE001
        err = str(exc)
        dbg(f"FAILED: {err}")
        total = time.perf_counter() - t_all
        ev = UtteranceEvent(
            direction=direction,
            source_text=source_text,
            translated_text="",
            normalized_text="",
            latency_sec=total,
            stt_ms=stt_ms,
            translate_tts_ms=0.0,
            stages=stages,
            error=err,
        )
        session.add_utterance(ev)
        await _send_phone(
            session.id,
            from_role,
            {"type": "utterance_result", "ok": False, "error": err},
        )
        await _send_phone(session.id, from_role, {"type": "status", "phase": "idle"})
        await _send_phone(session.id, partner_role, {"type": "status", "phase": "idle"})
        await _broadcast_dashboard(session, host_base)
        logger.exception("Utterance failed %s", direction)
        return ev


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
    """Server-side QR SVG (no CDN) — used by the laptop dashboard."""
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
    # Force readable on-screen size (library defaults to mm units)
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
    """PNG QR — most reliable for <img> tags (esp. inside Next.js iframes)."""
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
    """Local self-test: text → existing translate/TTS → (optional) partner WS."""
    session = _require_session(session_id)
    try:
        direction = body.normalized_direction()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    from_role: Role = "A" if direction.startswith("A") else "B"
    ev = await process_utterance(
        session,
        from_role,
        text_override=body.text if body.skip_stt else None,
    )
    return {"ok": ev.error is None, "event": ev.to_dict(), "state": session.public_state()}


# Phone page AFTER /test/api/* so "api" is never captured as a session id.
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
    session.log(f"PHONE {role_u} CONNECTED")
    await _broadcast_dashboard(session)
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
                # Keep partner complementary so A→B / B→A both translate
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

            if mtype == "audio_utterance":
                # Push-to-talk complete utterance
                b64 = msg.get("audio_b64") or ""
                try:
                    audio = base64.b64decode(b64)
                except Exception as exc:  # noqa: BLE001
                    await ws.send_json({"type": "error", "detail": f"bad audio: {exc}"})
                    continue
                mime = str(msg.get("mime") or "audio/wav")
                sr = int(msg.get("sample_rate") or 16000)
                phone.mic_active = False
                await process_utterance(
                    session,
                    role_u,  # type: ignore[arg-type]
                    audio=audio,
                    mime=mime,
                    sample_rate=sr,
                    input_lang=str(msg["input_lang"]) if msg.get("input_lang") else None,
                    output_lang=str(msg["output_lang"]) if msg.get("output_lang") else None,
                )
                continue

            if mtype == "text_utterance":
                # Debug / fallback without mic
                text = str(msg.get("text") or "").strip()
                if not text:
                    await ws.send_json({"type": "error", "detail": "text required"})
                    continue
                await process_utterance(
                    session,
                    role_u,  # type: ignore[arg-type]
                    text_override=text,
                    input_lang=str(msg["input_lang"]) if msg.get("input_lang") else None,
                    output_lang=str(msg["output_lang"]) if msg.get("output_lang") else None,
                )
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
        session.log(f"PHONE {role_u} DISCONNECTED")
        await _broadcast_dashboard(session)


def mount_phone_test(app) -> None:
    """Attach phone-test routes to the main FastAPI app (once)."""
    if getattr(app.state, "phone_test_mounted", False):
        return
    app.include_router(router)
    app.state.phone_test_mounted = True
    logger.info("Phone-test routes mounted at /test/")
