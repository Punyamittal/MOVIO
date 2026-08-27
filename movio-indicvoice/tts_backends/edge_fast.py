"""
Ultra-low-latency TTS via Microsoft Edge neural voices (edge-tts).

Keeps a warm WebSocket to speech.platform.bing.com so synthesis skips the
~1s reconnect tax. Warm first-audio is typically ~250–450ms on a decent link.

Returns MP3 bytes (clients play as audio/mpeg).

Install: pip install edge-tts aiohttp certifi
"""
from __future__ import annotations

import asyncio
import io
import logging
import sys
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tts_backends.base import TTSBackend  # noqa: E402

logger = logging.getLogger("tts.edge_fast")

VOICE_MAP = {
    "jaya": "ta-IN-PallaviNeural",
    "kavitha": "ta-IN-PallaviNeural",
    "pallavi": "ta-IN-PallaviNeural",
    "valluvar": "ta-IN-ValluvarNeural",
    "divya": "en-IN-NeerjaNeural",
    "neerja": "en-IN-NeerjaNeural",
    "rohit": "en-IN-PrabhatNeural",
    "prabhat": "en-IN-PrabhatNeural",
    "tamil": "ta-IN-PallaviNeural",
    "english": "en-IN-NeerjaNeural",
}
DEFAULT_VOICE = "ta-IN-PallaviNeural"
OUTPUT_FORMAT = "audio-24khz-48kbitrate-mono-mp3"
SPEECH_RATE = "+20%"
KEEPALIVE_SEC = 12.0
# Fire first-audio callback on the first MP3 packet (TTFA), not after buffering
FIRST_CHUNK_BYTES = 1


def _pick_voice(voice_style: str) -> str:
    s = (voice_style or "").strip()
    if not s:
        return DEFAULT_VOICE
    if "-" in s and "Neural" in s and " " not in s:
        return s
    lower = s.lower()
    for key, vid in VOICE_MAP.items():
        if key in lower:
            return vid
    if any(n in lower for n in ("jaya", "kavitha", "tamil")):
        return "ta-IN-PallaviNeural"
    if any(n in lower for n in ("rohit", "divya", "male")):
        return "en-IN-PrabhatNeural" if "rohit" in lower or "male" in lower else "en-IN-NeerjaNeural"
    return DEFAULT_VOICE


class _EdgePool:
    """Single-thread asyncio pool with a reused Edge read-aloud WebSocket."""

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._session = None
        self._ws = None
        self._lock: Optional[asyncio.Lock] = None
        self._ready = threading.Event()
        self._closed = False
        self._mock = False
        self._last_synth = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run_loop, name="edge-tts-pool", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=60):
            raise RuntimeError("Edge TTS pool failed to start")

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._lock = asyncio.Lock()

        async def _start() -> None:
            try:
                await self._bootstrap()
            finally:
                self._ready.set()
            if not self._mock:
                loop.create_task(self._keepalive())

        loop.create_task(_start())
        loop.run_forever()

    async def _bootstrap(self) -> None:
        try:
            import aiohttp  # noqa: F401
            import edge_tts  # noqa: F401

            assert self._lock is not None
            async with self._lock:
                await self._ensure_session()
                await self._ensure_ws()
                await self._synth_locked("OTP 4821.", DEFAULT_VOICE, None)
            logger.info("Edge pool ready (warm websocket)")
        except ImportError:
            logger.warning("edge-tts/aiohttp missing — Edge backend will mock")
            self._mock = True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Edge pool bootstrap failed: %s", exc)

    async def _ensure_session(self) -> None:
        if self._session is not None and not self._session.closed:
            return
        import aiohttp
        from edge_tts.communicate import _SSL_CTX

        timeout = aiohttp.ClientTimeout(total=45, connect=10, sock_connect=10, sock_read=30)
        connector = aiohttp.TCPConnector(
            limit=8,
            ttl_dns_cache=600,
            keepalive_timeout=120,
            enable_cleanup_closed=True,
            ssl=_SSL_CTX,
        )
        self._session = aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            trust_env=True,
        )

    async def _close_ws(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:  # noqa: BLE001
                pass
            self._ws = None

    async def _ensure_ws(self) -> None:
        if self._ws is not None and not self._ws.closed:
            return
        await self._ensure_session()
        from edge_tts.communicate import _SSL_CTX, connect_id, date_to_string
        from edge_tts.constants import SEC_MS_GEC_VERSION, WSS_HEADERS, WSS_URL
        from edge_tts.drm import DRM

        assert self._session is not None
        # Drop any half-open socket before replacing
        await self._close_ws()
        url = (
            f"{WSS_URL}&ConnectionId={connect_id()}"
            f"&Sec-MS-GEC={DRM.generate_sec_ms_gec()}"
            f"&Sec-MS-GEC-Version={SEC_MS_GEC_VERSION}"
        )
        t0 = time.perf_counter()
        self._ws = await self._session.ws_connect(
            url,
            compress=15,
            headers=DRM.headers_with_muid(WSS_HEADERS),
            ssl=_SSL_CTX,
        )
        cfg = (
            f"X-Timestamp:{date_to_string()}\r\n"
            "Content-Type:application/json; charset=utf-8\r\n"
            "Path:speech.config\r\n\r\n"
            '{"context":{"synthesis":{"audio":{"metadataoptions":{'
            '"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"'
            "},"
            f'"outputFormat":"{OUTPUT_FORMAT}"'
            "}}}}\r\n"
        )
        await self._ws.send_str(cfg)
        logger.info("Edge websocket connected in %.0fms", (time.perf_counter() - t0) * 1000)

    async def _keepalive(self) -> None:
        while not self._closed:
            await asyncio.sleep(KEEPALIVE_SEC)
            if self._mock or self._closed:
                continue
            # Skip if a real request kept the socket warm recently
            if (time.perf_counter() - self._last_synth) < KEEPALIVE_SEC:
                continue
            try:
                assert self._lock is not None
                async with self._lock:
                    await self._ensure_ws()
                    await self._synth_locked("OK.", DEFAULT_VOICE, None)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Edge keepalive refresh: %s", exc)
                await self._close_ws()

    async def _synth_locked(
        self,
        text: str,
        voice: str,
        on_first: Optional[Callable[[bytes], None]],
    ) -> bytes:
        from edge_tts.communicate import (
            connect_id,
            date_to_string,
            get_headers_and_data,
            mkssml,
            ssml_headers_plus_data,
        )
        from edge_tts.data_classes import TTSConfig

        await self._ensure_ws()
        assert self._ws is not None
        cfg = TTSConfig(voice, SPEECH_RATE, "+0%", "+0Hz", "SentenceBoundary")
        await self._ws.send_str(
            ssml_headers_plus_data(connect_id(), date_to_string(), mkssml(cfg, text))
        )

        buf = bytearray()
        first_sent = False
        import aiohttp

        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.BINARY:
                    if len(msg.data) < 2:
                        continue
                    header_length = int.from_bytes(msg.data[:2], "big")
                    params, data = get_headers_and_data(msg.data, header_length)
                    if params.get(b"Path") == b"audio" and data:
                        buf.extend(data)
                        if on_first and not first_sent and len(buf) >= FIRST_CHUNK_BYTES:
                            on_first(bytes(buf))
                            first_sent = True
                elif msg.type == aiohttp.WSMsgType.TEXT:
                    encoded = msg.data.encode("utf-8")
                    params, _ = get_headers_and_data(encoded, encoded.find(b"\r\n\r\n"))
                    if params.get(b"Path") == b"turn.end":
                        break
                elif msg.type in (
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                    aiohttp.WSMsgType.CLOSE,
                ):
                    await self._close_ws()
                    raise RuntimeError("Edge websocket closed mid-synthesis")
        except Exception:
            await self._close_ws()
            raise

        if not buf:
            raise RuntimeError("edge-tts returned empty audio")
        if on_first and not first_sent:
            on_first(bytes(buf))
        self._last_synth = time.perf_counter()
        return bytes(buf)

    async def synthesize(
        self,
        text: str,
        voice: str,
        on_first: Optional[Callable[[bytes], None]] = None,
    ) -> bytes:
        if self._mock:
            return _silent_wav(max(0.4, min(4.0, len(text) * 0.04)))
        assert self._lock is not None
        async with self._lock:
            try:
                return await self._synth_locked(text, voice, on_first)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Edge synth failed (%s); reconnecting once", exc)
                await self._close_ws()
                await self._ensure_ws()
                return await self._synth_locked(text, voice, on_first)

    def synthesize_sync(
        self,
        text: str,
        voice: str,
        on_first: Optional[Callable[[bytes], None]] = None,
    ) -> bytes:
        self.start()
        assert self._loop is not None
        fut: Future = asyncio.run_coroutine_threadsafe(
            self.synthesize(text, voice, on_first), self._loop
        )
        return fut.result(timeout=60)

    def close(self) -> None:
        self._closed = True
        if self._loop is None:
            return

        async def _shutdown() -> None:
            await self._close_ws()
            if self._session is not None and not self._session.closed:
                await self._session.close()

        try:
            fut = asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)
            fut.result(timeout=5)
        except Exception:  # noqa: BLE001
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)


_POOL = _EdgePool()


class EdgeFastBackend(TTSBackend):
    name = "edge_fast"
    audio_format = "mp3"

    def __init__(self, device: str | None = None, return_wav: bool = False):
        self.device = device or "cpu"
        self.return_wav = return_wav
        self._mock = False
        self._checked = False

    def warmup(self) -> None:
        self._ensure()
        if self._mock:
            return
        try:
            audio = self.synthesize("OTP 4821.", "jaya")
            logger.info(
                "Edge-TTS warmup complete (voice=%s, bytes=%d)",
                DEFAULT_VOICE,
                len(audio),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Edge-TTS warmup failed: %s", exc)

    def _ensure(self) -> None:
        if self._checked:
            return
        self._checked = True
        try:
            import edge_tts  # noqa: F401
            import aiohttp  # noqa: F401

            _POOL.start()
            self._mock = _POOL._mock
        except ImportError:
            logger.error(
                "edge-tts not installed — Edge backend cannot speak. "
                "Run: pip install edge-tts aiohttp certifi"
            )
            self._mock = True

    def synthesize(
        self,
        text: str,
        voice_style: str,
        on_first_audio: Callable[[bytes], None] | None = None,
    ) -> bytes:
        self._ensure()
        text = (text or "").strip()
        if not text:
            return _silent_wav(0.3) if self.return_wav else b""
        if self._mock:
            # Never cache / ship silence as if it were speech.
            raise RuntimeError(
                "edge-tts is not installed (silent mock disabled). "
                "pip install edge-tts aiohttp certifi  — or set DEFAULT_TTS_BACKEND=win_sapi"
            )

        voice = _pick_voice(voice_style)
        audio = _POOL.synthesize_sync(text, voice, on_first=on_first_audio)
        if self.return_wav:
            return _mp3_to_wav(audio)
        return audio


def _mp3_to_wav(mp3_bytes: bytes) -> bytes:
    import subprocess
    import tempfile

    try:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        ffmpeg = "ffmpeg"

    with tempfile.TemporaryDirectory() as td:
        mp3_path = Path(td) / "in.mp3"
        wav_path = Path(td) / "out.wav"
        mp3_path.write_bytes(mp3_bytes)
        try:
            subprocess.run(
                [ffmpeg, "-y", "-i", str(mp3_path), "-ac", "1", str(wav_path)],
                check=True,
                capture_output=True,
            )
            return wav_path.read_bytes()
        except Exception as exc:  # noqa: BLE001
            logger.warning("mp3→wav failed (%s); returning silence", exc)
            return _silent_wav(1.0)


def _silent_wav(duration_sec: float = 1.0, sr: int = 24000) -> bytes:
    import struct
    import wave

    n = int(duration_sec * sr)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack("<" + "h" * n, *([0] * n)))
    return buf.getvalue()


def get_backend() -> EdgeFastBackend:
    return EdgeFastBackend()
