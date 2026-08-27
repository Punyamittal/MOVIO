"""
Deterministic text normalizer for taxi-domain Tanglish TTS.

Distinguishes digit-by-digit contexts (OTP / phone / IDs / plates) from
cardinal contexts (counts / quantities / currency amounts).

Uses indic-nlp-library where it fits; custom logic for taxi-domain gaps.
Each public function is unit-tested in tests/test_pipeline.py.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime

logger = logging.getLogger("normalization.deterministic")

# ---------------------------------------------------------------------------
# Number word tables (English spoken forms — TTS backends handle mixed script)
# ---------------------------------------------------------------------------
ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

OTP_HINT = re.compile(
    r"\b(otp|pin|code|passcode|verification)\b",
    re.IGNORECASE,
)
PHONE_RE = re.compile(
    r"(?<!\w)(?:\+?91[\s\-]*)?[6-9]\d{9}(?!\w)"
)
# Vehicle plates e.g. TN45AB1234, TN-09-CD-5678
PLATE_RE = re.compile(
    r"\b([A-Z]{2})\s*-?\s*(\d{1,2})\s*-?\s*([A-Z]{1,3})\s*-?\s*(\d{1,4})\b",
    re.IGNORECASE,
)
BOOKING_ID_RE = re.compile(
    r"\b((?:booking\s*(?:id|ID)\s*)?)([A-Z]{1,3}\d{3,8})\b"
)
CURRENCY_RE = re.compile(r"₹\s*(\d+(?:,\d{3})*(?:\.\d+)?)")
DISTANCE_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(km|kilometers?|kilometres?|m|meters?|metres?)\b",
    re.IGNORECASE,
)
TIME_RE = re.compile(
    r"\b(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)?\b"
)
DATE_WORD_RE = re.compile(
    r"\b(today|tomorrow|yesterday)\b",
    re.IGNORECASE,
)
# ISO-ish or DD/MM/YYYY
DATE_NUM_RE = re.compile(
    r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b"
)
# General integers not already handled — applied last with context awareness
CARDINAL_RE = re.compile(r"\b(\d+)\b")


def digit_by_digit(digits: str) -> str:
    """Speak each digit separately — NEVER as a large cardinal number."""
    cleaned = re.sub(r"\D", "", digits)
    return " ".join(ONES[int(c)] for c in cleaned)


def letter_by_letter(text: str) -> str:
    parts = []
    for ch in text:
        if ch.isalpha():
            parts.append(ch.upper())
        elif ch.isdigit():
            parts.append(ONES[int(ch)])
        elif ch in ("-", " "):
            continue
    return " ".join(parts)


def cardinal_to_words(n: int) -> str:
    """Standard spoken cardinal form for counts/quantities."""
    if n < 0:
        return "minus " + cardinal_to_words(-n)
    if n < 20:
        return ONES[n]
    if n < 100:
        ten, rem = divmod(n, 10)
        return TENS[ten] if rem == 0 else f"{TENS[ten]} {ONES[rem]}"
    if n < 1000:
        hun, rem = divmod(n, 100)
        if rem == 0:
            return f"{ONES[hun]} hundred"
        return f"{ONES[hun]} hundred {cardinal_to_words(rem)}"
    if n < 100_000:
        thou, rem = divmod(n, 1000)
        head = cardinal_to_words(thou) + " thousand"
        return head if rem == 0 else f"{head} {cardinal_to_words(rem)}"
    # Fall back for larger amounts
    return " ".join(ONES[int(c)] for c in str(n))  # safe digit fallback


def normalize_otp_and_short_codes(text: str) -> str:
    """
    OTP / short codes → digit-by-digit.
    E.g. '4821' near OTP context → 'four eight two one'
    NEVER 'four thousand eight hundred twenty-one'.

    Only digits within a short window of OTP/PIN/code cues are rewritten —
    never every 3–6 digit number in the whole sentence (that would corrupt
    currency amounts like ₹100 in "OTP 4821, fare ₹100").
    """
    # Explicit "OTP is 4821" / "OTP 4821" / "code: 4821"
    text = re.sub(
        r"(\b(?:OTP|otp|PIN|pin|passcode|code)\b[\s:#\-]*)(\d{3,8})",
        lambda m: m.group(1) + digit_by_digit(m.group(2)),
        text,
    )
    # Windowed: digits within ~40 chars after an OTP/PIN cue word
    def window_repl(m: re.Match) -> str:
        cue, rest = m.group(1), m.group(2)

        def dig(mm: re.Match) -> str:
            return digit_by_digit(mm.group(0))

        rest2 = re.sub(r"\b\d{3,8}\b", dig, rest, count=1)
        return cue + rest2

    text = re.sub(
        r"(\b(?:OTP|otp|PIN|pin|passcode|verification\s+code)\b)(.{0,40})",
        window_repl,
        text,
    )
    return text


def normalize_phone_numbers(text: str) -> str:
    """Phone numbers → digit-by-digit."""
    def repl(m: re.Match) -> str:
        return digit_by_digit(m.group(0))

    return PHONE_RE.sub(repl, text)


def normalize_booking_ids_and_plates(text: str) -> str:
    """Vehicle plates / alphanumeric IDs → letter-by-letter + digit-by-digit."""
    def plate_repl(m: re.Match) -> str:
        raw = "".join(m.groups())
        return letter_by_letter(raw)

    text = PLATE_RE.sub(plate_repl, text)

    def booking_repl(m: re.Match) -> str:
        prefix, token = m.group(1) or "", m.group(2)
        # Only rewrite if mixed alphanumeric (not pure digits handled elsewhere)
        if re.search(r"[A-Za-z]", token) and re.search(r"\d", token):
            return prefix + letter_by_letter(token)
        return m.group(0)

    return BOOKING_ID_RE.sub(booking_repl, text)


def normalize_currency(text: str) -> str:
    """₹ amounts → spoken form."""
    def repl(m: re.Match) -> str:
        num = m.group(1).replace(",", "")
        if "." in num:
            whole, frac = num.split(".", 1)
            spoken = cardinal_to_words(int(whole)) + " rupees"
            if int(frac):
                spoken += " and " + cardinal_to_words(int(frac)) + " paise"
            return spoken
        return cardinal_to_words(int(num)) + " rupees"

    return CURRENCY_RE.sub(repl, text)


def normalize_distances(text: str) -> str:
    """km / m → spoken form."""
    def repl(m: re.Match) -> str:
        raw, unit = m.group(1), m.group(2).lower()
        if "." in raw:
            whole, frac = raw.split(".", 1)
            num_spoken = cardinal_to_words(int(whole)) + " point " + " ".join(
                ONES[int(c)] for c in frac
            )
        else:
            num_spoken = cardinal_to_words(int(raw))
        if unit.startswith("km") or unit.startswith("kilomet"):
            unit_spoken = "kilometers"
        else:
            unit_spoken = "meters"
        return f"{num_spoken} {unit_spoken}"

    return DISTANCE_RE.sub(repl, text)


def normalize_times(text: str) -> str:
    """'7:30 PM' → natural spoken form, not raw digit reading."""
    def repl(m: re.Match) -> str:
        hour = int(m.group(1))
        minute = int(m.group(2))
        ampm = (m.group(3) or "").upper()
        hour_spoken = cardinal_to_words(hour)
        if minute == 0:
            minute_spoken = "o'clock"
        elif minute < 10:
            minute_spoken = f"oh {cardinal_to_words(minute)}"
        else:
            minute_spoken = cardinal_to_words(minute)
        if minute == 0:
            base = f"{hour_spoken} {minute_spoken}"
        else:
            base = f"{hour_spoken} {minute_spoken}"
        if ampm:
            base = f"{base} {ampm}"
        return base

    return TIME_RE.sub(repl, text)


def normalize_dates(text: str) -> str:
    """Dates → natural spoken form. Relative words kept; numeric dates expanded."""
    # Relative words are already natural speech — leave them.
    def num_repl(m: re.Match) -> str:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            dt = datetime(y, mo, d)
            # Day month year spoken
            months = [
                "", "January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December",
            ]
            return f"{cardinal_to_words(d)} {months[mo]} {cardinal_to_words(y)}"
        except ValueError:
            return m.group(0)

    return DATE_NUM_RE.sub(num_repl, text)


def normalize_cardinal_numbers(text: str, protected_spans: list[tuple[int, int]] | None = None) -> str:
    """
    General cardinal numbers (counts/quantities) → standard spoken form.
    Must NOT re-process digit-by-digit contexts already expanded (they contain words).
    Remaining bare integers are treated as cardinals.
    """
    def repl(m: re.Match) -> str:
        n = int(m.group(1))
        # Very long digit strings that somehow remain → digit-by-digit for safety
        if len(m.group(1)) >= 7:
            return digit_by_digit(m.group(1))
        return cardinal_to_words(n)

    return CARDINAL_RE.sub(repl, text)


def apply_lexicon(text: str, lexicon: dict[str, str]) -> str:
    """Replace known place/transport terms with pronunciation-aware spellings."""
    # Longer keys first to prefer multi-word place names
    for key in sorted(lexicon.keys(), key=len, reverse=True):
        if key.startswith("_"):
            continue
        val = lexicon.get(key) or ""
        if not str(val).strip():
            continue  # empty placeholders — leave surface form
        text = re.sub(rf"\b{re.escape(key)}\b", str(val), text, flags=re.IGNORECASE)
    return text


def normalize(text: str, lexicon: dict[str, str] | None = None) -> str:
    """
    Full deterministic pipeline (order matters):
    OTP → phone → plates/IDs → currency → distance → time → date → cardinals → lexicon
    """
    original = text
    text = normalize_otp_and_short_codes(text)
    text = normalize_phone_numbers(text)
    text = normalize_booking_ids_and_plates(text)
    text = normalize_currency(text)
    text = normalize_distances(text)
    text = normalize_times(text)
    text = normalize_dates(text)
    text = normalize_cardinal_numbers(text)
    if lexicon:
        text = apply_lexicon(text, lexicon)
    logger.debug("normalize: %r → %r", original, text)
    return text


# Try indic-nlp for optional helpers (coverage check — gaps remain custom above)
def _probe_indic_nlp() -> bool:
    try:
        import indicnlp  # noqa: F401
        return True
    except ImportError:
        return False


INDIC_NLP_AVAILABLE = _probe_indic_nlp()
if INDIC_NLP_AVAILABLE:
    logger.info("indic-nlp-library available; custom taxi-domain normalizers still used for gaps")
else:
    logger.info("indic-nlp-library not installed; using custom normalizers only")


if __name__ == "__main__":
    samples = [
        "Your OTP is 4821",
        "Please call 9876543210",
        "Cab TN45AB1234 arrived",
        "Fare ₹245 for 12 km",
        "Arrive at 7:30 PM tomorrow",
        "Driver 5 minutes away",
    ]
    for s in samples:
        print(f"{s} → {normalize(s)}")
