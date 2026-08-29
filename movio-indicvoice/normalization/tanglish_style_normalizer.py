"""
Polish Ollama / offline Tanglish toward gold-pair register.

Gold pairs are the style reference: causal clauses (-naala), driver-kitta,
nu quotatives, Tamil time words, vidama/venaam, no English calques.

Applied after model translation (not on exact gold hits).
"""
from __future__ import annotations

import re
from typing import Callable

from normalization import tanglish_morphology as morphology
from normalization.pronunciation_rules import strip_tamil_script

Rule = tuple[re.Pattern[str], str | Callable[[re.Match[str]], str]]

_TAMIL_MINUTES: dict[str, str] = {
    "1": "oru",
    "one": "oru",
    "2": "rendu",
    "two": "rendu",
    "3": "moonu",
    "three": "moonu",
    "4": "naalu",
    "four": "naalu",
    "5": "ainthu",
    "five": "ainthu",
    "6": "aaru",
    "six": "aaru",
    "7": "ezhu",
    "seven": "ezhu",
    "8": "ettu",
    "eight": "ettu",
    "9": "onbadhu",
    "nine": "onbadhu",
    "10": "pathu",
    "ten": "pathu",
    "15": "padhinaindhu",
    "fifteen": "padhinaindhu",
    "20": "irubathu",
    "twenty": "irubathu",
}

# Known Ollama calques / garbage → gold-style (longer patterns first).
_ANTI_CALQUE_RAW: list[tuple[str, str | Callable[[re.Match[str]], str], int]] = [
    (r"\bconfirm\s+kanna\b", "confirm pannunga", re.I),
    (r"\bwhich\s+side\s+la\s+come\s+pannenga\b", "eppadi vara pora nu confirm pannunga", re.I),
    (r"\bcome\s+pannenga\b", "vara sollunga", re.I),
    (r"\btell\s+pannunga\b", "sollunga", re.I),
    (r"\barrive\s+panna\b", "vandhuduchu", re.I),
    (r"\bentrance-uda\s+pannanga\b", "entrance irukku", re.I),
    (r"\bapplicashun\b", "App-la", re.I),
    (r"\bapplication\s+saya\b", "App-la", re.I),
    (r"\bshow\s+van\b", "kaattuthu", re.I),
    (r"\bnear\s+la\b", "pakkathula", re.I),
    (r"\bdriver\s+ku\b", "driver-kitta", re.I),
    (r"\bdriver\s+ke\b", "driver-kitta", re.I),
    (r"\bwait\s+for\s+(\d+|one|two|five|ten)\s+minutes?\s+near\b", r"wait pannunga \1 minutes near", re.I),
    (r"\bwe\s+no\s+get\s+stuck\b", "nikkama irukalam", re.I),
    (r"\brain\s+come\s+heavily\b", "romba mazhai peiyuthu", re.I),
    (r"\btake\s+inner\s+road\b", "inner road route-la po", re.I),
    (r"\bwrong\s+gps\s+or\s+wrong\s+gate\b", "GPS thappu illana thappu gate", re.I),
    (r"\bbuildi\s+ngil\b", "building kitta", re.I),
    (r"\baappa\s+kooda\b", "appuram", re.I),
    (r"\bpottum\s+kuduthu\b", "podunga", re.I),
    (r"\baadha\b", "aana", re.I),
    (r"\bapp(?:-la)?\s+price\s+follow\s+panna\b", "andha price-a follow pannunga", re.I),
    (r"\bfollow\s+panna\b", "follow pannunga", re.I),
    (r"\bapp\s+confirm\s+panniten\b", "app confirm pannitrukku", re.I),
    (r"\bgo\s+by\s+that\b", "andha price-a follow pannunga", re.I),
    (
        r"\bflyover\s+ya\s+ground\s+route-a\s+confirm\s+panna\b",
        "flyover-a edukkardhu illa ground route-a edukkardhu nu confirm pannunga",
        re.I,
    ),
    (
        r"\bflyover\s+ya\s+ground\s+route-a\s+enna\s+decide\s+panna\b",
        "flyover-a edukkardhu illa ground route-a edukkardhu nu confirm pannunga",
        re.I,
    ),
    (r"\byenna\s+fare\s+change\s+aagiduchu\b", "adha vachu fare change aagum", re.I),
    (r"\bfare\s+change\s+panna\b", "adha vachu fare change aagum", re.I),
    (r"\bconfirm\s+panna\b", "confirm pannunga", re.I),
    (r"\bdecide\s+panna\b", "confirm pannunga", re.I),
    (r"\bmeter\s+start\s+pannenga\s+nu\b", "meter start pannadhukku munnadi", re.I),
    # Stacked vocatives: a speaker picks one register, never two.
    (r"\b(?:ayya|anna|uncle)\s+(?:brother|ayya|anna)\b", "Anna", re.I),
    (r"\bbrother\s+(?:ayya|anna)\b", "Anna", re.I),
    (
        r"\bcan\s+see\s+three\s+cars\s+matching\s+description\s+gate\b",
        "gate pakkathula sonna description-ku match aagura moonu car-a naan paakuren",
        re.I,
    ),
    (r"\bcould\s+flash\s+(?:your\s+)?indicator\s+once\b", "indicator-a oru thadava flash pannunga", re.I),
    (r"\bso\s+know\s+one\s+is\b", "unga vandi edhu nu theriyuradhukku", re.I),
    (r"\bflash\s+indicator\s+once\b", "indicator-a oru thadava flash pannunga", re.I),
    # "pannanga" never appears in the gold corpus; the polite imperative is
    # "pannunga" (49 occurrences). Same for the other -anga verb stems.
    (r"\bpann?anga\b", "pannunga", re.I),
    (r"\bsollanga\b", "sollunga", re.I),
    (r"\bpannatu\b", "pannunga", re.I),
    (r"\bnee\b", "neenga", re.I),
    # Non-words seen in production, mapped to what they were reaching for.
    (r"\balaiyaa\b", "already", re.I),
    (r"\baga\b", "Anna", re.I),
    (r"\bsave\s+time\s+pann\w+\b", "time save aagum", re.I),
    # Raw English stomach clause → restructured Tanglish when source mentions stomach.
    (r"\bmy\s+stomach\s+bad\s+day\s+irukku\b",
        "enakku indha naeku vayitru romba correct-a illa",
        re.I,
    ),
    # Natural spoken register (Chennai everyday Tanglish).
    (r"\bkonjam seconds-ku munnadi\b", "sila seconds-ku munnadi", re.I),
    (r"\bkonjam nimishath?ukku munnadi\b", "sila nimishathukku munnadi", re.I),
    (r"\bback seat-a koodaippen\b", "back seat-la vittuten", re.I),
    (r"\bback seat-a kooduth(?:en|utaen)\b", "back seat-la vittuten", re.I),
    (r"\bcorrect vehicle dhaan pannikinum\b", "correct vehicle dhaana-nu confirm pannikanum", re.I),
    (r"\bcorrect vehicle dhaan pannikanum\b", "correct vehicle dhaana-nu confirm pannikanum", re.I),
    (r"\bdryvur-a\b", "driver-a", re.I),
    (r"\bavarukku adhu check panna\b", "adha check panna", re.I),
    (
        r"\bmap-la arrival time-nu increase dhaan (?:padhinaindhu|fifteen)(?:\s+minutes)? nimisham-ku mela aagalam\b",
        "so map-la arrival time innum padhinaindhu nimisham-ku mela aagalam",
        re.I,
    ),
    (
        r"\bmap-la arrival time-nu increase dhaan (\w+) nimisham-ku mela aagalam\b",
        r"so map-la arrival time innum \1 nimisham-ku mela increase aagalam",
        re.I,
    ),
]

# Case-suffix repairs. A suffix that sounds plausible but carries the wrong
# grammatical function produces fluent, semantically wrong speech — worse for a
# voice agent than obviously broken text.
_CASE_REPAIR_RAW: list[tuple[str, str | Callable[[re.Match[str]], str], int]] = [
    # "-ku" is dative/purpose. Blocking *caused by* something needs "-nala".
    (r"\b(\w+)\s+ku\s+block\s+(pannirukanga|aayirukku)\b", r"\1-nala block \2", re.I),
    (r"\b(\w+)-ku\s+block\s+(pannirukanga|aayirukku)\b", r"\1-nala block \2", re.I),
    # "-ko" is not a real suffix; before motion verbs it is usually a mistyped -a.
    (r"\b(\w+)-ko\s+(po|vara|poga)\b", r"\1-a avoid pannunga", re.I),
    (r"\b(\w+)-ko\b", r"\1-ku", re.I),
    # Time clause tacked on at the end, English-style, after the verb.
    (
        r"\b(\w+\s+pannirukanga),\s*next\s+hour-a\b",
        r"adutha oru mani neramukku \1",
        re.I,
    ),
    (r"\b(\w+\s+pannirukanga),\s*next\s+hour\b", r"adutha oru mani neramukku \1", re.I),
]

# Vocabulary alignment with gold corpus (safe on any Tanglish).
_GOLD_VOCAB_RAW: list[tuple[str, str | Callable[[re.Match[str]], str], int]] = [
    (r"\bplease\s+ask\s+the\s+driver\b", "driver-kitta sollunga", re.I),
    (r"\bplease\s+tell\s+the\s+driver\b", "driver-kitta sollunga", re.I),
    (r"\bask\s+the\s+driver\b", "driver-kitta sollunga", re.I),
    (r"\btell\s+the\s+driver\b", "driver-kitta sollunga", re.I),
    (r"\bwait\s+pannadhinga\b", "wait pannadheenga", re.I),
    (r"\bdo\s+not\s+cancel\b", "cancel pannadheenga", re.I),
    (r"\bdon'?t\s+cancel\b", "cancel pannadheenga", re.I),
    (r"\binstead\s+of\b", "vida", re.I),
    (r"\bdo\s+not\s+follow\b", "follow pannadheenga", re.I),
    (r"\bdon'?t\s+follow\b", "follow pannadheenga", re.I),
]


def _rules(raw: list[tuple[str, str | Callable[[re.Match[str]], str], int]]) -> list[Rule]:
    return [(re.compile(pat, flags), repl) for pat, repl, flags in raw]


def _apply_rules(text: str, rules: list[Rule]) -> str:
    out = text or ""
    for pattern, repl in rules:
        out = pattern.sub(repl, out)
    return out


def _minutes_word_repl(m: re.Match[str]) -> str:
    raw = m.group(1).lower()
    tam = _TAMIL_MINUTES.get(raw, raw)
    return f"{tam} nimisham"


def normalize_time_phrases(text: str) -> str:
    """English time counts → spoken Tanglish (gold register)."""
    out = text or ""
    out = re.sub(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten|fifteen|twenty|\d{1,2})\s+(minutes?)\b",
        _minutes_word_repl,
        out,
        flags=re.I,
    )
    out = re.sub(r"\bone\s+hour\b", "oru mani neram", out, flags=re.I)
    out = re.sub(r"\ban\s+hour\b", "oru mani neram", out, flags=re.I)
    out = re.sub(r"\btwo\s+hundred\s+rupees?\b", "rendu nooru rupaa", out, flags=re.I)
    out = re.sub(r"\btwo\s+hundred\s+meters?\b", "rendu nooru meter", out, flags=re.I)
    return out


def cleanup_tanglish(text: str) -> str:
    out = re.sub(r"\s+", " ", text or "").strip()
    out = re.sub(r"\bso\s+aana\b", "aana", out, flags=re.I)
    out = re.sub(r"\bso\s+so\b", "so", out, flags=re.I)
    out = re.sub(r"\s+([.,!?])", r"\1", out)
    return out


_ANTI_CALQUE = _rules(_ANTI_CALQUE_RAW)
_CASE_REPAIR = _rules(_CASE_REPAIR_RAW)
_GOLD_VOCAB = _rules(_GOLD_VOCAB_RAW)

_STATE_ADJ = "|".join(morphology.STATE_ADJECTIVES)

# "streets-a mostly empty panna": accusative on the subject plus a bare
# infinitive predicate. Tamil states this predicatively.
_PREDICATIVE_RE = re.compile(
    r"\b(\w+)-a\s+((?:mostly|romba|konjam|almost|fully|completely)\s+)?"
    r"(" + _STATE_ADJ + r")\s+panna\b",
    re.I,
)

# "late pannuvanga": a state cannot be performed by someone in the future.
_STATE_ACTION_RE = re.compile(
    r"\b(" + _STATE_ADJ + r")\s+pann(?:uvanga|uvaanga|uven|uvaen|uveen)\b", re.I
)

# Speaker's own future where the English only asked politely.
_FIRST_SG_FUTURE_RE = re.compile(r"\bpann(?:uvaen|uven|uveen)\b", re.I)

# Bare infinitive left stranded at the end of a clause.
_STRANDED_INFINITIVE_RE = re.compile(r"\bpanna\b(?=\s*(?:[,.;!?]|$))", re.I)


def repair_verb_forms(text: str, source: str) -> str:
    """Put verbs back into the person, tense and mood the English calls for.

    Meaning-preserving by construction: each rewrite changes only the verb
    form, never the content words, so a wrong-mood sentence is not "fixed" by
    substituting a different sentence.
    """
    out = text or ""
    out = _PREDICATIVE_RE.sub(lambda m: f"{m.group(1)}-um {m.group(2) or ''}{m.group(3)}-a irukku", out)
    out = _STATE_ACTION_RE.sub(r"\1-a irukku", out)

    if morphology.is_suggestion(source):
        out = _FIRST_SG_FUTURE_RE.sub("pannalama", out)
    if morphology.is_suggestion(source) or morphology.is_imperative(source):
        out = _STRANDED_INFINITIVE_RE.sub("pannunga", out)
    return out


def polish_tanglish_output(text: str, *, source: str = "") -> str:
    """Nudge model Tanglish toward gold-pair style.

    `source` is the English utterance; it decides mood-sensitive repairs, since
    the same Tanglish verb form is right for a statement and wrong for a
    request.
    """
    out = strip_tamil_script(text)
    out = _apply_rules(out, _ANTI_CALQUE)
    out = _apply_rules(out, _CASE_REPAIR)
    out = repair_verb_forms(out, source)
    out = _apply_rules(out, _GOLD_VOCAB)
    out = normalize_time_phrases(out)
    out = cleanup_tanglish(out)
    return out
