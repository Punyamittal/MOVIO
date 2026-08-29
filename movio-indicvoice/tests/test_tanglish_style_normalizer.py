"""Tests for gold-guided Tanglish style polish (Ollama output cleanup)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from normalization.tanglish_style_normalizer import polish_tanglish_output  # noqa: E402


class TestTanglishStyleNormalizer(unittest.TestCase):
    def test_confirm_kanna_calque(self) -> None:
        src = "driver ku confirm kanna which side la come pannenga"
        out = polish_tanglish_output(src).lower()
        self.assertIn("confirm pannunga", out)
        self.assertNotIn("kanna", out)
        self.assertNotIn("come pannenga", out)

    def test_driver_ku_to_kitta(self) -> None:
        out = polish_tanglish_output("driver ku sollunga").lower()
        self.assertIn("driver-kitta", out)

    def test_ten_minutes_to_pathu_nimisham(self) -> None:
        out = polish_tanglish_output("wait outside ten minutes").lower()
        self.assertIn("pathu nimisham", out)

    def test_please_tell_driver_gold_phrase(self) -> None:
        out = polish_tanglish_output("Please tell the driver to wait.").lower()
        self.assertIn("driver-kitta sollunga", out)

    def test_rain_come_heavily(self) -> None:
        out = polish_tanglish_output("since rain come heavily now").lower()
        self.assertIn("romba mazhai peiyuthu", out)

    def test_strips_tamil_script(self) -> None:
        out = polish_tanglish_output("naan uள்ளே wait pannuren")
        self.assertNotRegex(out, r"[\u0B80-\u0BFF]")

    def test_otp_vehicle_confirm_natural_register(self) -> None:
        broken = (
            "Enakku konjam seconds-ku munnadi OTP vandhuduchu, naan vehicle number "
            "TN 38 AB 7294-a correct vehicle dhaan pannikinum."
        )
        out = polish_tanglish_output(broken).lower()
        self.assertIn("sila seconds-ku munnadi", out)
        self.assertIn("dhaana-nu confirm pannikanum", out)
        self.assertNotIn("pannikinum", out)

    def test_back_seat_charger_natural_register(self) -> None:
        broken = (
            "Thappudhala en phone charger-a back seat-a koodaippen, so dryvur-a "
            "contact panni avarukku adhu check panna sollunga."
        )
        out = polish_tanglish_output(broken).lower()
        self.assertIn("back seat-la vittuten", out)
        self.assertIn("driver-a contact", out)
        self.assertIn("adha check panna sollunga", out)
        self.assertNotIn("koodaippen", out)

    def test_map_eta_increase_natural_register(self) -> None:
        broken = (
            "Signal kitta romba traffic irukku, map-la arrival time-nu increase "
            "dhaan padhinaindhu nimisham-ku mela aagalam."
        )
        out = polish_tanglish_output(broken).lower()
        self.assertIn("innum padhinaindhu nimisham-ku mela", out)
        self.assertNotIn("increase dhaan", out)


if __name__ == "__main__":
    unittest.main()
