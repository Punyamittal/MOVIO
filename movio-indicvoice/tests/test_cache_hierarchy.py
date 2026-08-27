"""
Unit/integration tests for layered TTS cache (full / clause / template).

Run: python -m unittest tests.test_cache_hierarchy -v
  or: pytest tests/test_cache_hierarchy.py -q
"""
from __future__ import annotations

import io
import struct
import sys
import threading
import time
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.cache import AudioCache  # noqa: E402
from server.pipeline import TTSPipeline, pronunciation_version  # noqa: E402
from server.templates import TemplateRegistry, get_template_registry  # noqa: E402
from server.websocket_stream import concat_wavs  # noqa: E402
from tts_backends.base import TTSBackend  # noqa: E402


def _silent_wav(duration_sec: float = 0.3, sr: int = 22050, fingerprint: bytes = b"") -> bytes:
    n = int(duration_sec * sr)
    # Optional non-zero samples so different phrases produce different PCM
    frames = [0] * n
    if fingerprint:
        for i, b in enumerate(fingerprint[: min(64, n)]):
            frames[i] = ((b % 40) - 20) * 100
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(struct.pack("<" + "h" * n, *frames))
    return buf.getvalue()


class CountingBackend(TTSBackend):
    name = "mock_counting"
    audio_format = "wav"

    def __init__(self):
        self.calls: list[str] = []
        self.lock = threading.Lock()
        self.delay_sec = 0.05

    def synthesize(self, text: str, voice_style: str) -> bytes:
        with self.lock:
            self.calls.append(text)
        time.sleep(self.delay_sec)
        return _silent_wav(
            0.15 + 0.01 * len(text.split()),
            fingerprint=text.encode("utf-8"),
        )


class TestCacheIdentity(unittest.TestCase):
    def test_different_dimensions_different_keys(self):
        base = dict(
            normalized_text="Please share the OTP.",
            voice_style="Jaya",
            target_language="tanglish",
            pronunciation_version="abc",
            tts_model_version="win_sapi:wav",
            audio_format="wav",
            level="clause",
        )
        k0 = AudioCache.make_key(**base)
        self.assertNotEqual(k0, AudioCache.make_key(**{**base, "voice_style": "Rohit"}))
        self.assertNotEqual(k0, AudioCache.make_key(**{**base, "target_language": "en"}))
        self.assertNotEqual(k0, AudioCache.make_key(**{**base, "tts_model_version": "edge:mp3"}))
        self.assertNotEqual(k0, AudioCache.make_key(**{**base, "pronunciation_version": "xyz"}))
        self.assertNotEqual(k0, AudioCache.make_key(**{**base, "audio_format": "mp3"}))
        self.assertNotEqual(k0, AudioCache.make_key(**{**base, "level": "full"}))


class TestDynamicSlots(unittest.TestCase):
    def setUp(self):
        self.reg = get_template_registry()
        self.cache = AudioCache(64)
        self.backend = CountingBackend()
        self.pipe = TTSPipeline(
            backend=self.backend,
            cache=self.cache,
            skip_llm=True,
            translate_enabled=False,
            clause_cache=True,
            template_cache=True,
        )

    def test_otp_slots_do_not_cross(self):
        a = "Please share the OTP 4821."
        b = "Please share the OTP 7392."
        ra = self.pipe.run(a, "voice-a", target_lang="en")
        rb = self.pipe.run(b, "voice-a", target_lang="en")
        self.assertNotEqual(ra.normalized_text, rb.normalized_text)
        # Dynamic OTP spoken forms must differ
        self.assertIn("four eight two one", ra.normalized_text)
        self.assertIn("seven three nine two", rb.normalized_text)
        # After both synthesized, replaying A must not pull B's audio via wrong key
        calls_before = len(self.backend.calls)
        ra2 = self.pipe.run(a, "voice-a", target_lang="en")
        self.assertTrue(ra2.cache_hit)
        self.assertEqual(len(self.backend.calls), calls_before)
        self.assertEqual(ra2.audio, ra.audio)
        self.assertNotEqual(ra.audio, rb.audio)


class TestClauseAndTemplateReuse(unittest.TestCase):
    def setUp(self):
        self.cache = AudioCache(128)
        self.backend = CountingBackend()
        self.pipe = TTSPipeline(
            backend=self.backend,
            cache=self.cache,
            skip_llm=True,
            translate_enabled=False,
            clause_cache=True,
            template_cache=True,
        )

    def test_minutes_reuse_static_prefix(self):
        s5 = "Your driver will arrive in 5 minutes."
        s10 = "Your driver will arrive in 10 minutes."
        self.pipe.run(s5, "v", target_lang="en")
        calls_after_first = list(self.backend.calls)
        self.pipe.run(s10, "v", target_lang="en")
        # Cold path synthesizes the whole clause once, then warms the static prefix.
        static = "Your driver will arrive"
        self.assertIn(static, calls_after_first)
        static_calls = [c for c in self.backend.calls if c == static]
        self.assertEqual(len(static_calls), 1, "static template unit must be synthesized once")
        # Second ETA must synthesize its own dynamic unit (not reuse five-minutes audio)
        self.assertIn("in ten minutes.", self.backend.calls)
        self.assertNotIn("in five minutes.", self.backend.calls)

    def test_template_match_registry(self):
        reg = TemplateRegistry()
        m = reg.match("Your driver will arrive in five minutes.")
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.template_id, "driver_arrive_minutes")
        self.assertEqual(m.slots["minutes"], "five")
        self.assertEqual(len(m.units), 2)
        self.assertEqual(m.units[0].kind, "static")
        self.assertEqual(m.units[1].kind, "dynamic")
        self.assertIn("five", m.units[1].text)


class TestConcurrentDedup(unittest.TestCase):
    def test_inflight_coalescing(self):
        cache = AudioCache(32)
        backend = CountingBackend()
        backend.delay_sec = 0.2
        pipe = TTSPipeline(
            backend=backend,
            cache=cache,
            skip_llm=True,
            translate_enabled=False,
            clause_cache=True,
            template_cache=False,
        )
        text = "Please share the OTP."
        results: list = []
        errors: list = []

        def worker():
            try:
                results.append(pipe.run(text, "v", target_lang="en"))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertFalse(errors)
        self.assertEqual(len(results), 6)
        # Whole utterance or clause should only be generated once
        unique_synth = set(backend.calls)
        self.assertLessEqual(len(backend.calls), 2)  # at most clause pieces once each
        self.assertTrue(all(r.audio == results[0].audio for r in results))
        self.assertTrue(unique_synth)


class TestCacheInvalidation(unittest.TestCase):
    def test_model_change_misses(self):
        cache = AudioCache(16)
        text = "Your driver has arrived."
        cache.put(
            text,
            "v",
            b"AUDIO-A",
            tts_model_version="win_sapi:wav",
            pronunciation_version="p1",
            level="full",
        )
        hit = cache.get(
            text,
            "v",
            tts_model_version="win_sapi:wav",
            pronunciation_version="p1",
            level="full",
        )
        self.assertEqual(hit, b"AUDIO-A")
        miss = cache.get(
            text,
            "v",
            tts_model_version="edge_fast:mp3",
            pronunciation_version="p1",
            level="full",
        )
        self.assertIsNone(miss)
        miss2 = cache.get(
            text,
            "v",
            tts_model_version="win_sapi:wav",
            pronunciation_version="p2-changed",
            level="full",
        )
        self.assertIsNone(miss2)

    def test_pronunciation_version_changes(self):
        v1 = pronunciation_version({"OMR": "O M R", "OTP": ""})
        v2 = pronunciation_version({"OMR": "oh em aar", "OTP": ""})
        self.assertNotEqual(v1, v2)


class TestAudioStitching(unittest.TestCase):
    def test_concat_sample_rate_and_duration(self):
        a = _silent_wav(0.2, sr=22050)
        b = _silent_wav(0.3, sr=22050)
        merged = concat_wavs([a, b], gap_ms=100)
        self.assertTrue(merged[:4] == b"RIFF")
        with wave.open(io.BytesIO(merged), "rb") as wf:
            sr = wf.getframerate()
            nframes = wf.getnframes()
            channels = wf.getnchannels()
        self.assertEqual(sr, 22050)
        self.assertEqual(channels, 1)
        duration = nframes / sr
        # 0.2 + 0.1 gap + 0.3 = 0.6s (± frame rounding)
        self.assertGreater(duration, 0.55)
        self.assertLess(duration, 0.70)

    def test_pipeline_stitched_output_is_wav(self):
        cache = AudioCache(64)
        backend = CountingBackend()
        pipe = TTSPipeline(
            backend=backend,
            cache=cache,
            skip_llm=True,
            translate_enabled=False,
            clause_cache=True,
            template_cache=True,
        )
        # Two-clause utterance forces stitch path after full miss
        text = "Your driver has arrived. Please share the OTP."
        result = pipe.run(text, "v", target_lang="en")
        self.assertTrue(result.audio[:4] == b"RIFF")
        self.assertGreater(result.chunk_count, 1)
        self.assertGreater(result.audio_duration_sec, 0.15)


class TestFullUtteranceFastPath(unittest.TestCase):
    def test_full_hit_skips_tts(self):
        cache = AudioCache(32)
        backend = CountingBackend()
        pipe = TTSPipeline(
            backend=backend,
            cache=cache,
            skip_llm=True,
            translate_enabled=False,
            clause_cache=True,
            template_cache=True,
        )
        text = "Your ride will arrive shortly."
        r1 = pipe.run(text, "v", target_lang="en")
        n1 = len(backend.calls)
        r2 = pipe.run(text, "v", target_lang="en")
        self.assertTrue(r2.cache_hit)
        self.assertEqual(r2.cache_level, "full")
        self.assertEqual(len(backend.calls), n1)
        self.assertEqual(r1.audio, r2.audio)


if __name__ == "__main__":
    unittest.main()
