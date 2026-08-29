"""Tests for the canonical Tanglish normalization spec and post-processing."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from normalization.tanglish_llm_layer import postprocess_normalize  # noqa: E402
from normalization.tanglish_normalize_spec import (  # noqa: E402
    FEW_SHOT_EXAMPLES,
    NORMALIZE_SYSTEM_PROMPT,
    build_normalize_messages,
    enforce_roman_script,
    parse_normalize_output,
)
from normalization.tanglish_style_normalizer import polish_tanglish_output  # noqa: E402
from normalization.translation_validator import check_malformed_tanglish  # noqa: E402


class TestNormalizeSpec(unittest.TestCase):
    def test_system_prompt_covers_six_rule_classes(self):
        for phrase in (
            "NEVER OUTPUT MIXED SCRIPT",
            "IMPERATIVE vs INFINITIVE",
            "CASE SUFFIXES",
            "SUBORDINATE CLAUSE",
            "CODE-MIXING",
            "REJECT / FLAG NON-WORDS",
            "NATURAL MODERN SPOKEN TANGLISH",
        ):
            self.assertIn(phrase, NORMALIZE_SYSTEM_PROMPT)

    def test_fewshot_messages_shape(self):
        msgs = build_normalize_messages("test input", ["driver", "OTP"])
        self.assertEqual(msgs[0]["role"], "system")
        self.assertEqual(msgs[-1]["role"], "user")
        self.assertIn("test input", msgs[-1]["content"])
        # system + (user+assistant)*4 fewshots + final user
        self.assertEqual(len(msgs), 1 + len(FEW_SHOT_EXAMPLES) * 2 + 1)

    def test_parse_flagged_output(self):
        raw = 'Anna, wait pannunga. [FLAGGED: unrecognized token "xyz"]'
        text, flags = parse_normalize_output(raw)
        self.assertEqual(text, "Anna, wait pannunga.")
        self.assertTrue(any(f.startswith("normalize_flagged:") for f in flags))

    def test_enforce_roman_script(self):
        mixed = "Naan know இது is strange, ஆனா AC off pannunga"
        text, flags = enforce_roman_script(mixed)
        self.assertNotRegex(text, r"[\u0B80-\u0BFF]")
        self.assertIn("tamil_script_stripped", flags)


class TestFewShotRuleAlignment(unittest.TestCase):
    """Rule-based polish/validator should implement the same fixes as the spec."""

    def test_procession_ku_to_nala(self):
        inp, _expected = FEW_SHOT_EXAMPLES[0]
        out = polish_tanglish_output(inp).lower()
        self.assertIn("procession-nala block", out)
        self.assertNotIn("procession ku block", out)

    def test_garbage_input_is_flagged_not_guessed(self):
        _, flagged = FEW_SHOT_EXAMPLES[2]
        text, flags = parse_normalize_output(flagged)
        self.assertTrue(any(f.startswith("normalize_flagged:") for f in flags))

    def test_garbage_fuel_sentence_fails_validator(self):
        garbage = FEW_SHOT_EXAMPLES[2][0]
        hard, _ = check_malformed_tanglish("", garbage)
        self.assertTrue(hard)

    def test_postprocess_runs_polish_without_llm(self):
        inp = "procession ku block pannirukanga"
        out, _ = postprocess_normalize(inp, source=inp)
        self.assertIn("procession-nala", out.lower())


if __name__ == "__main__":
    unittest.main()
