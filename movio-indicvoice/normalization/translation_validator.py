"""
Semantic validation for English → Tanglish translations.

Answers one question: *does this Tanglish sentence say what the English
sentence said, and nothing more?*

The checks compare source and output rather than filtering the output against
a blacklist. A word like "parking" is only a problem when the source never
mentioned parking; deleting it blindly would break the many utterances that
legitimately talk about parking.

Flags are split into two severities:

  HARD  meaning was changed — invented concepts, wrong/missing entities,
        repetition loops, empty or untranslated output. Worth a retry.
  SOFT  stylistic or length signals. Recorded for debugging, never a retry
        on their own, because natural Tanglish varies in length and word
        count and over-correcting it produces stilted speech.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    TANGLISH_EXPANSION_RATIO,
    TANGLISH_REPEAT_LIMIT,
    TANGLISH_SHRINK_RATIO,
)

# ---------------------------------------------------------------------------
# Tokenisation
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[A-Za-z\u0B80-\u0BFF]+")
_NUM_RE = re.compile(r"\d+")
_TIME_RE = re.compile(r"\b(\d{1,2})[:.](\d{2})\s*(a\.?m\.?|p\.?m\.?)?", re.I)
_CODE_RE = re.compile(r"\b[A-Z]{2,3}[\s-]?\d{1,2}[\s-]?[A-Z]{1,2}[\s-]?\d{3,4}\b")

# Tanglish grammatical suffixes glued onto loanwords: gate-la, driver-kitta,
# entrance-ku, suitcase-oda. Stripped so concept matching sees the stem.
_SUFFIXES = (
    "kitta",
    "kulla",
    "vukku",
    "ukku",
    "oda",
    "aana",
    "aaga",
    "ula",
    "la",
    "ku",
    "va",
    "ah",
    "aa",
    "um",
    "nu",
    "in",
    "a",
)

# English number words and their Chennai-Tamil spoken equivalents, so
# "five minutes" → "anju minutes" is not read as a lost number.
_NUMBER_WORDS: dict[str, str] = {
    "zero": "0",
    "one": "1",
    "onnu": "1",
    "oru": "1",
    "two": "2",
    "rendu": "2",
    "renda": "2",
    "three": "3",
    "moonu": "3",
    "muunu": "3",
    "four": "4",
    "naalu": "4",
    "naaku": "4",
    "five": "5",
    "anju": "5",
    "ainthu": "5",
    "six": "6",
    "aaru": "6",
    "seven": "7",
    "ezhu": "7",
    "eight": "8",
    "ettu": "8",
    "nine": "9",
    "onbadhu": "9",
    "ten": "10",
    "pathu": "10",
    "twenty": "20",
    "thirty": "30",
    "forty": "40",
    "fifty": "50",
    "hundred": "100",
}

# Capitalised words that are not place/person names.
_NOT_A_NAME = frozenset(
    {
        "i", "i'm", "im", "the", "a", "an", "and", "but", "so", "or", "if",
        "please", "my", "me", "he", "she", "it", "they", "we", "you", "your",
        "his", "her", "their", "our", "this", "that", "there", "here", "am",
        "is", "are", "was", "were", "be", "been", "have", "has", "had", "do",
        "does", "did", "will", "would", "can", "could", "should", "need",
        "want", "tell", "ask", "let", "come", "go", "wait", "stop", "turn",
        "driver", "cab", "taxi", "otp", "pm", "am", "ok", "okay", "yes", "no",
        "hello", "hi", "thanks", "thank", "sorry", "sir", "madam",
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
        "sunday", "today", "tomorrow", "tonight", "morning", "evening",
        "afternoon", "night",
    }
)

# ---------------------------------------------------------------------------
# Taxi-domain concepts
#
# Each concept lists the surface forms that mean it, in English AND in spoken
# Tanglish. A concept counts as "present" in a text if any form appears.
# Only ADDED concepts (in output, absent from source) are treated as errors.
# ---------------------------------------------------------------------------

_CONCEPTS: dict[str, frozenset[str]] = {
    "otp": frozenset({"otp", "pin", "code", "ரகசிய"}),
    "parking": frozenset({"parking", "park"}),
    "cab": frozenset({"cab", "taxi", "auto", "vehicle", "car", "vandi"}),
    "driver": frozenset({"driver", "drivera", "driverkitta", "ஓட்டுநர்"}),
    "minutes": frozenset({"minute", "minutes", "nimisham", "nimidam", "நிமிடம்"}),
    "hours": frozenset({"hour", "hours", "mani", "manikku"}),
    "airport": frozenset({"airport", "terminal", "flight"}),
    "booking": frozenset({"booking", "book", "ride", "trip"}),
    "traffic": frozenset({"traffic", "jam", "nerisal", "போக்குவரத்து"}),
    "payment": frozenset(
        {"payment", "pay", "fare", "cash", "upi", "gpay", "money", "rupees", "price"}
    ),
    "luggage": frozenset(
        {"luggage", "suitcase", "bag", "bags", "backpack", "saaman", "சாமான்"}
    ),
    "hotel": frozenset({"hotel", "lobby", "reception"}),
    "station": frozenset({"station", "metro", "railway", "train", "bus"}),
    "gate": frozenset({"gate", "entrance", "exit", "vaasal"}),
    "security": frozenset({"security", "guard", "watchman"}),
    "phone": frozenset({"phone", "call", "mobile", "number", "whatsapp"}),
    "map": frozenset({"map", "maps", "gps", "navigation", "route", "location"}),
    "road": frozenset({"road", "street", "highway", "signal", "bridge", "flyover"}),
    "building": frozenset({"building", "office", "apartment", "kattidam", "கட்டிடம்"}),
    "cancel": frozenset({"cancel", "cancelled", "cancellation"}),
    "wait": frozenset({"wait", "waiting", "kaathiru", "காத்திரு"}),
    "arrive": frozenset(
        {"arrive", "arrived", "arriving", "reach", "reached", "vandhu", "vandhutaanga",
         "vandhuruvaanga", "varuvaaru", "varum", "vandhuten"}
    ),
    "hospital": frozenset({"hospital", "clinic", "pharmacy", "medical"}),
    "rain": frozenset({"rain", "raining", "mazhai", "wet"}),
}

# Concepts whose unwanted appearance is the reported failure mode. Adding any
# of these when the source never mentioned them is always a hard error.
_HIGH_RISK = frozenset(
    {"otp", "parking", "cab", "driver", "minutes", "airport", "payment", "booking"}
)

# The model narrating instead of translating.
_META_MARKERS = (
    "here is",
    "here's the",
    "translation:",
    "tanglish:",
    "english:",
    "tamil:",
    "note:",
    "explanation:",
    "option 1",
    "option 2",
    "alternative",
    "i cannot",
    "i can't",
    "i don't have",
    "i do not have",
    "as an ai",
    "sure,",
    "certainly",
)

# Spoken-Tanglish markers used to tell "translated" from "still English".
_TANGLISH_MARKERS = re.compile(
    r"(?<![A-Za-z])("
    r"naan|naa|enakku|en\s|ennoda|unga|neenga|avaru|avara|avanga|namma|"
    r"irukk\w*|nikk\w*|pann\w*|sollu\w*|sonn\w*|vand\w*|var\w*|aag\w*|"
    r"pakkathula|kitta|munnadi|pinnadi|veliya|kulla|dhaan|konjam|romba|"
    r"innum|ippo|aana|illa|venum|vendaam|mudiy\w*|paak\w*|ninai\w*|"
    r"-la|-ku|-oda|-a\b|-um"
    r")",
    re.I,
)

_TAMIL_SCRIPT_RE = re.compile(r"[\u0B80-\u0BFF]")


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text or "")


def _stem(token: str) -> str:
    """Strip Tanglish case/particle suffixes so 'gate-la' matches 'gate'."""
    t = token.lower()
    for _ in range(2):
        for suf in _SUFFIXES:
            if len(t) > len(suf) + 2 and t.endswith(suf):
                t = t[: -len(suf)]
                break
        else:
            break
    return t


def concept_tokens(text: str) -> set[str]:
    """Lowercase tokens plus their suffix-stripped stems."""
    out: set[str] = set()
    for raw in re.split(r"[^A-Za-z\u0B80-\u0BFF]+", text or ""):
        if not raw:
            continue
        low = raw.lower()
        out.add(low)
        out.add(_stem(low))
    return out


def concepts_in(text: str) -> set[str]:
    toks = concept_tokens(text)
    return {name for name, forms in _CONCEPTS.items() if toks & forms}


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


@dataclass
class Entities:
    numbers: set[str] = field(default_factory=set)
    times: set[str] = field(default_factory=set)
    names: set[str] = field(default_factory=set)
    codes: set[str] = field(default_factory=set)

    def is_empty(self) -> bool:
        return not (self.numbers or self.times or self.names or self.codes)


def extract_entities(text: str, *, is_source: bool = True) -> Entities:
    """Numbers, clock times, vehicle/booking codes and proper names.

    `is_source` controls capitalisation-based name detection: Tanglish output
    capitalises sentence-initial words like 'Naan', which are not names.
    """
    t = text or ""
    ent = Entities()

    for m in _TIME_RE.finditer(t):
        hh, mm = m.group(1), m.group(2)
        ent.times.add(f"{int(hh)}:{mm}")

    for m in _CODE_RE.finditer(t):
        ent.codes.add(re.sub(r"[\s-]", "", m.group(0)).upper())

    # Digits that are not part of an already-captured time or code.
    masked = _TIME_RE.sub(" ", _CODE_RE.sub(" ", t))
    for num in _NUM_RE.findall(masked):
        ent.numbers.add(str(int(num)) if num.isdigit() else num)

    # Spelled numbers, English or Tanglish.
    for w in _words(masked):
        val = _NUMBER_WORDS.get(w.lower())
        if val is not None:
            ent.numbers.add(val)

    tokens = re.findall(r"\b[A-Za-z][A-Za-z']*\b", t)
    for i, tok in enumerate(tokens):
        if not tok[:1].isupper():
            continue
        if tok.lower() in _NOT_A_NAME:
            continue
        if _NUMBER_WORDS.get(tok.lower()):
            continue
        # Skip sentence-initial capitals unless the source clearly marks a name.
        if i == 0 and (not is_source or tok.lower() in _NOT_A_NAME):
            continue
        if i == 0 and is_source and len(tokens) > 1:
            # "Guindy is far" — ambiguous; only keep if it repeats later.
            if tok not in tokens[1:]:
                continue
        ent.names.add(tok.lower())
    return ent


def _time_forms(t: str) -> set[str]:
    hh, mm = t.split(":")
    forms = {f"{hh}:{mm}", f"{hh}.{mm}", f"{hh} {mm}", f"{int(hh):02d}:{mm}"}
    return forms


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def check_empty(output: str) -> list[str]:
    if not (output or "").strip():
        return ["empty_output"]
    if len(_words(output)) < 1:
        return ["empty_output"]
    return []


def check_meta_output(output: str) -> list[str]:
    low = (output or "").lower()
    flags = [f"meta_output:{m.strip()}" for m in _META_MARKERS if m in low]
    if "\n" in (output or "").strip():
        flags.append("multi_line_output")
    return flags[:2]


def check_repetition(output: str, limit: int | None = None) -> list[str]:
    """Catch degenerate loops like 'OTP la ... OTP la ... OTP la ...'."""
    limit = TANGLISH_REPEAT_LIMIT if limit is None else limit
    words = [w.lower() for w in _words(output)]
    if len(words) < 6:
        return []
    flags: list[str] = []

    counts: dict[str, int] = {}
    for w in words:
        if len(w) < 3:
            continue
        counts[w] = counts.get(w, 0) + 1
    worst = max(counts.items(), key=lambda kv: kv[1], default=("", 0))
    if worst[1] >= limit:
        flags.append(f"repeated_token:{worst[0]}x{worst[1]}")

    bigrams: dict[tuple[str, str], int] = {}
    for a, b in zip(words, words[1:]):
        bigrams[(a, b)] = bigrams.get((a, b), 0) + 1
    bworst = max(bigrams.items(), key=lambda kv: kv[1], default=((), 0))
    if bworst[1] >= 3:
        flags.append(f"repeated_phrase:{' '.join(bworst[0])}x{bworst[1]}")

    # Same comma-clause emitted more than once.
    clauses = [c.strip().lower() for c in re.split(r"[,;.]", output or "") if c.strip()]
    if len(clauses) != len(set(clauses)) and len(clauses) > 2:
        flags.append("duplicate_clause")
    return flags


def check_entities(source: str, output: str) -> list[str]:
    src = extract_entities(source, is_source=True)
    out = extract_entities(output, is_source=False)
    flags: list[str] = []
    out_low = (output or "").lower()
    out_tokens = concept_tokens(output)
    out_digits = set(_NUM_RE.findall(output or ""))

    def _time_covered(t: str) -> bool:
        if t in out.times or any(f in out_low for f in _time_forms(t)):
            return True
        # Models often drop the colon: 7:30 → 730 / 7 30 / 7-30
        hh, mm = t.split(":")
        compact = f"{int(hh)}{mm}"
        spaced = f"{int(hh)} {mm}"
        dashed = f"{int(hh)}-{mm}"
        return compact in out_digits or compact in out_low or spaced in out_low or dashed in out_low

    for num in sorted(src.numbers):
        if num in out.numbers:
            continue
        # Digits that belong to a preserved clock time are not "missing numbers".
        if any(num in t.split(":") for t in src.times if _time_covered(t)):
            continue
        flags.append(f"number_missing:{num}")

    for num in sorted(out.numbers - src.numbers):
        # Compact clock forms (730 from 7:30) are not invented numbers.
        if any(num == f"{int(t.split(':')[0])}{t.split(':')[1]}" for t in src.times):
            continue
        flags.append(f"number_invented:{num}")

    for t in sorted(src.times):
        if _time_covered(t):
            continue
        flags.append(f"time_missing:{t}")
    for t in sorted(out.times - src.times):
        flags.append(f"time_invented:{t}")

    for code in sorted(src.codes):
        if code not in re.sub(r"[\s-]", "", output or "").upper():
            flags.append(f"code_missing:{code}")
    for code in sorted(out.codes - src.codes):
        flags.append(f"code_invented:{code}")

    for name in sorted(src.names):
        if name in out_tokens or name in out_low:
            continue
        flags.append(f"name_missing:{name}")
    for name in sorted(out.names - src.names):
        # Tanglish verbs/particles are never names, but they can be
        # capitalised mid-sentence by the model.
        if _TANGLISH_MARKERS.search(name):
            continue
        flags.append(f"name_invented:{name}")
    return flags


def check_concepts(source: str, output: str) -> tuple[list[str], list[str]]:
    """Returns (hard_flags, soft_flags) for concept drift."""
    src = concepts_in(source)
    out = concepts_in(output)
    added = out - src
    dropped = src - out
    hard = [f"concept_added:{c}" for c in sorted(added & _HIGH_RISK)]
    soft = [f"concept_added_minor:{c}" for c in sorted(added - _HIGH_RISK)]
    soft += [f"concept_dropped:{c}" for c in sorted(dropped)]
    # Losing more than half the source concepts is real meaning loss.
    if src and len(dropped) / len(src) > 0.5:
        hard.append(f"meaning_loss:{len(dropped)}/{len(src)}")
    return hard, soft


def check_length(source: str, output: str) -> tuple[list[str], list[str]]:
    """Length is usually a soft signal — except on very short sources, where
    a multi-clause expansion almost always means invented taxi filler."""
    src_n = len(_words(source))
    out_n = len(_words(output))
    if src_n == 0:
        return [], []
    ratio = out_n / src_n
    hard: list[str] = []
    soft: list[str] = []
    if ratio > TANGLISH_EXPANSION_RATIO:
        flag = f"expansion_suspicious:{ratio:.2f}"
        # "The OTP is 4821." must not become a paragraph about waiting.
        if src_n <= 8 and out_n >= max(12, src_n * 2):
            hard.append(flag)
        else:
            soft.append(flag)
    elif ratio < TANGLISH_SHRINK_RATIO:
        soft.append(f"truncation_suspicious:{ratio:.2f}")
    return hard, soft


def check_translated(source: str, output: str) -> list[str]:
    """Output must actually be Tanglish, not the English echoed back.

    Exception: very short entity-heavy utterances ("The OTP is 4821.") are
    correctly spoken almost entirely in Latin loanwords — that is Tanglish.
    """
    if _TANGLISH_MARKERS.search(output or ""):
        return []
    if _TAMIL_SCRIPT_RE.search(output or ""):
        return []

    src_toks = {w.lower() for w in _words(source)}
    out_toks = {w.lower() for w in _words(output)}
    if not out_toks:
        return ["not_translated"]

    # Short entity replies: OTP / numbers / names only.
    preserveish = {
        "otp", "pin", "driver", "cab", "taxi", "airport", "parking", "gate",
        "entrance", "minutes", "minute", "pm", "am", "upi", "eta",
    }
    if len(out_toks) <= 6 and (
        out_toks <= (preserveish | set(_NUM_RE.findall(output or "")) | src_toks)
        or any(c.isdigit() for c in (output or ""))
    ):
        src_ent = extract_entities(source, is_source=True)
        if not src_ent.is_empty() or (src_toks & preserveish):
            return []

    # Plain English paraphrase with no Tanglish markers is a hard failure —
    # otherwise temperature-0 small models return fluent English and we
    # accept it as "ok".
    english_glue = re.findall(
        r"\b(i'?m|i|am|is|are|the|a|an|please|got|pick|me|up|outside|with|"
        r"have|has|will|would|can|could|at|to|for|and|but)\b",
        output or "",
        re.I,
    )
    if len(english_glue) >= 3:
        return ["not_translated"]

    overlap = len(src_toks & out_toks) / len(out_toks)
    if overlap > 0.75:
        return ["not_translated"]
    return ["weak_tanglish"]


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

_SOFT_PREFIXES = (
    "expansion_suspicious",
    "truncation_suspicious",
    "concept_added_minor",
    "concept_dropped",
    "weak_tanglish",
    "name_missing",
)


@dataclass
class TranslationReport:
    ok: bool
    hard_flags: list[str] = field(default_factory=list)
    soft_flags: list[str] = field(default_factory=list)

    @property
    def flags(self) -> list[str]:
        return self.hard_flags + self.soft_flags

    def reason(self) -> str:
        """Short, model-readable summary used to steer a retry."""
        if not self.hard_flags:
            return ""
        parts: list[str] = []
        for f in self.hard_flags:
            kind, _, detail = f.partition(":")
            if kind == "concept_added":
                parts.append(f"you introduced '{detail}', which the source never mentions")
            elif kind == "number_invented":
                parts.append(f"you invented the number {detail}")
            elif kind == "number_missing":
                parts.append(f"you dropped the number {detail}")
            elif kind == "time_missing":
                parts.append(f"you dropped the time {detail}")
            elif kind == "time_invented":
                parts.append(f"you invented the time {detail}")
            elif kind == "name_invented":
                parts.append(f"you invented the name '{detail}'")
            elif kind in ("code_missing", "code_invented"):
                parts.append(f"you changed the code {detail}")
            elif kind == "meaning_loss":
                parts.append("you dropped most of the source meaning")
            elif kind.startswith("repeated") or kind == "duplicate_clause":
                parts.append("you repeated the same words instead of finishing the sentence")
            elif kind == "not_translated":
                parts.append("you returned English instead of Tanglish")
            elif kind == "empty_output":
                parts.append("you returned nothing")
            elif kind.startswith("meta_output") or kind == "multi_line_output":
                parts.append("you added commentary or several options instead of one translation")
        # De-duplicate, preserve order.
        seen: set[str] = set()
        uniq = [p for p in parts if not (p in seen or seen.add(p))]
        return "; ".join(uniq[:4])


def validate_translation(source: str, output: str) -> TranslationReport:
    """Compare a Tanglish translation against its English source."""
    hard: list[str] = []
    soft: list[str] = []

    empty = check_empty(output)
    if empty:
        return TranslationReport(ok=False, hard_flags=empty)

    hard += check_meta_output(output)
    hard += check_repetition(output)
    hard += check_entities(source, output)
    c_hard, c_soft = check_concepts(source, output)
    hard += c_hard
    soft += c_soft
    l_hard, l_soft = check_length(source, output)
    hard += l_hard
    soft += l_soft
    hard += check_translated(source, output)

    # Demote the checks that must never block natural Tanglish on their own.
    demoted = [f for f in hard if f.split(":", 1)[0] in _SOFT_PREFIXES]
    hard = [f for f in hard if f not in demoted]
    soft += demoted

    return TranslationReport(ok=not hard, hard_flags=hard, soft_flags=soft)


def score(source: str, output: str) -> float:
    """Lower is better — used to pick the least-bad candidate after retries."""
    rep = validate_translation(source, output)
    return len(rep.hard_flags) * 10 + len(rep.soft_flags)


if __name__ == "__main__":
    good = (
        "I am standing near the security gate with a red suitcase.",
        "Naan security gate pakkathula red suitcase-oda nikkiren.",
    )
    bad = (
        "I am standing near the security gate with a red suitcase.",
        "En, nammal aana security gate la neerla suitcase irukku, driver aana "
        "opposite side la road la, aana turn around pannunga, main entrance la "
        "come pannunga, OTP la send pannunga, cab la waiting pannunga, parking "
        "la find pannunga, minutes la wait pannunga.",
    )
    for src, out in (good, bad):
        rep = validate_translation(src, out)
        print("OK" if rep.ok else "FAIL", rep.flags)
        print("  reason:", rep.reason() or "-")
