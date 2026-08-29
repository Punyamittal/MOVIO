"""Style polish fixes for meter/fixed-price and route-confirm calques."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from normalization.tanglish_style_normalizer import polish_tanglish_output  # noqa: E402
from normalization.tanglish_translator import clear_cache, exact_gold, translate_to_tanglish  # noqa: E402
from normalization.translation_validator import check_case_markers, validate_translation  # noqa: E402

METER_EN = (
    "Brother, I know the meter is showing a different amount, but the app "
    "already confirmed a fixed price for this trip, so please go by that instead"
)

FLYOVER_ROUTE_EN = (
    "Brother, before you start the meter, could you confirm once whether you're "
    "taking the flyover or the ground route, since the fare changes depending on that?"
)

UNCLE_INDICATOR_EN = (
    "Uncle, I can see three cars matching that description near the gate, so could "
    "you flash your indicator once so I know which one is yours?"
)

PROCESSION_ROUTE_EN = (
    "Brother, please don't take the route the app is showing right now, since "
    "there's a religious procession blocking that entire street for the next hour."
)

FUEL_GAUGE_EN = (
    "Brother, I noticed the fuel gauge is showing quite low, so if you need to "
    "stop at a petrol bunk on the way, please let me know in advance so I'm not "
    "surprised by the delay."
)

LATE_HIGHWAY_EN = (
    "Brother, since it's already quite late and the streets are mostly empty, "
    "would it be okay to skip the usual route and take the highway instead, "
    "just to save some time?"
)

BRIDGE_BUMPY_EN = (
    "Brother, I understand the bridge road is faster, but my stomach isn't doing "
    "too well today, so please avoid the bumpy stretch even if it takes a couple "
    "of minutes longer."
)

BRIDGE_BUMPY_BAD = (
    "Aga bridge road pona, brother, but my stomach bad day irukku, so dryvur "
    "bumpy stretch-ko po nu naan nenaikkuren, konjam extra nimisham aanalum paravaila."
)


class TestMeterFixedPricePolish(unittest.TestCase):
    def test_aadha_to_aana(self):
        out = polish_tanglish_output("Aadha brother, meter amount").lower()
        self.assertIn("aana", out)
        self.assertNotIn("aadha", out)

    def test_follow_panna_to_imperative(self):
        out = polish_tanglish_output("so app-la price follow panna").lower()
        self.assertIn("follow pannunga", out)

    def test_app_confirm_not_first_person(self):
        out = polish_tanglish_output("app confirm panniten").lower()
        self.assertIn("pannitrukku", out)
        self.assertNotIn("panniten", out)

    def test_preprocess_gold_meter_sentence(self):
        from server.pipeline import TTSPipeline

        pipe = TTSPipeline(skip_llm=False)
        spoken, ok, flags, meta = pipe.preprocess(METER_EN, target_lang="tanglish")
        self.assertEqual(meta.get("translator_engine"), "gold")
        self.assertTrue(ok)
        lower = spoken.lower()
        self.assertIn("kaattuthu", lower)
        self.assertIn("follow pannunga", lower)
        self.assertNotIn("aadha", lower)
        self.assertNotIn("panniten", lower)

    def test_flyover_route_exact_gold(self):
        clear_cache()
        gold = exact_gold(FLYOVER_ROUTE_EN)
        self.assertIsNotNone(gold)
        assert gold is not None
        self.assertIn("munnadi", gold.lower())
        self.assertIn("edukkardhu", gold.lower())
        self.assertIn("confirm pannunga", gold.lower())
        self.assertIn("adha vachu fare change aagum", gold.lower())
        r = translate_to_tanglish(FLYOVER_ROUTE_EN, use_cache=False)
        self.assertEqual(r.engine, "gold")

    def test_polish_flyover_route_calques(self):
        out = polish_tanglish_output(
            "Flyover ya ground route-a confirm panna, uncle, yenna fare change aagiduchu."
        ).lower()
        self.assertIn("confirm pannunga", out)
        self.assertIn("adha vachu fare change aagum", out)
        self.assertNotIn("confirm panna", out)
        self.assertNotIn("aagiduchu", out)

    def test_polish_grammar_collapse_fragment(self):
        out = polish_tanglish_output(
            "bro, meter start pannenga nu, flyover ya ground route-a enna decide panna, fare change panna."
        ).lower()
        self.assertIn("munnadi", out)
        self.assertIn("confirm pannunga", out)
        self.assertIn("adha vachu fare change aagum", out)

    def test_uncle_indicator_exact_gold(self):
        clear_cache()
        gold = exact_gold(UNCLE_INDICATOR_EN)
        self.assertIsNotNone(gold)
        assert gold is not None
        self.assertIn("uncle", gold.lower())
        self.assertIn("moonu car", gold.lower())
        self.assertIn("indicator flash pannunga", gold.lower())
        self.assertIn("theriyuradhukku", gold.lower())
        r = translate_to_tanglish(UNCLE_INDICATOR_EN, use_cache=False)
        self.assertEqual(r.engine, "gold")

    def test_polish_stripped_english_fragment(self):
        broken = (
            "Uncle, can see three cars matching description gate, so could flash "
            "indicator once so know one is?"
        )
        out = polish_tanglish_output(broken).lower()
        self.assertIn("moonu car", out)
        self.assertIn("paakuren", out)
        self.assertIn("flash pannunga", out)
        self.assertIn("theriyuradhukku", out)
        self.assertNotIn("so know one is", out)

    def test_procession_route_exact_gold(self):
        clear_cache()
        gold = exact_gold(PROCESSION_ROUTE_EN)
        self.assertIsNotNone(gold)
        assert gold is not None
        lower = gold.lower()
        self.assertIn("anna", lower)
        self.assertIn("follow pannadheenga", lower)
        self.assertIn("procession-nala", lower)
        self.assertIn("adutha oru mani neramukku", lower)
        self.assertNotIn("procession ku", lower)
        self.assertNotIn("ayya brother", lower)
        r = translate_to_tanglish(PROCESSION_ROUTE_EN, use_cache=False)
        self.assertEqual(r.engine, "gold")

    def test_polish_procession_case_marker_and_vocative(self):
        broken = (
            "Ayya brother, app sollara route-a follow pannadheenga, andha street ippo "
            "procession ku block pannirukanga, next hour-a."
        )
        out = polish_tanglish_output(broken).lower()
        self.assertIn("anna", out)
        self.assertNotIn("ayya brother", out)
        self.assertIn("procession-nala", out)
        self.assertNotIn("procession ku", out)
        self.assertIn("adutha oru mani neramukku", out)
        self.assertNotIn("next hour-a", out)

    def test_case_marker_validator_flags_procession_ku(self):
        bad = (
            "Anna, app sollara route-a follow pannadheenga, andha street ippo "
            "procession ku block pannirukanga, next hour-a."
        )
        hard, soft = check_case_markers(PROCESSION_ROUTE_EN, bad)
        self.assertIn("case_marker_wrong:procession_ku_causal", hard)
        self.assertIn("time_calque_trailing", soft)
        good = (
            "Anna, app sollara route-a follow pannadheenga, andha street-a "
            "procession-nala adutha oru mani neramukku block pannirukanga."
        )
        hard2, soft2 = check_case_markers(PROCESSION_ROUTE_EN, good)
        self.assertNotIn("case_marker_wrong:procession_ku_causal", hard2)
        self.assertNotIn("time_calque_trailing", soft2)
        self.assertNotIn("stacked_vocative", soft2)

    def test_procession_gold_matches_do_not_contraction(self):
        expanded = (
            "Brother, please do not take the route the app is showing right now, since "
            "there is a religious procession blocking that entire street for the next hour."
        )
        gold = exact_gold(expanded)
        self.assertIsNotNone(gold)
        assert gold is not None
        self.assertIn("procession-nala", gold.lower())

    def test_ollama_output_passes_validator_for_procession(self):
        from normalization.translation_validator import validate_translation

        tanglish = (
            "Anna, app sollara route-a follow pannadheenga, andha street-a "
            "procession-nala adutha oru mani neramukku block pannirukanga."
        )
        report = validate_translation(PROCESSION_ROUTE_EN, tanglish)
        self.assertNotIn("number_invented:1", report.hard_flags)
        self.assertTrue(report.ok)

    def test_to_tanglish_uses_ollama_not_english_fallback(self):
        clear_cache()
        expanded = (
            "Brother, please do not take the route the app is showing right now, since "
            "there is a religious procession blocking that entire street for the next hour."
        )
        from normalization.language_translator import to_tanglish

        out, eng = to_tanglish(expanded, "en")
        self.assertIn(eng, ("gold", "ollama", "ollama-retry1", "cache"))
        self.assertIn("pannadheenga", out.lower())
        self.assertNotIn("please do not take the route", out.lower())

    def test_fuel_gauge_exact_gold(self):
        clear_cache()
        gold = exact_gold(FUEL_GAUGE_EN)
        self.assertIsNotNone(gold)
        assert gold is not None
        lower = gold.lower()
        self.assertIn("anna", lower)
        self.assertIn("fuel gauge", lower)
        self.assertIn("kammi", lower)
        self.assertIn("petrol bunk", lower)
        self.assertIn("munnadiye sollunga", lower)
        self.assertIn("surprise aagama", lower)
        self.assertNotIn("thambi", lower)
        r = translate_to_tanglish(FUEL_GAUGE_EN, use_cache=False)
        self.assertEqual(r.engine, "gold")

    def test_malformed_ollama_garbage_rejected(self):
        garbage = (
            "annuh, enakku theri fuel gauge vera thambi irukku, aana petro bunnu "
            "pahamilla enna panni kooda, pannungala aayiram paniyama irukkenga, "
            "so aayiram paniyama iruku nu surprise panna mudiyalana."
        )
        report = validate_translation(FUEL_GAUGE_EN, garbage)
        self.assertFalse(report.ok)
        hard = " ".join(report.hard_flags)
        self.assertTrue(
            "malformed" in hard or "concept_added" in hard or "not_translated" in hard
        )

    def test_late_highway_exact_gold(self):
        clear_cache()
        gold = exact_gold(LATE_HIGHWAY_EN)
        self.assertIsNotNone(gold)
        assert gold is not None
        lower = gold.lower()
        self.assertIn("anna", lower)
        self.assertIn("raathiri aayidichu", lower)
        self.assertIn("empty-a irukku", lower)
        self.assertIn("edukalama", lower)
        self.assertIn("save aagum", lower)
        self.assertNotIn("pannuvaen", lower)
        self.assertNotIn("pannuvanga", lower)
        r = translate_to_tanglish(LATE_HIGHWAY_EN, use_cache=False)
        self.assertEqual(r.engine, "gold")

    def test_malformed_late_highway_ollama_output(self):
        garbage = (
            "Ayya, alaiyaa irukku nu late pannuvanga, streets-a mostly empty panna, "
            "usual route skip pannuvaen, highway aagum nu save time pannuven."
        )
        report = validate_translation(LATE_HIGHWAY_EN, garbage)
        self.assertFalse(report.ok)
        hard = " ".join(report.hard_flags)
        self.assertIn("malformed", hard)

    def test_polish_late_highway_calques(self):
        broken = (
            "Ayya, alaiyaa irukku nu late pannuvanga, streets-a mostly empty panna, "
            "usual route skip pannuvaen, highway aagum nu save time pannuven."
        )
        out = polish_tanglish_output(broken, source=LATE_HIGHWAY_EN).lower()
        self.assertIn("already", out)
        self.assertNotIn("alaiyaa", out)
        # State described predicatively, not performed as a future action.
        self.assertIn("empty-a irukku", out)
        self.assertIn("late-a irukku", out)
        self.assertNotIn("pannuvanga", out)
        # Polite request restored; the speaker is not announcing their own plan.
        self.assertIn("pannalama", out)
        self.assertNotIn("pannuvaen", out)
        self.assertNotIn("pannuven", out)
        self.assertIn("save aagum", out)

    def test_bridge_bumpy_exact_gold(self):
        self.assertIsNotNone(exact_gold(BRIDGE_BUMPY_EN))

    def test_malformed_bridge_bumpy_ollama_output(self):
        report = validate_translation(BRIDGE_BUMPY_EN, BRIDGE_BUMPY_BAD)
        self.assertFalse(report.ok)
        hard = " ".join(report.hard_flags)
        self.assertIn("malformed:english_chunk_collapse", hard)
        self.assertIn("malformed:invalid_ko_suffix", hard)
        self.assertIn("malformed:avoid_lost", hard)
        self.assertIn("malformed:avoid_inverted_go", hard)
        self.assertIn("malformed:concession_as_past", hard)
        self.assertIn("malformed:garbage_token:aga", hard)

    def test_polish_bridge_bumpy_partial_repair(self):
        out = polish_tanglish_output(BRIDGE_BUMPY_BAD, source=BRIDGE_BUMPY_EN).lower()
        self.assertNotIn("aga", out)
        self.assertNotIn("stretch-ko", out)
        self.assertIn("avoid pannunga", out)
        self.assertIn("vayitru romba correct-a illa", out)
        self.assertNotIn("stomach bad day", out)


if __name__ == "__main__":
    unittest.main()
