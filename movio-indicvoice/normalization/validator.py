"""
Post-LLM sanity checks before text reaches TTS.

Flags are logged to normalization/validator_flags.log — useful error-class data
for a potential future QLoRA dataset (NOT implemented here).
"""
from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import PRESERVE_ENGLISH_LIST_PATH, VALIDATOR_FLAGS_LOG  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("normalization.validator")

TAMIL_SCRIPT_RE = re.compile(r"[\u0B80-\u0BFF]+")
DIGIT_SEQ_RE = re.compile(r"\d+")

# Spoken digit words used by deterministic_normalizer
DIGIT_WORDS = {
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
}


@dataclass
class ValidationResult:
    ok: bool
    text: str
    flags: list[str] = field(default_factory=list)


def load_preserve_list(path: Path = PRESERVE_ENGLISH_LIST_PATH) -> list[str]:
    if not path.exists():
        return []
    return [str(x).strip() for x in json.loads(path.read_text(encoding="utf-8")) if str(x).strip()]


def _log_flags(original: str, output: str, flags: list[str]) -> None:
    if not flags:
        return
    VALIDATOR_FLAGS_LOG.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "original": original,
        "output": output,
        "flags": flags,
        # FUTURE QLoRA: these flagged pairs are candidate supervised examples
    }
    with VALIDATOR_FLAGS_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.warning("Validator flags: %s", flags)


def check_numeric_preservation(original: str, output: str) -> list[str]:
    """Any digit sequence in input must appear in some spoken form in output."""
    from normalization.deterministic_normalizer import cardinal_to_words, digit_by_digit

    flags = []
    digit_seqs = DIGIT_SEQ_RE.findall(original)
    if not digit_seqs:
        return flags
    out_lower = output.lower()
    out_digits = set(DIGIT_SEQ_RE.findall(output))
    for seq in digit_seqs:
        if seq in out_digits or seq in output:
            continue
        # Accept digit-by-digit spoken form
        spoken = digit_by_digit(seq)
        if spoken in out_lower:
            continue
        if all(
            ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"][int(c)]
            in out_lower
            for c in seq
        ):
            continue
        # Accept cardinal spoken form (e.g. 30 → thirty, 245 → two hundred forty five)
        try:
            card = cardinal_to_words(int(seq)).lower()
            # Normalize hyphenation / spacing variants
            card_compact = card.replace("-", " ")
            if card_compact in out_lower or all(
                tok in out_lower for tok in card_compact.split() if tok not in ("and",)
            ):
                continue
        except ValueError:
            pass
        flags.append(f"numeric_missing:{seq}")
    return flags


def check_preserve_list(original: str, output: str, preserve: list[str] | None = None) -> list[str]:
    """Confirm preserve-list terms present in input were not silently Tamil-scripted away."""
    preserve = preserve if preserve is not None else load_preserve_list()
    flags = []
    orig_lower = original.lower()
    out_lower = output.lower()
    for term in preserve:
        t = term.strip()
        if not t:
            continue
        if t.lower() not in orig_lower:
            continue
        if t.lower() in out_lower:
            continue
        # If the Latin term vanished, flag — may have been transliterated to Tamil
        flags.append(f"preserve_lost:{t}")
    return flags


def check_length_sanity(original: str, output: str, hi: float = 2.0, lo: float = 0.5) -> list[str]:
    """Flag wild length deviation (hallucination / over-translation signal)."""
    flags = []
    if not original.strip():
        return flags
    ratio = len(output) / max(len(original), 1)
    if ratio > hi:
        flags.append(f"length_too_long:ratio={ratio:.2f}")
    elif ratio < lo:
        flags.append(f"length_too_short:ratio={ratio:.2f}")
    return flags


def validate(original: str, output: str, preserve: list[str] | None = None) -> ValidationResult:
    flags: list[str] = []
    flags.extend(check_numeric_preservation(original, output))
    flags.extend(check_preserve_list(original, output, preserve))
    flags.extend(check_length_sanity(original, output))
    _log_flags(original, output, flags)
    # Soft-fail: still return output so pipeline can continue, but ok=False when flagged
    return ValidationResult(ok=len(flags) == 0, text=output, flags=flags)


if __name__ == "__main__":
    orig = "Your OTP is 4821 for the driver"
    bad = "உங்கள் ரகசிய எண் சரியாக உள்ளது"
    print(asdict(validate(orig, bad)))
    good = "Your OTP is four eight two one for the driver"
    print(asdict(validate(orig, good)))
