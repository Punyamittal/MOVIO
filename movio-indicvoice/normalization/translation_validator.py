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
from normalization import tanglish_morphology as morphology  # noqa: E402
from normalization import tanglish_vocab  # noqa: E402

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
    "eleven": "11",
    "padhinonnu": "11",
    "twelve": "12",
    "panneendu": "12",
    "thirteen": "13",
    "padhimoonu": "13",
    "fourteen": "14",
    "padhinaalu": "14",
    "fifteen": "15",
    "padhinaindhu": "15",
    "padhinanju": "15",
    "sixteen": "16",
    "padhinaaru": "16",
    "seventeen": "17",
    "padhinezhu": "17",
    "eighteen": "18",
    "padhinettu": "18",
    "nineteen": "19",
    "pathonbadhu": "19",
    "twenty": "20",
    "irubathu": "20",
    "thirty": "30",
    "muppathu": "30",
    "forty": "40",
    "naapathu": "40",
    "fifty": "50",
    "ambathu": "50",
    "sixty": "60",
    "arubathu": "60",
    "seventy": "70",
    "ezhubathu": "70",
    "eighty": "80",
    "enbathu": "80",
    "ninety": "90",
    "thonnooru": "90",
    "hundred": "100",
    "nooru": "100",
    "thousand": "1000",
    "aayiram": "1000",
    "ayiram": "1000",
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
        # Domain acronyms — uppercase, but never person/place names.
        "eta", "gps", "upi", "atm", "ac", "id", "sms", "app", "pin", "km",
        "kms", "uber", "ola", "wifi", "pnr", "iap",
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
        {"payment", "pay", "paid", "fare", "cash", "upi", "gpay", "money",
         "rupees", "rupaa", "price", "charge"}
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
    "fuel": frozenset({"fuel", "petrol", "diesel", "gauge", "bunk", "tank"}),
}

# Kinship terms that must not appear unless the source mentions family relations.
_KINSHIP_TERMS = frozenset(
    {"thambi", "akka", "amma", "appa", "mama", "maama", "cousin", "sister", "brother"}
)

# Common model garbage — not valid spoken Tanglish tokens.
# Curated non-words seen in production. "annuh" is deliberately absent: it is
# the phonetic respelling of a correct "Anna" produced downstream for the TTS
# engine, not something the translator invented.
_GARBAGE_TOKENS = frozenset(
    {"pahamilla", "paham", "petro", "bunnu", "petha", "petroli", "alaiyaa", "alaiya", "aga"}
)

# Entire English phrase with only a Tamil copula bolted on — not code-switching.
_ENGLISH_CHUNK_COPULA = re.compile(
    r"\b(?:my|your|our|the|this|that)\s+"
    r"(?:(?!(?:naan|enakku|unga|irukk|pann|soll|vand|var|aag|theriy|illa|romba|konjam|"
    r"ippo|indha|andha|edhu|enna|aana|nu|dhaan|vayitru|vayiru))\b"
    r"[a-z]+\s+){2,}"
    r"(?:irukku|irukka|irukken|irundhu)\b",
    re.I,
)

# "-ko" is not a Tamil case suffix; gold corpus uses -ku, -a, -oda, -la, -nala.
_INVALID_KO_SUFFIX = re.compile(r"\b\w+-ko\b", re.I)

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


def _english_stems(token: str) -> set[str]:
    """Base forms for English inflections so 'parked'/'pinned' match 'park'/'pin'.

    Without this, a source that says "the vehicle is parked" and an output that
    says "park pannirukku" looked like the model had *added* the parking concept.
    """
    out: set[str] = set()
    t = token
    if len(t) > 4 and t.endswith("ing"):
        base = t[:-3]
        out.update({base, base + "e"})
        if len(base) > 2 and base[-1] == base[-2]:
            out.add(base[:-1])
    if len(t) > 3 and t.endswith("ed"):
        base = t[:-2]
        out.update({base, base + "e"})
        if len(base) > 2 and base[-1] == base[-2]:
            out.add(base[:-1])
    if len(t) > 3 and t.endswith("es"):
        out.add(t[:-2])
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        out.add(t[:-1])
    return out


def concept_tokens(text: str) -> set[str]:
    """Lowercase tokens plus Tanglish suffix stems and English inflection stems."""
    out: set[str] = set()
    for raw in re.split(r"[^A-Za-z\u0B80-\u0BFF]+", text or ""):
        if not raw:
            continue
        low = raw.lower()
        out.add(low)
        out.add(_stem(low))
        out |= _english_stems(low)
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

    # Spoken Tanglish: oru/onnu before a noun is often "a/an", not the number 1.
    if not is_source:
        if re.search(
            r"\b(?:oru|onnu)\s+(?:vandi|car|bag|package|suitcase|person|per|ride|"
            r"thadava|time|mani|nimisham)\b",
            t,
            re.I,
        ):
            ent.numbers.discard("1")

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


def _apply_spoken_number_equivalence(
    src: Entities, out: Entities, source: str, output: str
) -> None:
    """Align English/Tanglish number phrasing so validator does not false-flag gold."""
    src_low = (source or "").lower()
    out_low = (output or "").lower()

    if re.search(r"\btwo\s+hundred\b", src_low) or "200" in src.numbers:
        if "rendu" in out_low and "nooru" in out_low:
            src.numbers.discard("2")
            src.numbers.discard("100")
            out.numbers.discard("2")
            out.numbers.discard("100")

    if re.search(r"\b(?:an|one|1)\s+hour", src_low):
        if re.search(r"\b(?:onnu|oru)\b", out_low) and "mani" in out_low:
            src.numbers.discard("1")
            out.numbers.discard("1")

    # "next hour" / "for the next hour" → adutha oru mani neramukku (not digit 1).
    if re.search(r"\bhour\b", src_low):
        if re.search(r"\bmani\b", out_low) and re.search(r"\b(?:onnu|oru)\b", out_low):
            out.numbers.discard("1")

    if re.search(r"\bonce\b", src_low):
        if re.search(r"\b(?:onnu|oru)\s+(?:thadava|time)\b", out_low):
            out.numbers.discard("1")

    if "twice" in src_low and "rendu" in out_low and "thadava" in out_low:
        out.numbers.discard("2")

    # Tamil marks indefiniteness with oru/onnu ("a vehicle", "one of the
    # passengers"). When the source never counted, these are articles, not the
    # number 1 — a real dropped count still surfaces as number_missing.
    if "1" not in src.numbers and re.search(r"\b(?:oru|onnu)\b", out_low):
        out.numbers.discard("1")

    # "this one" / "the first one" are pronouns, not the number 1.
    pronoun_ones = re.findall(
        r"\b(?:this|that|which|another|the\s+other|first|second|third|last|next)\s+one\b",
        src_low,
    )
    if pronoun_ones and len(re.findall(r"\bone\b", src_low)) == len(pronoun_ones):
        src.numbers.discard("1")
        # "the next one" → "adutha onnu": the mirror pronoun is not a count either.
        if re.search(r"\b(?:oru|onnu)\b", out_low):
            out.numbers.discard("1")

    # "neither of us" → "rendu perukkum": rendu is the pair, not an added count.
    if re.search(r"\b(?:both|neither|either)\s+of\s+(?:us|them|you)\b", src_low):
        if re.search(r"\brendu\s+per", out_low) and "2" not in src.numbers:
            out.numbers.discard("2")

    # "a couple of minutes" → rendu nimisham (not an invented count).
    if re.search(r"\bcouple\s+of\s+minutes?\b", src_low):
        if re.search(r"\brendu\s+nimisham\b", out_low):
            src.numbers.discard("2")
            out.numbers.discard("2")


def check_entities(source: str, output: str) -> list[str]:
    src = extract_entities(source, is_source=True)
    out = extract_entities(output, is_source=False)
    _apply_spoken_number_equivalence(src, out, source, output)
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


def check_malformed_tanglish(source: str, output: str) -> tuple[list[str], list[str]]:
    """Fluent-looking output that is not valid Tanglish.

    Returns (hard, soft). Hard flags are grammatical facts that never occur in
    the gold corpus — a stranded infinitive, a verb in a person the English
    never licensed, a kinship term nobody mentioned. Soft flags are corpus
    heuristics (unfamiliar vocabulary) that are too noisy to gate on: measured
    against the gold pairs themselves, unknown-word density does not separate
    real garbage from correct-but-novel Tanglish.
    """
    hard: list[str] = []
    soft: list[str] = []
    src_low = (source or "").lower()
    out_low = (output or "").lower()

    # A kinship term the source never introduced ("fuel gauge vera thambi").
    # Matched with a trailing case suffix too, so "thambiya" is caught as well.
    for kin in sorted(_KINSHIP_TERMS):
        if re.search(rf"\b{re.escape(kin)}\w*\b", out_low) and not re.search(
            rf"\b{re.escape(kin)}\w*\b", src_low
        ):
            hard.append(f"malformed:kinship_insert:{kin}")
            break

    # Curated non-words seen in production. Narrow by design — the corpus is
    # too small to infer new ones reliably (see soft unknown_vocab below).
    for junk in sorted(_GARBAGE_TOKENS):
        if re.search(rf"\b{re.escape(junk)}\b", out_low):
            hard.append(f"malformed:garbage_token:{junk}")
            break

    # "theriyum" (I know) truncated to a non-word stem.
    if re.search(r"\btheri\b", out_low):
        hard.append("malformed:truncated_stem:theri")

    # A verb stranded in the infinitive where the main verb belongs. Never
    # occurs in any of the gold pairs.
    if morphology.CLAUSE_FINAL_INFINITIVE.search(output or ""):
        hard.append("malformed:bare_infinitive_clause_final")

    # The speaker announcing their own future action when the English did not.
    if morphology.FIRST_SG_FUTURE.search(output or "") and not (
        morphology.source_allows_first_sg_future(source)
    ):
        hard.append("malformed:person_1sg_future")

    # A state turned into an action someone performs ("late pannuvanga").
    if morphology.STATE_AS_ACTION.search(output or ""):
        hard.append("malformed:state_as_action")

    # A polite request rendered as a flat statement loses the ask entirely.
    if morphology.is_suggestion(source) and not morphology.has_request_form(output):
        hard.append("malformed:mood_suggestion_lost")
    # Driver-directed "please avoid / please tell …" must land as -unga/-adheenga.
    if re.search(
        r"\bplease\s+(?:avoid|tell|ask|wait|stop|come|take|share|confirm|let|be|slow)\b",
        src_low,
    ) and not morphology.has_request_form(output):
        hard.append("malformed:mood_suggestion_lost")

    # Raw English chunk + copula only ("my stomach bad day irukku").
    if _ENGLISH_CHUNK_COPULA.search(output or ""):
        hard.append("malformed:english_chunk_collapse")

    # "-ko" suffix (e.g. "stretch-ko") — not attested in the gold corpus.
    if _INVALID_KO_SUFFIX.search(output or ""):
        hard.append("malformed:invalid_ko_suffix")

    # Source says avoid; output must not drop or invert it.
    if re.search(r"\bavoid\b", src_low):
        avoid_ok = re.search(
            r"\b(?:avoid|vidama|venaam|edukadheenga|pokadheenga|pokkadheenga|"
            r"pannadheenga)\b",
            out_low,
        )
        if not avoid_ok:
            hard.append("malformed:avoid_lost")
        if re.search(r"\bpo\s+nu\b", out_low) and not re.search(r"\bavoid\b", out_low):
            hard.append("malformed:avoid_inverted_go")

    # Concessive "I know it's faster" misread as completed "went" on the road.
    if re.search(r"\b(?:understand|know|faster|even if)\b", src_low):
        if re.search(r"\b(?:road|route|bridge|highway)\s+pona\b", out_low):
            if not re.search(r"\b(?:theriyum|irukum|fast-a)\b", out_low):
                hard.append("malformed:concession_as_past")

    if unknown := tanglish_vocab.unknown_tokens(output or "", source or ""):
        soft.append(f"unknown_vocab:{','.join(unknown[:4])}")

    return hard, soft


def check_concepts(source: str, output: str) -> tuple[list[str], list[str]]:
    """Returns (hard_flags, soft_flags) for concept drift."""
    src = concepts_in(source)
    out = concepts_in(output)
    added = out - src
    dropped = src - out

    risky = set(_HIGH_RISK)
    # Naming the vehicle is licensed once the source is already about a ride
    # ("ask the driver to stop" → "vehicle-a stop panna driver-kitta sollunga").
    if src & {"driver", "booking", "cab"}:
        risky.discard("cab")

    hard = [f"concept_added:{c}" for c in sorted(added & risky)]
    soft = [f"concept_added_minor:{c}" for c in sorted(added - risky)]
    soft += [f"concept_dropped:{c}" for c in sorted(dropped)]
    # Losing most of the source concepts is real meaning loss. Needs a big
    # enough denominator: dropping the single detected concept of a one-concept
    # sentence usually just means Tanglish phrased it without the loanword.
    if len(src) >= 3 and len(dropped) >= 2 and len(dropped) / len(src) > 0.5:
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
        # Spoken Tanglish for this pipeline is Latin code-mix. Tamil glyphs mixed
        # with English words are interlinear glosses, not natural Tanglish.
        latin_tokens = re.findall(r"\b[A-Za-z]{2,}\b", output or "")
        if len(latin_tokens) >= 2:
            return ["tamil_script_mixed"]
        return ["tamil_script_only"]

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
    "unknown_vocab",
)


# Retry guidance per malformed sub-kind. Describing the grammatical fault is
# what steers a small model; naming the token it produced does not.
_MALFORMED_REASONS: dict[str, str] = {
    "kinship_insert": "you added a family term the source never mentioned",
    "garbage_token": "you produced a word that does not exist in Tanglish",
    "truncated_stem": "you cut a verb short into a non-word stem",
    "bare_infinitive_clause_final": (
        "you ended a clause on a bare infinitive; use the polite imperative "
        "(-unga) or a finite verb"
    ),
    "person_1sg_future": (
        "you used the 'I will' future when the speaker was not describing their "
        "own future action"
    ),
    "state_as_action": (
        "you turned a description into an action someone performs; a state like "
        "'late' or 'empty' needs irukku/aayidichu, not pannuvanga"
    ),
    "mood_suggestion_lost": (
        "the source asks politely, so the verb needs -alama or -unga, not a "
        "flat statement"
    ),
    "english_chunk_collapse": (
        "you dropped a raw English clause into the middle and only attached a "
        "Tamil verb at the end; restructure the whole idea in Tanglish"
    ),
    "invalid_ko_suffix": (
        "you used '-ko' as a suffix; Tamil uses -ku (dative), -a (object), "
        "-oda (with), or -la (locative), not -ko"
    ),
    "avoid_lost": "the source asks to avoid something but your output never says avoid or an equivalent",
    "avoid_inverted_go": (
        "the source asks to avoid a stretch but you used 'po' (go) instead "
        "of avoid/vidama/venaam"
    ),
    "concession_as_past": (
        "you used past-tense 'pona' (went) where the source concedes a point "
        "('I know it's faster, but…'); use a concessive like 'theriyum' or 'fast-a irukum'"
    ),
}

# Malformed sub-kinds that should still be spoken as Tanglish rather than
# falling back to English — register/person errors, not nonsense.
_MALFORMED_NON_BLOCKING = frozenset(
    {
        "mood_suggestion_lost",
        "bare_infinitive_clause_final",
        "person_1sg_future",
        "state_as_action",
        "concession_as_past",
    }
)


def malformed_blocks_fallback(flag: str) -> bool:
    """Whether a malformed hard flag should force English passthrough."""
    if not flag.startswith("malformed:"):
        return False
    parts = flag.split(":", 2)
    kind = parts[1] if len(parts) > 1 else ""
    return kind not in _MALFORMED_NON_BLOCKING


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
            elif kind == "case_marker_wrong":
                parts.append(
                    "you used -ku (for/to) where -nala (because of) is needed for causal blocking"
                )
            elif kind == "stacked_vocative":
                parts.append("you stacked vocatives (pick one: Anna, Ayya, or Brother)")
            elif kind == "time_calque_trailing":
                parts.append("you tacked the time clause at the end like English; put it before the verb")
            elif kind == "malformed":
                parts.append(_MALFORMED_REASONS.get(detail.split(":", 1)[0], "") or
                             f"the output contains invalid Tanglish ({detail or kind})")
            elif kind == "tamil_script_mixed":
                parts.append(
                    "you mixed Tamil script with English words (interlinear gloss, not Tanglish)"
                )
            elif kind == "tamil_script_only":
                parts.append("you used Tamil script instead of Latin Tanglish")
            elif kind == "empty_output":
                parts.append("you returned nothing")
            elif kind.startswith("meta_output") or kind == "multi_line_output":
                parts.append("you added commentary or several options instead of one translation")
        # De-duplicate, preserve order.
        seen: set[str] = set()
        uniq = [p for p in parts if not (p in seen or seen.add(p))]
        return "; ".join(uniq[:4])


def check_case_markers(source: str, output: str) -> tuple[list[str], list[str]]:
    """Flag fluent-but-wrong Tamil case suffixes (-ku vs -nala, stacked vocatives)."""
    hard: list[str] = []
    soft: list[str] = []
    out_low = (output or "").lower()
    src_low = (source or "").lower()

    if re.search(r"\bayya\s+(?:brother|anna)\b", out_low) or re.search(
        r"\bbrother\s+ayya\b", out_low
    ):
        soft.append("stacked_vocative")

    # "-ku" is dative/purpose; blocking *because of* a procession needs "-nala".
    if "procession" in src_low and re.search(r"\bblock", src_low):
        if re.search(r"\bprocession\s+ku\s+block", out_low):
            hard.append("case_marker_wrong:procession_ku_causal")

    if re.search(r"next\s+hour", src_low) and re.search(r",\s*next hour-a\.?$", out_low):
        soft.append("time_calque_trailing")

    return hard, soft


def validate_translation(source: str, output: str) -> TranslationReport:
    """Compare a Tanglish translation against its English source."""
    hard: list[str] = []
    soft: list[str] = []

    empty = check_empty(output)
    if empty:
        return TranslationReport(ok=False, hard_flags=empty)

    hard += check_meta_output(output)
    hard += check_repetition(output)
    m_hard, m_soft = check_malformed_tanglish(source, output)
    hard += m_hard
    soft += m_soft
    hard += check_entities(source, output)
    cm_hard, cm_soft = check_case_markers(source, output)
    hard += cm_hard
    soft += cm_soft
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
