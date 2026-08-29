"""
Generalisation tests for the Tanglish grammar layer.

The point of these is that none of the sentences below are gold pairs and none
are hardcoded in the rule tables. They are paraphrases of error classes seen in
production, so they only pass if the rules reason about verb form and case
suffix rather than matching remembered text.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import TANGLISH_GOLD_PAIRS_PATH  # noqa: E402
from normalization import tanglish_morphology as morphology  # noqa: E402
from normalization.tanglish_style_normalizer import polish_tanglish_output  # noqa: E402
from normalization.translation_validator import (  # noqa: E402
    check_malformed_tanglish,
    validate_translation,
)


class TestGoldCorpusIsAccepted(unittest.TestCase):
    """The validator must never reject a human-verified translation.

    Every rejected gold pair is a sentence where correct Ollama output would
    also be thrown away and replaced by English passthrough.
    """

    def test_every_gold_pair_validates(self):
        rows = json.loads(Path(TANGLISH_GOLD_PAIRS_PATH).read_text(encoding="utf-8"))
        self.assertGreater(len(rows), 200)
        rejected = [
            (row["id"], validate_translation(row["english"], row["tanglish"]).hard_flags)
            for row in rows
            if not validate_translation(row["english"], row["tanglish"]).ok
        ]
        self.assertEqual(rejected, [], f"validator rejects gold pairs: {rejected}")


class TestVerbFormGeneralisation(unittest.TestCase):
    def test_clause_final_infinitive_rejected(self):
        source = "Please drop me near the second gate."
        output = "Anna, rendaavadhu gate pakkathula drop panna."
        hard, _ = check_malformed_tanglish(source, output)
        self.assertIn("malformed:bare_infinitive_clause_final", hard)

    def test_infinitive_inside_clause_allowed(self):
        source = "Please tell the driver to wait near the gate."
        output = "Gate pakkathula wait panna driver-kitta sollunga."
        hard, _ = check_malformed_tanglish(source, output)
        self.assertNotIn("malformed:bare_infinitive_clause_final", hard)

    def test_first_person_future_needs_first_person_source(self):
        source = "Could you take the bypass instead of the service road?"
        output = "Service road-a vidama bypass edukka pannuven."
        hard, _ = check_malformed_tanglish(source, output)
        self.assertIn("malformed:person_1sg_future", hard)

    def test_first_person_future_allowed_when_source_says_i_will(self):
        source = "I will come out of the lobby as soon as the driver arrives."
        output = "Driver vandhadhum naan lobby-la irundhu veliya vandhuruven."
        hard, _ = check_malformed_tanglish(source, output)
        self.assertNotIn("malformed:person_1sg_future", hard)

    def test_first_person_future_allowed_in_reported_speech(self):
        source = "The driver said he would reach in ten minutes."
        output = "Driver ten minutes-la reach aagiduven-nu sonnaaru."
        hard, _ = check_malformed_tanglish(source, output)
        self.assertNotIn("malformed:person_1sg_future", hard)

    def test_kinship_insert_caught_with_case_suffix(self):
        source = "The lane next to the fuel pump is completely blocked."
        output = "Fuel pump pakkathula lane-a thambiya block pannirukanga."
        hard, _ = check_malformed_tanglish(source, output)
        self.assertIn("malformed:kinship_insert:thambi", hard)

    def test_pannanga_normalised_to_polite_imperative(self):
        source = "Please wait five minutes near the main gate."
        out = polish_tanglish_output(
            "Ainthu nimisham main gate pakkathula wait pannanga.", source=source
        ).lower()
        self.assertIn("wait pannunga", out)
        self.assertNotIn("pannanga", out)

    def test_invalid_ko_suffix_rejected(self):
        source = "Please avoid the narrow lane near the school."
        output = "School pakkathula narrow lane-ko po."
        hard, _ = check_malformed_tanglish(source, output)
        self.assertIn("malformed:invalid_ko_suffix", hard)

    def test_english_chunk_collapse_rejected(self):
        source = "My stomach isn't feeling well today."
        output = "Anna, my stomach bad day irukku."
        hard, _ = check_malformed_tanglish(source, output)
        self.assertIn("malformed:english_chunk_collapse", hard)

    def test_avoid_must_not_invert_to_go(self):
        source = "Please avoid the bumpy stretch on this road."
        output = "Anna, andha bumpy stretch-ko po nu nenaikkuren."
        hard, _ = check_malformed_tanglish(source, output)
        self.assertIn("malformed:avoid_lost", hard)
        self.assertIn("malformed:avoid_inverted_go", hard)

    def test_concession_not_past_tense_pona(self):
        source = "I know the bridge road is faster, but please take the inner route."
        output = "Anna, bridge road pona, aana inner route edunga."
        hard, _ = check_malformed_tanglish(source, output)
        self.assertIn("malformed:concession_as_past", hard)

    def test_state_cannot_be_performed(self):
        source = "The road ahead is completely blocked right now."
        output = "Munnadi road ippo blocked pannuvanga."
        hard, _ = check_malformed_tanglish(source, output)
        self.assertIn("malformed:state_as_action", hard)

    def test_habitual_plural_is_not_an_error(self):
        source = "Children usually cross the road around this time."
        output = "Indha time-la usually kuzhandhaikal road cross pannuvanga."
        hard, _ = check_malformed_tanglish(source, output)
        self.assertEqual(hard, [])

    def test_polite_request_must_keep_request_mood(self):
        source = "Could you please wait near the main entrance for two minutes?"
        output = "Main entrance pakkathula rendu nimisham naan wait pannitu irukken."
        hard, _ = check_malformed_tanglish(source, output)
        self.assertIn("malformed:mood_suggestion_lost", hard)

    def test_short_imperative_counts_as_request_mood(self):
        source = "Could you take an alternate route to avoid the flooding?"
        output = "Flood-a avoid panna alternate route edunga."
        hard, _ = check_malformed_tanglish(source, output)
        self.assertNotIn("malformed:mood_suggestion_lost", hard)

    def test_question_particle_counts_as_request_mood(self):
        source = "Could you send me the receipt over email as well?"
        output = "Receipt-a email-lakum anupungala."
        hard, _ = check_malformed_tanglish(source, output)
        self.assertNotIn("malformed:mood_suggestion_lost", hard)


class TestPolishGeneralisation(unittest.TestCase):
    """Repairs must fire on paraphrases, and must not invent content."""

    def test_predicative_repair_on_unseen_sentence(self):
        source = "Could you use the bypass since the lanes are mostly empty right now?"
        broken = "Anna, lanes-a mostly empty panna, service road skip pannuvaen."
        out = polish_tanglish_output(broken, source=source).lower()
        self.assertIn("lanes-um mostly empty-a irukku", out)
        self.assertIn("pannalama", out)
        self.assertNotIn("pannuvaen", out)

    def test_causal_suffix_repair_on_unseen_noun(self):
        source = "The lane is blocked because of a wedding party right now."
        broken = "Andha lane ippo wedding ku block pannirukanga."
        out = polish_tanglish_output(broken, source=source).lower()
        self.assertIn("wedding-nala block", out)
        self.assertNotIn("wedding ku block", out)

    def test_repair_does_not_invent_content(self):
        source = "Could you skip the service road, since it is quite late?"
        broken = "Anna, late pannuvanga, service road skip pannuvaen."
        out = polish_tanglish_output(broken, source=source).lower()
        # The old memorised rule injected "highway" and "romba raathiri" here.
        self.assertNotIn("highway", out)
        self.assertNotIn("raathiri", out)
        self.assertIn("service road", out)

    def test_statement_source_keeps_first_person_future(self):
        source = "I will walk the rest of the way from the corner."
        text = "Corner-la irundhu baaki naan nadanthu poiduven."
        out = polish_tanglish_output(text, source=source).lower()
        self.assertIn("poiduven", out)


class TestSourceMood(unittest.TestCase):
    def test_suggestion_detection(self):
        self.assertTrue(morphology.is_suggestion("Would it be okay to take the highway?"))
        self.assertTrue(morphology.is_suggestion("Could you stop near the signal?"))
        self.assertFalse(morphology.is_suggestion("The driver has already arrived."))

    def test_first_person_future_detection(self):
        self.assertTrue(morphology.source_allows_first_sg_future("I will cross over now."))
        self.assertTrue(morphology.source_allows_first_sg_future("I can walk from here."))
        self.assertFalse(
            morphology.source_allows_first_sg_future("The streets are mostly empty.")
        )


if __name__ == "__main__":
    unittest.main()
