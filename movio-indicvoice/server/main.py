"""
FastAPI TTS server for movio-indicvoice.

Phase 1: POST /tts (synchronous single request)
Phase 2: WS /tts/stream + cache (clause chunk streaming for low TTFA)
Phase 3: request queue with backpressure

Default backend is edge_fast (lightweight neural voices) for low TTFA.
No fine-tuning — this repo is off-the-shelf / prompt-only.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    CACHE_ENABLED,
    CACHE_MAX_ENTRIES,
    CACHE_PRIME_BACKGROUND,
    DEFAULT_TARGET_LANG,
    DEFAULT_TTS_BACKEND,
    DEFAULT_VOICE_STYLE,
    LOG_LEVEL,
    QUEUE_ENABLED,
    QUEUE_MAX_SIZE,
    QUEUE_REQUEST_TIMEOUT_SEC,
    QUEUE_WORKER_COUNT,
    SERVER_HOST,
    SERVER_PORT,
)
from server.cache import AudioCache  # noqa: E402
from server.pipeline import TTSPipeline, get_backend, pronunciation_version  # noqa: E402
from server.queue import QueueFullError, RequestTimeout, TTSQueue  # noqa: E402
from server.websocket_stream import concat_wavs  # noqa: E402

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("server.main")

cache: AudioCache | None = AudioCache(CACHE_MAX_ENTRIES) if CACHE_ENABLED else None
_pipelines: dict[str, TTSPipeline] = {}
tts_queue: TTSQueue | None = None


def _normalize_backend(name: str | None) -> str:
    n = (name or DEFAULT_TTS_BACKEND).lower().strip()
    if n in ("sapi", "turbo", "local", "win_sapi"):
        return "win_sapi"
    if n in ("f5", "indic_f5"):
        return "indic_f5"
    if n in ("edge", "fast", "edge_fast", "parler", "indic_parler", "quality"):
        # Legacy "parler/quality" aliases map to edge_fast (Parler removed)
        return "edge_fast"
    return n or DEFAULT_TTS_BACKEND


def _is_instant_backend(name: str | None) -> bool:
    return _normalize_backend(name) in ("win_sapi", "edge_fast")


def _get_pipeline(backend: str | None = None) -> TTSPipeline:
    key = _normalize_backend(backend)
    if key not in _pipelines:
        logger.info("Creating TTS pipeline backend=%s", key)
        _pipelines[key] = TTSPipeline(backend=get_backend(key), cache=cache, skip_llm=True)
    return _pipelines[key]


def _sync_worker(
    text: str,
    voice_style: str,
    skip_llm: bool = True,
    chunked: bool = True,
    backend: str | None = None,
    target_lang: str | None = None,
):
    from config import TRANSLATOR_OLLAMA_ENABLED

    key = _normalize_backend(backend)
    # Instant backends historically forced single-shot; layered cache (full →
    # clause → template) still applies inside pipeline.run when cache is on.
    if key in ("edge_fast", "win_sapi"):
        chunked = False
    # Never call Ollama polish on the TTS path unless explicitly enabled.
    if not TRANSLATOR_OLLAMA_ENABLED:
        skip_llm = True
    pipe = _get_pipeline(key)
    prev = pipe.skip_llm
    prev_lang = pipe.target_lang
    pipe.skip_llm = skip_llm
    pipe.target_lang = target_lang or DEFAULT_TARGET_LANG
    try:
        return pipe.run(text, voice_style, chunked=chunked, target_lang=pipe.target_lang)
    finally:
        pipe.skip_llm = prev
        pipe.target_lang = prev_lang


@asynccontextmanager
async def lifespan(app: FastAPI):
    global tts_queue
    default_pipe = _get_pipeline(DEFAULT_TTS_BACKEND)
    try:
        logger.info("Warming default TTS backend (%s)...", DEFAULT_TTS_BACKEND)
        await asyncio.to_thread(default_pipe.backend.warmup)
        logger.info(
            "TTS backend ready name=%s device=%s",
            getattr(default_pipe.backend, "name", "?"),
            getattr(default_pipe.backend, "device", "?"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("TTS warmup skipped: %s", exc)

    # Warm Edge neural pool in background so Neural·Edge hits <500ms TTFA
    try:
        if _normalize_backend(DEFAULT_TTS_BACKEND) != "edge_fast":
            logger.info("Warming edge_fast pool for low-latency neural path…")
            await asyncio.to_thread(_get_pipeline("edge_fast").backend.warmup)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Edge warmup skipped: %s", exc)

    # Preload Tanglish translation model so the first live utterance does not
    # pay the ~40s cold-load cost on a laptop GPU.
    try:
        from config import TRANSLATOR_OLLAMA_ENABLED
        from normalization.tanglish_translator import reload_gold, warmup as tanglish_warmup

        reload_gold()
        if cache is not None:
            cache.clear()
            logger.info("Cleared audio cache after gold reload")
        if TRANSLATOR_OLLAMA_ENABLED:
            logger.info("Warming Tanglish translation model…")
            await asyncio.to_thread(tanglish_warmup)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tanglish warmup skipped: %s", exc)

    # Lightweight demo prime (edge path is seconds, not minutes)
    try:
        logger.info("Priming demo phrase cache…")
        await asyncio.to_thread(
            _sync_worker,
            "Unga driver 5 minutes la vandhuruvaanga. OTP 4821 share pannunga.",
            DEFAULT_VOICE_STYLE,
            True,
            False,
            DEFAULT_TTS_BACKEND,
            DEFAULT_TARGET_LANG,
        )
        # Also prime Edge neural for the same demo phrase
        await asyncio.to_thread(
            _sync_worker,
            "Unga driver 5 minutes la vandhuruvaanga. OTP 4821 share pannunga.",
            DEFAULT_VOICE_STYLE,
            True,
            False,
            "edge_fast",
            DEFAULT_TARGET_LANG,
        )
        logger.info("Demo phrase cache ready")
    except Exception as exc:  # noqa: BLE001
        logger.warning("Demo cache prime failed: %s", exc)

    if QUEUE_ENABLED:
        tts_queue = TTSQueue(
            worker_fn=_sync_worker,
            max_size=QUEUE_MAX_SIZE,
            worker_count=QUEUE_WORKER_COUNT,
            request_timeout_sec=QUEUE_REQUEST_TIMEOUT_SEC,
        )
        await tts_queue.start()
        logger.info("Queue enabled")
    else:
        logger.info("Queue disabled — Phase 1 direct path")

    if CACHE_PRIME_BACKGROUND:
        logger.warning(
            "CACHE_PRIME_BACKGROUND=true can block GPU inference — not recommended for low TTFA"
        )

    yield
    if tts_queue is not None:
        await tts_queue.stop()


app = FastAPI(title="movio-indicvoice", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Two-phone local testing layer (QR pairing + browser clients). Thin wrapper;
# reuses this server's TTS / translation pipeline. Start via: python -m phone_test
try:
    from phone_test.routes import mount_phone_test

    mount_phone_test(app)
except Exception as _phone_exc:  # noqa: BLE001
    logger.warning("Phone-test routes not mounted: %s", _phone_exc)

try:
    from server.dashboard_api import router as dashboard_router

    app.include_router(dashboard_router)
except Exception as _dash_exc:  # noqa: BLE001
    logger.warning("Dashboard routes not mounted: %s", _dash_exc)

try:
    from server.studio_api import router as studio_router

    app.include_router(studio_router)
except Exception as _studio_exc:  # noqa: BLE001
    logger.warning("Studio routes not mounted: %s", _studio_exc)


def _record_tts_event(result, *, source: str = "api") -> None:
    """Persist synthesis metrics for the overview dashboard (never fails the request)."""
    try:
        from server.telemetry import record_synthesis

        metrics = result.metrics_dict() if hasattr(result, "metrics_dict") else {}
        record_synthesis(
            text=getattr(result, "original_text", "") or "",
            normalized_text=getattr(result, "normalized_text", "") or "",
            voice_style=getattr(result, "voice_style", "") or "",
            backend=getattr(result, "backend", "") or "",
            detected_lang=getattr(result, "detected_lang", "") or "",
            target_lang=getattr(result, "target_lang", "") or "",
            ttfa_ms=metrics.get("ttfa_ms"),
            full_synthesis_ms=metrics.get("full_synthesis_ms"),
            audio_duration_sec=float(getattr(result, "audio_duration_sec", 0.0) or 0.0),
            cache_hit=bool(getattr(result, "cache_hit", False)),
            source=source,
        )
    except Exception:  # noqa: BLE001
        pass


@app.get("/demo")
@app.get("/demo/")
async def demo_dashboard():
    """Same movio voice dashboard (Generate + Two-phone test)."""
    path = Path(__file__).resolve().parents[1] / "demo" / "dashboard.html"
    return FileResponse(path, media_type="text/html")


class TTSRequest(BaseModel):
    text: str = Field(..., min_length=1)
    voice_style: Optional[str] = None
    return_audio_base64: bool = True
    skip_llm: bool = True
    chunked: bool = True
    # edge_fast (default, low latency) | win_sapi | indic_f5
    backend: Optional[str] = None
    # Speak-as language: tanglish | en | ta | auto
    target_lang: Optional[str] = None


async def _run_tts(
    text: str,
    voice_style: str,
    skip_llm: bool = True,
    chunked: bool = True,
    backend: str | None = None,
    target_lang: str | None = None,
):
    # Bypass queue for turbo backends — queue adds avoidable latency
    if _is_instant_backend(backend or DEFAULT_TTS_BACKEND):
        return await asyncio.to_thread(
            _sync_worker, text, voice_style, skip_llm, chunked, backend, target_lang
        )
    if QUEUE_ENABLED and tts_queue is not None:
        try:
            return await tts_queue.submit(
                text,
                voice_style,
                skip_llm=skip_llm,
                chunked=chunked,
                backend=backend,
                target_lang=target_lang,
            )
        except QueueFullError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except RequestTimeout as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from exc
    return await asyncio.to_thread(
        _sync_worker, text, voice_style, skip_llm, chunked, backend, target_lang
    )


@app.get("/health")
async def health():
    pipe = _get_pipeline(DEFAULT_TTS_BACKEND)
    device = getattr(pipe.backend, "device", None)
    mock = bool(getattr(pipe.backend, "_mock", False))
    try:
        from normalization.tanglish_translator import _gold_pairs, gold_pairs_version

        gold_count = len(_gold_pairs())
        gold_version = gold_pairs_version()
    except Exception:  # noqa: BLE001
        gold_count = 0
        gold_version = "unknown"
    return {
        "ok": True,
        "default_backend": _normalize_backend(DEFAULT_TTS_BACKEND),
        "loaded_backends": list(_pipelines.keys()),
        "queue_enabled": QUEUE_ENABLED,
        "tts_device": device,
        "tts_mock": mock,
        "gold_pairs": gold_count,
        "gold_version": gold_version,
        "cache": cache.stats() if cache else None,
        "queue": tts_queue.stats() if tts_queue else None,
    }


@app.post("/admin/reload-gold")
async def admin_reload_gold():
    """Reload gold pairs, clear translation + audio caches (dev hot-reload)."""
    from normalization.pronunciation_rules import clear_pronunciation_cache
    from normalization.tanglish_translator import _gold_pairs, gold_pairs_version, reload_gold

    reload_gold()
    clear_pronunciation_cache()
    count = len(_gold_pairs())
    if cache is not None:
        cache.clear()
    for pipe in _pipelines.values():
        pipe.pronunciation_version = pronunciation_version(pipe.lexicon)
    logger.info("Admin gold reload: %d pairs, version=%s", count, gold_pairs_version())
    return {"ok": True, "gold_pairs": count, "gold_version": gold_pairs_version(), "cache_cleared": cache is not None}


@app.post("/tts")
async def tts_endpoint(body: TTSRequest):
    """POST /tts — default backend is edge_fast for low TTFA."""
    voice = body.voice_style or DEFAULT_VOICE_STYLE
    result = await _run_tts(
        body.text,
        voice,
        skip_llm=body.skip_llm,
        chunked=body.chunked,
        backend=body.backend,
        target_lang=body.target_lang or DEFAULT_TARGET_LANG,
    )

    metrics = result.metrics_dict()
    _record_tts_event(result, source="studio")
    if body.return_audio_base64:
        return JSONResponse(
            {
                "metrics": metrics,
                "normalized_text": result.normalized_text,
                "translated_text": result.translated_text,
                "detected_lang": result.detected_lang,
                "target_lang": result.target_lang,
                "audio_base64": base64.b64encode(result.audio).decode("ascii"),
                "ttfa_ms": metrics["ttfa_ms"],
                "full_synthesis_ms": metrics["full_synthesis_ms"],
                "chunk_count": metrics.get("chunk_count", 1),
                "backend": metrics.get("backend"),
                "audio_format": getattr(result, "audio_format", "wav"),
            }
        )
    return Response(
        content=result.audio,
        media_type="audio/wav",
        headers={
            "X-TTFA-Ms": str(metrics["ttfa_ms"]),
            "X-Full-Synthesis-Ms": str(metrics["full_synthesis_ms"]),
            "X-Cache-Hit": str(result.cache_hit).lower(),
            "X-Backend": str(metrics.get("backend", "")),
        },
    )


@app.websocket("/tts/stream")
async def tts_stream(ws: WebSocket):
    """
    Streaming TTS. Client JSON:
      {"text": "...", "voice_style": "...", "skip_llm": true,
       "backend": "edge_fast", "target_lang": "tanglish"}
    """
    await ws.accept()
    try:
        payload = await ws.receive_json()
        text = str(payload.get("text", "")).strip()
        voice = payload.get("voice_style") or DEFAULT_VOICE_STYLE
        skip_llm = bool(payload.get("skip_llm", True))
        backend = _normalize_backend(payload.get("backend"))
        target_lang = str(payload.get("target_lang") or DEFAULT_TARGET_LANG)
        if not text:
            await ws.send_json({"type": "error", "detail": "text required"})
            await ws.close()
            return

        # Instant backends: one utterance (no clause loop). Edge still streams
        # first MP3 bytes internally; splitting into clauses serializes N network
        # round-trips and balloons full-synth for long Tanglish lines.
        if backend in ("edge_fast", "win_sapi"):
            t0 = time.perf_counter()
            result = await asyncio.to_thread(
                _sync_worker, text, voice, skip_llm, False, backend, target_lang
            )
            wall = round((time.perf_counter() - t0) * 1000, 2)
            b64 = base64.b64encode(result.audio).decode("ascii")
            metrics = result.metrics_dict()
            meta = {
                "translated_text": result.translated_text,
                "detected_lang": result.detected_lang,
                "target_lang": result.target_lang,
                "translator_engine": result.translator_engine,
                "audio_format": getattr(result, "audio_format", "wav"),
                "preprocessing_ms": metrics.get("preprocessing_ms"),
            }
            await ws.send_json(
                {
                    "type": "chunk",
                    "index": 0,
                    "text": result.normalized_text,
                    "audio_b64": b64,
                    "cache_hit": result.cache_hit,
                    "ttfa_ms": metrics["ttfa_ms"],
                    "normalized_text": result.normalized_text,
                    "chunk_count": 1,
                    "backend": result.backend,
                    "partial": False,
                    **meta,
                }
            )
            await ws.send_json(
                {
                    "type": "done",
                    "chunk_count": 1,
                    "ttfa_ms": metrics["ttfa_ms"],
                    "full_synthesis_ms": metrics["full_synthesis_ms"],
                    "normalized_text": result.normalized_text,
                    "audio_b64": b64,
                    "backend": result.backend,
                    "client_wall_ms": wall,
                    **meta,
                }
            )
            _record_tts_event(result, source="stream")
            return

        loop = asyncio.get_running_loop()
        out_q: asyncio.Queue = asyncio.Queue()
        pipe = _get_pipeline(backend)

        def _produce() -> None:
            prev = pipe.skip_llm
            prev_lang = pipe.target_lang
            pipe.skip_llm = skip_llm
            pipe.target_lang = target_lang
            try:
                t0 = time.perf_counter()
                first_ms: float | None = None
                parts: list[bytes] = []
                normalized = ""
                meta: dict = {}
                fmt = getattr(pipe.backend, "audio_format", "wav")

                # Edge: synthesize clause-by-clause on a warm WS so first
                # playable audio lands under ~500ms without truncating MP3.
                for ch in pipe.iter_chunks(text, voice, target_lang=target_lang):
                    parts.append(ch["audio"])
                    if first_ms is None:
                        first_ms = ch.get("ttfa_ms")
                    normalized = ch.get("normalized_text") or normalized
                    meta = {
                        "translated_text": ch.get("translated_text", ""),
                        "detected_lang": ch.get("detected_lang", ""),
                        "target_lang": ch.get("target_lang", ""),
                        "translator_engine": ch.get("translator_engine", ""),
                        "audio_format": fmt,
                    }
                    asyncio.run_coroutine_threadsafe(
                        out_q.put(
                            {
                                "type": "chunk",
                                "index": ch["index"],
                                "text": ch["text"],
                                "audio_b64": base64.b64encode(ch["audio"]).decode("ascii"),
                                "cache_hit": ch["cache_hit"],
                                "ttfa_ms": ch.get("ttfa_ms"),
                                "normalized_text": normalized,
                                "chunk_count": ch.get("chunk_count"),
                                "backend": getattr(pipe.backend, "name", backend),
                                "partial": False,
                                **meta,
                            }
                        ),
                        loop,
                    ).result()

                if fmt == "mp3":
                    full = parts[0] if len(parts) == 1 else b"".join(parts)
                else:
                    full = concat_wavs(parts) if parts else b""
                asyncio.run_coroutine_threadsafe(
                    out_q.put(
                        {
                            "type": "done",
                            "chunk_count": len(parts),
                            "ttfa_ms": first_ms,
                            "full_synthesis_ms": round((time.perf_counter() - t0) * 1000, 2),
                            "normalized_text": normalized,
                            "audio_b64": base64.b64encode(full).decode("ascii") if full else "",
                            "backend": getattr(pipe.backend, "name", backend),
                            "audio_format": fmt,
                            "client_wall_ms": round((time.perf_counter() - t0) * 1000, 2),
                            **meta,
                        }
                    ),
                    loop,
                ).result()
            except Exception as exc:  # noqa: BLE001
                asyncio.run_coroutine_threadsafe(
                    out_q.put({"type": "error", "detail": str(exc)}), loop
                ).result()
            finally:
                pipe.skip_llm = prev
                pipe.target_lang = prev_lang
                asyncio.run_coroutine_threadsafe(out_q.put(None), loop).result()

        import threading

        threading.Thread(target=_produce, daemon=True).start()
        while True:
            item = await out_q.get()
            if item is None:
                break
            await ws.send_json(item)
            if item.get("type") == "done":
                try:
                    from server.telemetry import record_synthesis

                    record_synthesis(
                        text=text,
                        normalized_text=str(item.get("normalized_text") or ""),
                        voice_style=voice,
                        backend=str(item.get("backend") or backend),
                        detected_lang=str(item.get("detected_lang") or ""),
                        target_lang=str(item.get("target_lang") or target_lang),
                        ttfa_ms=item.get("ttfa_ms"),
                        full_synthesis_ms=item.get("full_synthesis_ms"),
                        audio_duration_sec=0.0,
                        cache_hit=False,
                        source="stream",
                    )
                except Exception:  # noqa: BLE001
                    pass
                break
            if item.get("type") == "error":
                break
    except WebSocketDisconnect:
        logger.info("WS client disconnected")
    except Exception:  # noqa: BLE001
        logger.exception("WS stream error")
        try:
            await ws.send_json({"type": "error", "detail": "stream failed"})
        except Exception:  # noqa: BLE001
            pass


def main():
    import uvicorn

    uvicorn.run("server.main:app", host=SERVER_HOST, port=SERVER_PORT, reload=False)


if __name__ == "__main__":
    main()
