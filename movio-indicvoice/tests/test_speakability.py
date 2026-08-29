"""Tests for colloquial + phonetic Tanglish pronunciation rules."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from normalization.pronunciation_rules import (  # noqa: E402
    colloquialize_tanglish,
    load_pronunciation_lexicon,
    phoneticize_tanglish,
)
from normalization.speakability import prepare_for_latin_tts, prepare_for_tanglish_tts  # noqa: E402


class TestLexicon(unittest.TestCase):
    def test_lexicon_loads_without_tamil_script(self):
        data = load_pronunciation_lexicon()
        self.assertGreater(len(data.get("tokens", [])), 50)
        self.assertGreater(len(data.get("phrases", [])), 20)

    def test_pannuraru_phonetic_not_corrupted(self):
        out = phoneticize_tanglish("wait pannuraru.").lower()
        self.assertIn("pan-nu-ra-ru", out)
        self.assertNotIn("pan--ra-ru", out)


class TestColloquialRules(unittest.TestCase):
    def test_pakkathula_becomes_kitta(self):
        src = "Naan security gate pakkathula wait pannitu irukken."
        out = colloquialize_tanglish(src)
        self.assertIn("security gate kitta", out.lower())
        self.assertNotIn("pakkathula", out.lower())
        self.assertIn("pannit iruken", out.lower())

    def test_building_ngil_becomes_building_kitta(self):
        out = colloquialize_tanglish("Naan building-ngil nikkiren.")
        self.assertIn("building kitta", out.lower())

    def test_imperatives_unchanged_in_driver_register(self):
        src = "Driver-a inge vara sollunga."
        out = colloquialize_tanglish(src)
        self.assertIn("vara sollunga", out.lower())

    def test_driver_wrong_entrance_gold_phrase(self):
        src = (
            "Driver pakathule vandhutaru, aana thappana entrance-le wait pannuraru."
        )
        out = colloquialize_tanglish(src)
        self.assertEqual(out, src)
        tts = prepare_for_latin_tts(src).lower()
        self.assertIn("dry-vur pa-ka-thu-le van-thu-ta-ru", tts)
        self.assertIn("thap-pa-na entrance-le wait pan-nu-ra-ru", tts)

    def test_gaadi_to_vandi(self):
        out = colloquialize_tanglish("Gaadi late aaguthu.")
        self.assertIn("vandi", out.lower())
        self.assertNotIn("gaadi", out.lower())

    def test_gold_waiting_sentence(self):
        src = (
            "Naan security gate kitta building outside-la wait pannit iruken, "
            "driver-a inge vara sollung."
        )
        out = colloquialize_tanglish(src)
        self.assertEqual(out.lower(), src.lower())


class TestPhoneticRules(unittest.TestCase):
    def test_gate_kitta_phonetic(self):
        out = phoneticize_tanglish("Naan security gate kitta wait pannit iruken.")
        self.assertIn("gate kit-ta", out.lower())
        self.assertIn("i-ru-ken", out.lower())

    def test_vara_sollung_phonetic(self):
        out = phoneticize_tanglish("driver-a inge vara sollung")
        self.assertIn("va-ra sol-lung", out.lower())

    def test_anna_address_phonetic_hyphenated(self):
        out = phoneticize_tanglish(
            "Thanks anna, gate kitta wait pannit iruken.", compact=False
        ).lower()
        self.assertIn("ann-uh", out)
        self.assertNotIn("an-na", out)

    def test_anna_address_phonetic_compact(self):
        out = phoneticize_tanglish(
            "Thanks anna, gate kitta wait pannit iruken.", compact=True
        ).lower()
        self.assertIn("annuh", out)
        self.assertNotIn("an-na", out)

    def test_address_terms_saar_thambi(self):
        out = phoneticize_tanglish("Saar, thambi inga varunga.", compact=True).lower()
        self.assertIn("saar", out)
        self.assertIn("thambi", out)
        hyphen = phoneticize_tanglish("Saar, thambi inga varunga.", compact=False).lower()
        self.assertIn("tham-bi", hyphen)

    def test_driver_wrong_entrance_translation(self):
        import normalization.tanglish_translator as tt
        from normalization.language_translator import translate

        tt._GOLD = None
        src = "The driver has arrived, but he is waiting near the wrong entrance."
        r = translate(src, "tanglish")
        self.assertEqual(r.engine, "gold")
        self.assertIn("pakathule vandhutaru", r.text.lower())
        self.assertIn("thappana entrance-le", r.text.lower())
        self.assertIn("pannuraru", r.text.lower())
        self.assertNotIn("pakkatla", r.text.lower())
        self.assertNotIn("arrive panna", r.text.lower())

    def test_still_office_tell_driver_wait_gold(self):
        import normalization.tanglish_translator as tt
        from normalization.language_translator import translate
        from normalization.speakability import prepare_for_latin_tts

        tt._GOLD = None
        src = (
            "I'm still at the office, it'll take a bit of time, "
            "please tell the driver to wait."
        )
        r = translate(src, "tanglish")
        self.assertEqual(r.engine, "gold")
        self.assertIn("innum office-la iruken", r.text.lower())
        self.assertIn("konja neram aagum", r.text.lower())
        self.assertIn("driver kitta wait pannunga sollunga", r.text.lower())
        tts = prepare_for_latin_tts(r.text).lower()
        self.assertIn("in-num of-fice-la i-ru-ken", tts)
        self.assertIn("dry-vur kit-ta wait pan-nun-ga sol-lun-ga", tts)

    def test_wrong_address_confirm_gold(self):
        import normalization.tanglish_translator as tt
        from normalization.language_translator import translate
        from normalization.speakability import prepare_for_latin_tts

        tt._GOLD = None
        src = (
            "The car has already arrived here, but the address you gave is wrong, "
            "please confirm a bit."
        )
        r = translate(src, "tanglish")
        self.assertEqual(r.engine, "gold")
        self.assertIn("vandhuduchu", r.text.lower())
        self.assertIn("thappa iruku", r.text.lower())
        self.assertIn("konjam confirm pannunga", r.text.lower())
        tts = prepare_for_latin_tts(r.text).lower()
        self.assertIn("van-di al-red-y in-ga van-thu-du-chu", tts)
        self.assertIn("kon-jam confirm pan-nun-ga", tts)

    def test_cant_come_near_call_driver_gold(self):
        import normalization.tanglish_translator as tt
        from normalization.language_translator import translate

        tt._GOLD = None
        src = (
            "I can't come near, you're stopped for a while, "
            "please call the driver and tell him."
        )
        r = translate(src, "tanglish")
        self.assertEqual(r.engine, "gold")
        self.assertIn("kitta vara mudiyathu", r.text.lower())
        self.assertIn("konja nerathula stop pannitu iruken", r.text.lower())
        self.assertIn("driver-a phone panni sollunga", r.text.lower())
        self.assertNotIn("pottum", r.text.lower())
        self.assertNotIn("tell pannunga", r.text.lower())

    def test_full_latin_pipeline(self):
        src = (
            "Naan security gate pakkathula building outside-la wait pannitu irukken, "
            "driver-a inge vara sollunga."
        )
        out = prepare_for_latin_tts(src).lower()
        self.assertIn("gate kit-ta", out)
        self.assertIn("pan-nit i-ru-ken", out)
        self.assertIn("sol-lun-ga", out)
        self.assertNotIn("pakkathula", out)


if __name__ == "__main__":
    unittest.main()
