"""
Unit tests for deterministic normalizers + light pipeline smoke tests.

Run: pytest tests/test_pipeline.py -q
Or:  python -m tests.test_pipeline
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from normalization.deterministic_normalizer import (  # noqa: E402
    digit_by_digit,
    normalize,
    normalize_booking_ids_and_plates,
    normalize_cardinal_numbers,
    normalize_currency,
    normalize_dates,
    normalize_distances,
    normalize_otp_and_short_codes,
    normalize_phone_numbers,
    normalize_times,
)
from normalization.validator import validate  # noqa: E402
from server.pipeline import TTSPipeline  # noqa: E402


class TestOTP(unittest.TestCase):
    def test_otp_digit_by_digit(self):
        out = normalize_otp_and_short_codes("Your OTP is 4821")
        self.assertIn("four eight two one", out)
        self.assertNotIn("thousand", out)

    def test_digit_by_digit_helper(self):
        self.assertEqual(digit_by_digit("4821"), "four eight two one")


class TestPhone(unittest.TestCase):
    def test_phone_digit_by_digit(self):
        out = normalize_phone_numbers("Please call 9876543210 now")
        self.assertIn("nine eight seven", out)
        self.assertNotIn("9876543210", out)


class TestPlates(unittest.TestCase):
    def test_plate_expansion(self):
        out = normalize_booking_ids_and_plates("Cab TN45AB1234 arrived")
        # letter-by-letter + digit-by-digit
        self.assertIn("T", out)
        self.assertIn("N", out)
        self.assertIn("four", out)
        self.assertIn("five", out)


class TestCurrency(unittest.TestCase):
    def test_rupees(self):
        out = normalize_currency("fare ₹245")
        self.assertIn("rupees", out)
        self.assertIn("two hundred", out)


class TestDistance(unittest.TestCase):
    def test_km(self):
        out = normalize_distances("roughly 12 km away")
        self.assertIn("twelve", out)
        self.assertIn("kilometers", out)


class TestTime(unittest.TestCase):
    def test_time_spoken(self):
        out = normalize_times("arrive at 7:30 PM")
        self.assertIn("seven", out)
        self.assertIn("thirty", out)
        self.assertIn("PM", out)


class TestDate(unittest.TestCase):
    def test_numeric_date(self):
        out = normalize_dates("trip on 15/08/2026")
        self.assertIn("August", out)
        self.assertIn("fifteen", out)


class TestCardinal(unittest.TestCase):
    def test_cardinal_vs_otp_context(self):
        # After OTP normalization, remaining small counts use cardinal form
        text = normalize("Driver 5 minutes away. OTP 4821")
        self.assertIn("four eight two one", text)
        self.assertIn("five", text)


class TestFullNormalize(unittest.TestCase):
    def test_pipeline_order(self):
        out = normalize("Your OTP is 4821, fare ₹100, 2 km, at 9:00 AM")
        self.assertIn("four eight two one", out)
        self.assertIn("rupees", out)
        self.assertIn("kilometers", out)


class TestValidator(unittest.TestCase):
    def test_numeric_flag(self):
        r = validate("OTP 4821", "no numbers here")
        self.assertFalse(r.ok)
        self.assertTrue(any(f.startswith("numeric_missing") for f in r.flags))

    def test_preserve_flag(self):
        r = validate("share with driver", "share with டிரைவர்")
        self.assertFalse(r.ok)
        self.assertTrue(any("preserve_lost" in f for f in r.flags))


class TestPipelineSmoke(unittest.TestCase):
    def test_end_to_end_mock(self):
        pipe = TTSPipeline(skip_llm=True)
        result = pipe.run("Your OTP is 4821")
        self.assertTrue(len(result.audio) > 44)
        self.assertIn("four eight two one", result.normalized_text)
        # TTFA and full synthesis both present and distinct keys
        m = result.metrics_dict()
        self.assertIn("ttfa_ms", m)
        self.assertIn("full_synthesis_ms", m)


if __name__ == "__main__":
    unittest.main()
