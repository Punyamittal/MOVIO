"""Tests for non-Ollama Tanglish audit (meaning + code-mix ratio)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from normalization.tanglish_audit import (  # noqa: E402
    audit_gold_corpus,
    audit_non_ollama_translation,
    code_mix_profile,
    is_ollama_engine,
)


def test_skips_ollama_engines():
    assert is_ollama_engine("ollama")
    assert is_ollama_engine("ollama-retry2")
    assert is_ollama_engine("ollama-unvalidated")
    assert is_ollama_engine("cache")
    assert audit_non_ollama_translation("hi", "vanakkam", "ollama") is None


def test_flags_english_passthrough():
    rep = audit_non_ollama_translation(
        "Your driver will arrive in five minutes.",
        "Your driver will arrive in five minutes.",
        "passthrough",
        log=False,
    )
    assert rep is not None
    assert not rep.ok
    assert any("untranslated" in f for f in rep.mix_flags)


def test_accepts_natural_tanglish_mix():
    rep = audit_non_ollama_translation(
        "Your driver will arrive in five minutes.",
        "Unga driver 5 minutes la vandhuruvaanga.",
        "gold",
        log=False,
    )
    assert rep is not None
    assert rep.ok
    assert rep.mix.tamil_ratio >= 0.45


def test_code_mix_profile_counts_tamil_stems():
    mix = code_mix_profile("Unga driver vandhuruvaanga pickup la wait pannunga.")
    assert mix.tamil_tokens >= 3
    assert mix.content_tokens >= 4


def test_gold_corpus_audit_regression():
    reports = audit_gold_corpus()
    assert len(reports) >= 270
    failures = [r for r in reports if not r.ok]
    if failures:
        sample = failures[0]
        pytest.fail(
            f"{len(failures)} gold pairs failed audit: "
            f"{sample.source!r} -> {sample.output!r} "
            f"mix_flags={sample.mix_flags} hard={sample.hard_flags}"
        )
