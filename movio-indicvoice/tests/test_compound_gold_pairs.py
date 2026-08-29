"""Gold-pair coverage for long compound passenger sentences (#2–#10)."""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from normalization.language_translator import translate  # noqa: E402
from normalization.tanglish_translator import (  # noqa: E402
    build_messages,
    call_model,
    clear_cache,
    exact_gold,
)
from normalization.translation_validator import validate_translation  # noqa: E402

_TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")

COMPOUND_SENTENCES: list[tuple[str, str, list[str]]] = [
    (
        "gold_passenger_app_driver_reached_no_car",
        "The app is showing that my driver has already reached the pickup point, but I've been standing outside for the last ten minutes and I don't see any car nearby, so I think either the GPS is showing the wrong location or he's waiting at a completely different gate.",
        ["kaattuthu", "pathu nimisham", "gps", "thappu", "gate-la wait pannuraru"],
    ),
    (
        "gold_passenger_rain_flyover_inner_road",
        "Since it's raining heavily right now and the traffic near the flyover is completely blocked because of a diversion, I think it would be better if the driver takes the inner road route instead of the main road, even if it takes a few extra minutes, because at least we won't be stuck for an hour.",
        ["mazhai", "flyover", "inner road", "main road-a vidama"],
    ),
    (
        "gold_passenger_wrong_drop_uturn",
        "I know I gave you the wrong drop location earlier by mistake, and I'm really sorry for the confusion, but if it's possible, could you please ask the driver to take a U-turn at the next signal and come back to the correct building, which is actually just two minutes away from where we currently are?",
        ["thappu drop", "u-turn", "correct building", "rendu nimisham"],
    ),
    (
        "gold_passenger_surge_toll_fare",
        "Even though the fare shown in the app before the ride started was around two hundred rupees, the driver is now saying that because of the surge pricing and the toll charges on this route, the final amount will be almost double, so I want to know if this is normal or if I should file a complaint with support.",
        ["rendu nooru", "surge pricing", "toll charge", "complaint"],
    ),
    (
        "gold_passenger_flyover_construction_service_road",
        "Please tell the driver that once he crosses the second signal, he should not take the flyover like the app is showing, because there's road construction going on up there, and instead he should continue straight on the service road until he sees a petrol bunk on the right, and take the small lane right after that.",
        ["flyover-a edukkakoodadhu", "service road", "petrol bunk", "chinna lane"],
    ),
    (
        "gold_passenger_whatsapp_live_location",
        "I understand that the driver might be new to this area, but this is the third time he's missed the turn even after I explained it clearly, so at this point I think it would be faster if I just share my live location on WhatsApp so he can follow it directly instead of relying on the app's navigation.",
        ["moonaavadhu", "whatsapp", "live location", "nambaama"],
    ),
    (
        "gold_passenger_wait_two_min_package",
        "Before you drop me off, could you please wait for exactly two minutes near the gate because I need to run inside and grab a package that I forgot, and I promise it won't take any longer than that since the security guard already has it ready at the front desk.",
        ["ennai drop", "ulle odi", "marandha package", "front desk"],
    ),
    (
        "gold_passenger_cancel_double_charge",
        "The reason I'm cancelling this ride is not because of the driver, but because the app charged me twice for the same booking, and until that refund is processed, I don't feel comfortable booking another ride using the same payment method, so I'll wait until customer support responds to my complaint.",
        ["rendu thadava charge", "refund", "payment method", "customer support"],
    ),
    (
        "gold_passenger_two_people_one_pin",
        "Since there are two of us traveling together but only one pickup pin was shared, please make sure the driver waits at the main entrance instead of the side gate, because my friend is coming from the other building and it'll be easier for both of us to meet him at one common point rather than confusing him with two different locations.",
        ["rendu per", "pickup pin", "main entrance", "side gate-a vidama"],
    ),
]


class TestCompoundGoldPairs(unittest.TestCase):
    def setUp(self) -> None:
        clear_cache()

    def test_all_compound_sentences_hit_gold(self) -> None:
        for _id, english, needles in COMPOUND_SENTENCES:
            with self.subTest(gold_id=_id):
                gold = exact_gold(english)
                self.assertIsNotNone(gold, f"missing gold for {_id}")
                assert gold is not None
                self.assertFalse(
                    _TAMIL_RE.search(gold),
                    f"Tamil script in gold {_id}: {gold!r}",
                )
                low = gold.lower()
                for needle in needles:
                    self.assertIn(needle.lower(), low, f"{_id}: expected {needle!r}")
                report = validate_translation(english, gold)
                self.assertTrue(report.ok, f"{_id}: {report.hard_flags}")

    def test_translate_uses_gold_engine(self) -> None:
        for _id, english, _ in COMPOUND_SENTENCES:
            with self.subTest(gold_id=_id):
                r = translate(english, "tanglish")
                self.assertEqual(r.engine, "gold", _id)
                self.assertFalse(_TAMIL_RE.search(r.text or ""))


def _ollama_live() -> bool:
    try:
        from config import OLLAMA_BASE_URL, TRANSLATOR_OLLAMA_ENABLED
        import requests

        if not TRANSLATOR_OLLAMA_ENABLED:
            return False
        requests.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags", timeout=3).raise_for_status()
        return True
    except Exception:
        return False


@unittest.skipUnless(_ollama_live(), "Ollama not available")
class TestCompoundOllamaBaseline(unittest.TestCase):
    """Snapshot what the raw model does WITHOUT gold (paraphrased keys)."""

    def test_model_on_paraphrase_not_in_gold(self) -> None:
        # Slight paraphrase so exact_gold does not match — shows model drift.
        english = (
            "The application says my driver already arrived at pickup, but I have "
            "waited outside ten minutes with no car visible — wrong GPS or wrong gate?"
        )
        self.assertIsNone(exact_gold(english))
        from config import TANGLISH_MODEL

        msgs = build_messages(english, examples=[])
        out, _ = call_model(
            msgs, model=TANGLISH_MODEL, source=english, temperature=0.3, timeout=90
        )
        print(f"\n[OLLAMA paraphrase]\nEN: {english}\nTA: {out}\n")
        report = validate_translation(english, out)
        # We do not assert quality — this is diagnostic only.
        self.assertTrue(len(out) > 20)
        if not report.ok:
            print(f"  validator hard_flags: {report.hard_flags}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
