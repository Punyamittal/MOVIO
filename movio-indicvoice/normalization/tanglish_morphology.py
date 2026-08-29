"""
Tanglish verb morphology and English source mood.

The recurring model failure is not vocabulary — it is putting a verb in the
wrong person/tense/mood. "It's late" becomes "late pannuvanga" (you all will
make it late); "would it be okay to skip" becomes "skip pannuvaen" (I will
skip). Both are fluent and both change who is doing what.

These tables let the validator and the style normalizer reason about verb
FORM rather than matching whole sentences, so a paraphrase of the same error
is caught by the same rule.

Empirically grounded in normalization/tanglish_gold_pairs.json:
  * clause-final bare infinitive ("... empty panna.")   0 occurrences
  * 1sg future ("...uven")                              only with English
                                                        first-person future or
                                                        reported speech
  * polite imperative ("...unga")                       120 occurrences
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Tanglish verb forms
# ---------------------------------------------------------------------------

# 1st person singular future: pannuven, poiduven, vandhuruven, aagiduven.
FIRST_SG_FUTURE = re.compile(r"\b\w*(?:uven|uvaen|uveen)\b", re.I)

# 2nd/3rd person plural: pannuvanga, vandhuruvaanga, panniduvaanga.
#
# NOT a reliable future marker on its own. In spoken Tamil this same form
# carries habitual ("kuzhandhaikal road cross pannuvanga" — children usually
# cross) and impersonal/passive ("pick pannuvanga" — they pick up) readings,
# all of which appear in the gold corpus. Only the state-adjective case below
# is unambiguously wrong.
PLURAL_FUTURE = re.compile(r"\b\w*(?:uvanga|uvaanga)\b", re.I)

# Polite suggestion / permission: pannalama, edukalama, pannalam, irukalam.
SUGGESTION = re.compile(r"\b\w*(?:alama|alaam|alam)\b", re.I)

# Polite imperative, with the optional question particle: pannunga, edunga,
# sollunga, anupungala.
POLITE_IMPERATIVE = re.compile(r"\b\w{2,}unga(?:la|laa)?\b", re.I)

# States you cannot "perform". "It's late" → "late pannuvanga" turns a
# description into an action someone will carry out, flipping the subject.
STATE_ADJECTIVES = (
    "late", "early", "empty", "full", "ready", "closed", "open", "free",
    "busy", "clear", "blocked", "available", "flooded", "crowded",
)
STATE_AS_ACTION = re.compile(
    r"\b(?:" + "|".join(STATE_ADJECTIVES) + r")\s+"
    r"pann(?:uvanga|uvaanga|uven|uvaen|uveen|a)\b",
    re.I,
)

# Negative polite imperative: pannadheenga, wait pannadheenga.
NEGATIVE_IMPERATIVE = re.compile(r"\b\w*adheenga\b", re.I)

# Bare infinitive stranded at the end of a clause. Inside a clause these are
# fine ("confirm panna sollunga"); clause-final they are a dropped main verb.
_BARE_INFINITIVES = (
    "panna",
    "solla",
    "eduka",
    "edukka",
    "poga",
    "vara",
    "paakka",
    "nikka",
    "kekka",
    "kudukka",
    "wait panna",
)
CLAUSE_FINAL_INFINITIVE = re.compile(
    r"\b(?:" + "|".join(_BARE_INFINITIVES) + r")\s*(?=[,.;!?]|$)", re.I
)

# ---------------------------------------------------------------------------
# English source mood
# ---------------------------------------------------------------------------

# The speaker describes their own future action: "I will cross", "I can walk".
FIRST_PERSON_FUTURE = re.compile(
    r"\bi(?:'ll|'d)\b|\bi\s+(?:will|shall|can|am\s+going\s+to|would)\b|\bi'm\s+going\s+to\b",
    re.I,
)

# Reported speech keeps the original speaker's person in Tamil:
# "the driver said he would reach" → "reach aagiduven-nu sonnaaru".
REPORTED_SPEECH = re.compile(r"\b(?:said|told|mentioned|informed|claimed)\b", re.I)

# Someone else's future action: "he will", "the driver should be able to".
THIRD_PERSON_FUTURE = re.compile(
    r"\b(?:he|she|they|you|driver|drivers)\s+(?:will|would|should|may|might|are|is)\b"
    r"|\bshould\s+be\s+able\s+to\b|\bwill\s+be\b|\bgoing\s+to\s+(?:be|take|reach)\b",
    re.I,
)

# A request framed as a question — needs -alama/-unga, never a flat future.
SUGGESTION_SOURCE = re.compile(
    r"\bwould\s+it\s+be\s+(?:okay|ok|alright|fine|possible)\b"
    r"|\bis\s+it\s+(?:okay|ok|possible|alright|fine)\b"
    r"|\b(?:could|can|shall|should|may)\s+(?:you|we|i)\b"
    r"|\bwould\s+you\s+mind\b"
    r"|\bdo\s+you\s+think\s+you\s+could\b"
    r"|\bany\s+chance\b",
    re.I,
)

# A direct request — needs the polite imperative.
IMPERATIVE_SOURCE = re.compile(
    r"\bplease\b|\bmake\s+sure\b|\bdon'?t\b|\bdo\s+not\b|\bkindly\b", re.I
)


def source_allows_first_sg_future(source: str) -> bool:
    src = source or ""
    return bool(FIRST_PERSON_FUTURE.search(src) or REPORTED_SPEECH.search(src))


def source_allows_plural_future(source: str) -> bool:
    src = source or ""
    return bool(THIRD_PERSON_FUTURE.search(src) or REPORTED_SPEECH.search(src))


def is_suggestion(source: str) -> bool:
    return bool(SUGGESTION_SOURCE.search(source or ""))


def is_imperative(source: str) -> bool:
    return bool(IMPERATIVE_SOURCE.search(source or ""))


def has_request_form(output: str) -> bool:
    """True when the Tanglish carries a polite request/suggestion ending."""
    out = output or ""
    if (
        SUGGESTION.search(out)
        or POLITE_IMPERATIVE.search(out)
        or NEGATIVE_IMPERATIVE.search(out)
    ):
        return True
    # Spoken imperatives that do not end in -unga (still attested in gold pairs).
    return bool(
        re.search(
            r"\b(?:poonga|ponga|vaanga|irukanga|sollung|sollunga|edunga|nikkunga|"
            r"pannatu|pannu|pannunga|wait\s+pann)\b",
            out,
            re.I,
        )
    )
