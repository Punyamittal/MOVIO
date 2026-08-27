"""
Scenario-based Movio acceptance tests.

Runs each scenario through the full preprocess pipeline (deterministic + optional
LLM + validator). Checks must_preserve rules programmatically where possible;
flags remaining cases for manual audio review.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import EVALUATION_RESULTS_DIR, PROJECT_ROOT, PRONUNCIATION_LEXICON_PATH  # noqa: E402
from server.pipeline import TTSPipeline  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluation.acceptance")

TESTS_PATH = PROJECT_ROOT / "evaluation" / "movio_acceptance_tests.json"

DIGIT_WORDS = {
    "0": "zero",
    "1": "one",
    "2": "two",
    "3": "three",
    "4": "four",
    "5": "five",
    "6": "six",
    "7": "seven",
    "8": "eight",
    "9": "nine",
}


def check_must_preserve(rule: str, original: str, normalized: str, lexicon: dict | None = None) -> tuple[bool | None, str]:
    """
    Returns (pass?, note).
    True/False = automatic; None = needs manual listening.
    """
    out_l = normalized.lower()
    rule_l = rule.lower()
    lexicon = lexicon or {}

    m = re.match(r"(\d+)\s+as separated digits", rule_l)
    if m:
        digits = m.group(1)
        spoken = " ".join(DIGIT_WORDS[d] for d in digits)
        ok = all(DIGIT_WORDS[d] in out_l for d in digits) or spoken in out_l
        return ok, f"digit-by-digit check for {digits}"

    if "as separated letters/digits" in rule_l:
        token = rule.split()[0]
        chars = re.findall(r"[A-Za-z0-9]", token)
        ok = all(
            (c.lower() in out_l) or (c.isdigit() and DIGIT_WORDS[c] in out_l)
            for c in chars
        )
        return ok, f"plate/id expansion check for {token}"

    # Simple English loanword / place-name Latin preservation
    if rule.lower() in original.lower():
        if rule.lower() in out_l:
            return True, f"latin term preserved: {rule}"
        # Accept pronunciation-lexicon substitution (e.g. Guindy → கிண்டி)
        mapped = None
        for k, v in lexicon.items():
            if k.startswith("_") or not str(v).strip():
                continue
            if k.lower() == rule.lower():
                mapped = str(v).strip()
                break
        if mapped and mapped.lower() in out_l:
            return True, f"lexicon pronunciation applied for {rule} → {mapped}"
        return False, f"latin term missing in output: {rule}"

    return None, f"manual review suggested for rule: {rule}"


def run_acceptance(synthesize_audio: bool = False) -> dict:
    scenarios = json.loads(TESTS_PATH.read_text(encoding="utf-8"))
    lexicon = {}
    if PRONUNCIATION_LEXICON_PATH.exists():
        lexicon = json.loads(PRONUNCIATION_LEXICON_PATH.read_text(encoding="utf-8"))
    # skip_llm=True keeps acceptance deterministic offline; set False when Ollama is up
    pipe = TTSPipeline(skip_llm=True)

    auto_pass = 0
    auto_fail = 0
    manual = 0
    details = []

    for sc in scenarios:
        text = sc["input"]
        if synthesize_audio:
            result = pipe.run(text)
            normalized = result.normalized_text
        else:
            normalized, v_ok, flags = pipe.preprocess(text)
            _ = (v_ok, flags)

        rule_results = []
        needs_manual = False
        failed = False
        for rule in sc.get("must_preserve", []):
            ok, note = check_must_preserve(rule, text, normalized, lexicon=lexicon)
            rule_results.append({"rule": rule, "ok": ok, "note": note})
            if ok is None:
                needs_manual = True
            elif ok is False:
                failed = True

        if failed:
            status = "FAIL"
            auto_fail += 1
        elif needs_manual:
            status = "MANUAL"
            manual += 1
        else:
            status = "PASS"
            auto_pass += 1

        details.append(
            {
                "id": sc["id"],
                "category": sc.get("category"),
                "input": text,
                "normalized": normalized,
                "status": status,
                "rules": rule_results,
                "expected_behavior": sc.get("expected_behavior"),
            }
        )

    total = len(scenarios)
    summary_line = (
        f"{auto_pass}/{total} acceptance scenarios passed automatically, "
        f"{manual} require manual listening"
        + (f", {auto_fail} failed" if auto_fail else "")
        + "."
    )
    report = {
        "summary": summary_line,
        "auto_pass": auto_pass,
        "auto_fail": auto_fail,
        "manual_review": manual,
        "total": total,
        "details": details,
    }
    EVALUATION_RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = EVALUATION_RESULTS_DIR / "acceptance_results.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info(summary_line)
    print(summary_line)
    return report


if __name__ == "__main__":
    run_acceptance(synthesize_audio=False)
