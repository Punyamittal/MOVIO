"""
Adversarial + consecutive-request tests for English → Tanglish.

These catch the failure mode that motivated the rewrite:

  - inventing OTP / parking / cab / minutes when the source never said them
  - leaking concepts from a previous utterance into the next
  - dropping or mutating numbers, OTPs, times and place names

Run:
  pytest tests/test_tanglish_translation.py -q
  python -m tests.test_tanglish_translation
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from normalization.language_translator import translate  # noqa: E402
from normalization.tanglish_translator import (  # noqa: E402
    build_messages,
    clear_cache,
    exact_gold,
    retrieve_examples,
    translate_to_tanglish,
)
from normalization.translation_validator import (  # noqa: E402
    concepts_in,
    validate_translation,
)

# ---------------------------------------------------------------------------
# Pure-logic tests — no Ollama required
# ---------------------------------------------------------------------------


class TestValidatorCatchesReportedBug(unittest.TestCase):
    def test_rejects_reported_hallucination(self):
        source = "I am standing near the security gate with a red suitcase."
        bad = (
            "En, nammal aana security gate la neerla suitcase irukku, driver aana "
            "opposite side la road la, aana turn around pannunga, main entrance la "
            "come pannunga, OTP la send pannunga, cab la waiting pannunga, parking "
            "la find pannunga, minutes la wait pannunga."
        )
        report = validate_translation(source, bad)
        self.assertFalse(report.ok)
        hard = " ".join(report.hard_flags)
        self.assertIn("concept_added:otp", hard)
        self.assertIn("concept_added:parking", hard)
        self.assertIn("concept_added:cab", hard)

    def test_accepts_faithful_tanglish(self):
        source = "I am standing near the security gate with a red suitcase."
        good = "Naan security gate pakkathula red suitcase-oda nikkiren."
        report = validate_translation(source, good)
        self.assertTrue(report.ok, report.flags)

    def test_otp_must_preserve_digits(self):
        report = validate_translation("The OTP is 4821.", "OTP 7392.")
        self.assertFalse(report.ok)
        self.assertTrue(any("number" in f for f in report.hard_flags))

    def test_location_must_not_swap(self):
        report = validate_translation(
            "The driver is waiting near Guindy.",
            "Driver Velachery pakkathula wait pannitu irukkaaru.",
        )
        self.assertFalse(report.ok)
        hard = " ".join(report.hard_flags)
        self.assertTrue("name_invented:velachery" in hard or "name_missing:guindy" in hard)

    def test_parking_allowed_when_in_source(self):
        report = validate_translation(
            "I am waiting near the parking entrance.",
            "Naan parking entrance pakkathula wait pannitu irukken.",
        )
        self.assertTrue(report.ok, report.flags)
        self.assertNotIn("concept_added:parking", " ".join(report.hard_flags))


class TestStatelessPrompt(unittest.TestCase):
    def test_prompt_built_from_current_utterance_only(self):
        msgs = build_messages(
            "I need to reach the airport.",
            examples=[("The driver has arrived.", "Driver vandhutaanga.")],
        )
        # User-role contents must not contain leftover previous-utterance matter.
        user_blob = " ".join(m["content"] for m in msgs if m["role"] == "user")
        self.assertNotIn("OTP 4821", user_blob)
        self.assertNotIn("security gate", user_blob)
        self.assertIn("I need to reach the airport.", user_blob)
        # Assistant few-shot is only the examples we passed — not prior calls.
        asst = [m["content"] for m in msgs if m["role"] == "assistant"]
        self.assertEqual(asst, ["Driver vandhutaanga."])

    def test_retry_never_feeds_bad_output_back(self):
        msgs = build_messages(
            "I need to reach the airport.",
            examples=[],
            retry_reason="you introduced 'OTP', which the source never mentions",
        )
        blob = " ".join(m["content"] for m in msgs)
        # The failed candidate text itself must never reappear.
        self.assertNotIn("OTP la send", blob)
        self.assertIn("I need to reach the airport.", blob)
        self.assertIn("Do not add any new information", blob)

    def test_examples_retrieved_from_current_sentence_only(self):
        clear_cache()
        a = retrieve_examples("Please share the OTP 4821.", k=3)
        b = retrieve_examples("I need to reach the airport.", k=3)
        # Different inputs must produce different retrieval sets — otherwise
        # previous-turn residue is sneaking into few-shot selection.
        self.assertNotEqual(a, b)

    def test_exact_gold_is_instant(self):
        # Prefer a known gold pair if present; otherwise skip.
        gold = exact_gold(
            "I am waiting outside the hotel lobby, and the driver is standing "
            "near the parking entrance, but neither of us can see the other."
        )
        if gold is None:
            self.skipTest("gold pair not present in this checkout")
        self.assertTrue(len(gold) > 10)


# ---------------------------------------------------------------------------
# Live Ollama tests — skipped when the translator is disabled or Ollama is down
# ---------------------------------------------------------------------------


def _ollama_live() -> bool:
    try:
        from config import TRANSLATOR_OLLAMA_ENABLED
        import requests
        from config import OLLAMA_BASE_URL

        if not TRANSLATOR_OLLAMA_ENABLED:
            return False
        requests.get(f"{OLLAMA_BASE_URL.rstrip('/')}/api/tags", timeout=2).raise_for_status()
        return True
    except Exception:
        return False


@unittest.skipUnless(_ollama_live(), "Ollama / Tanglish translator not available")
class TestAdversarialLive(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        clear_cache()

    def _translate(self, text: str) -> str:
        r = translate_to_tanglish(text, use_cache=False)
        return r.text

    def test_security_gate_no_hallucination(self):
        src = "I am standing near the security gate with a red suitcase."
        out = self._translate(src)
        report = validate_translation(src, out)
        hard = " ".join(report.hard_flags)
        for banned in ("otp", "parking", "cab", "minutes"):
            self.assertNotIn(f"concept_added:{banned}", hard, f"out={out!r}")
        self.assertIn("security", out.lower())
        self.assertIn("suitcase", out.lower())

    def test_driver_five_minutes(self):
        src = "The driver will arrive in five minutes."
        out = self._translate(src)
        report = validate_translation(src, out)
        hard = " ".join(report.hard_flags)
        self.assertNotIn("concept_added:otp", hard, out)
        self.assertNotIn("concept_added:parking", hard, out)
        low = out.lower()
        self.assertTrue("driver" in low)
        self.assertTrue("5" in out or "five" in low or "anju" in low)

    def test_otp_4821_preserved(self):
        src = "Please share the OTP 4821."
        out = self._translate(src)
        self.assertIn("4821", out)
        self.assertIn("otp", out.lower())
        report = validate_translation(src, out)
        self.assertNotIn("number_invented", " ".join(report.hard_flags), out)

    def test_parking_entrance_ok(self):
        src = "I am waiting near the parking entrance."
        out = self._translate(src)
        self.assertIn("parking", out.lower())
        report = validate_translation(src, out)
        self.assertNotIn("concept_added:otp", " ".join(report.hard_flags), out)

    def test_guindy_not_velachery(self):
        src = "The driver is waiting near Guindy."
        out = self._translate(src)
        self.assertIn("guindy", out.lower())
        self.assertNotIn("velachery", out.lower())

    def test_airport_time_preserved(self):
        src = "I need to reach the airport before 7:30 PM."
        out = self._translate(src)
        low = out.lower()
        self.assertIn("airport", low)
        # Accept 7:30 / 7.30 / 730 with PM nearby — but not a swapped time.
        self.assertTrue(
            "7:30" in out or "7.30" in out or ("7" in out and "30" in out),
            f"time lost: {out!r}",
        )
        report = validate_translation(src, out)
        self.assertNotIn("concept_added:otp", " ".join(report.hard_flags), out)
        self.assertNotIn("concept_added:driver", " ".join(report.hard_flags), out)

    def test_long_sentence_semantic_content(self):
        src = (
            "I'm standing near the security gate with a red suitcase, but the "
            "driver has stopped on the opposite side of the road, so please ask "
            "him to turn around and come to the main entrance."
        )
        out = self._translate(src)
        low = out.lower()
        for must in ("security", "suitcase", "driver", "main entrance"):
            self.assertIn(must, low, f"missing {must!r} in {out!r}")
        report = validate_translation(src, out)
        hard = " ".join(report.hard_flags)
        for banned in ("otp", "parking", "cab"):
            self.assertNotIn(f"concept_added:{banned}", hard, out)


@unittest.skipUnless(_ollama_live(), "Ollama / Tanglish translator not available")
class TestConsecutiveIndependentRequests(unittest.TestCase):
    """Each request must only represent its own input — no context leakage."""

    SEQUENCE = [
        "The driver has arrived.",
        "I am waiting near the security gate.",
        "The OTP is 4821.",
        "I need to reach the airport.",
        "Please wait for five minutes.",
    ]

    # Concepts that must NOT appear unless the current source mentions them.
    SENSITIVE = ("otp", "driver", "security", "gate", "airport", "minutes", "parking", "cab")

    def test_no_cross_request_leakage(self):
        clear_cache()
        previous_concepts: set[str] = set()
        for src in self.SEQUENCE:
            res = translate_to_tanglish(src, use_cache=False)
            out = res.text
            src_concepts = concepts_in(src)
            out_low = out.lower()

            # Nothing from a previous request may appear unless it is also in
            # THIS source.
            for concept in previous_concepts:
                if concept in src_concepts:
                    continue
                # Soft concept words can appear as particles; check high-risk only.
                if concept in ("otp", "parking", "cab", "driver", "airport"):
                    forms = {
                        "otp": ("otp",),
                        "parking": ("parking",),
                        "cab": (" cab ", "taxi"),
                        "driver": ("driver",),
                        "airport": ("airport",),
                    }.get(concept, (concept,))
                    for form in forms:
                        self.assertNotIn(
                            form,
                            f" {out_low} ",
                            f"leakage of {concept!r} from earlier request into "
                            f"source={src!r} out={out!r}",
                        )

            report = validate_translation(src, out)
            hard = " ".join(report.hard_flags)
            for banned in ("otp", "parking", "cab", "driver", "minutes", "airport"):
                if banned in src_concepts:
                    continue
                self.assertNotIn(
                    f"concept_added:{banned}",
                    hard,
                    f"source={src!r} out={out!r}",
                )

            previous_concepts |= src_concepts


@unittest.skipUnless(_ollama_live(), "Ollama / Tanglish translator not available")
class TestPipelineRouting(unittest.TestCase):
    def test_translate_entry_uses_new_engine(self):
        clear_cache()
        r = translate(
            "I am standing near the security gate with a red suitcase.",
            target_lang="tanglish",
        )
        self.assertIn(r.engine, ("ollama", "ollama-retry1", "ollama-retry2", "gold", "cache"))
        self.assertNotEqual(r.engine, "offline-lexicon-weak")
        low = r.text.lower()
        self.assertNotIn("otp la send", low)
        self.assertNotIn("cab la waiting", low)


if __name__ == "__main__":
    unittest.main()
