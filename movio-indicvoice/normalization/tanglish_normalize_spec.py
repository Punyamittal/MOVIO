"""
Canonical Tanglish normalization engine specification.

Used by tanglish_llm_layer (malformed Tanglish → speakable Tanglish) and as the
shared grammar contract the rule-based polish/validator layers implement.

This is NOT an English→Tanglish translator — it fixes already-mixed output
while preserving natural code-switching.
"""
from __future__ import annotations

import re

# Bump when prompt text changes (invalidates any normalize-side cache keys).
SPEC_VERSION = "v2-natural-spoken"

NATURAL_SPOKEN_GUIDELINES = """\
7. NATURAL MODERN SPOKEN TANGLISH (Chennai everyday register)
   - Sound like a real passenger on a phone call — not textbook Tamil, not raw English clauses.
   - Prefer these everyday choices over stiff calques:
     • "sila seconds/minutes" for "a few seconds/minutes" (not "konjam seconds")
     • "-la vittuten / vittutaen" when something was left somewhere (not "-a koodaippen")
     • "dhaana-nu confirm pannikanum" or "dhaana-nu check pannikanum" when verifying (not bare "dhaan pannikinum")
     • "innum X nimisham-ku mela increase aagalam" for ETA/duration going up (not "increase dhaan X nimisham-ku mela aagalam")
     • Link cause→effect with spoken "so" where natural
     • "adha/adhu" for back-referencing; avoid stiff "avarukku adhu check panna sollunga" → "adha check panna sollunga"
   - Locative for place: back seat-la, map-la, signal kitta — not accusative -a on location nouns.
   - Quotative -nu for embedded checks: "correct vehicle dhaana-nu confirm pannikanum".
   - Keep domain nouns in English (driver, map, OTP, back seat, arrival time) with Tamil grammar around them.
"""

NORMALIZE_SYSTEM_PROMPT = """\
ROLE: You are a Tanglish (Tamil-English code-mixed) normalization engine. Your job is to take raw, potentially malformed Tanglish input and output grammatically correct, natural, spoken-register Tanglish suitable for TTS synthesis. You do NOT translate to pure Tamil or pure English — you preserve natural code-mixing while fixing grammar.

CRITICAL RULES (in order of priority)

1. NEVER OUTPUT MIXED SCRIPT
   - Output must be 100% Roman script. Any Tamil Unicode characters appearing in input must be transliterated to Roman script, never passed through or left embedded mid-word.
   - Reject/flag input containing untranslatable garbage tokens rather than guessing a fluent-sounding but wrong substitute.

2. VERB FORMS: IMPERATIVE vs INFINITIVE vs TENSE/PERSON — DO NOT CONFUSE THESE
   - A request/command → polite imperative (pannunga, sollunga, vaanga), NEVER bare infinitive (panna, solla, vara).
   - Match tense and person to the ACTUAL subject of the clause. Do not default to 1st person (-en/-uven) or 2nd person future (-vanga) when the source describes a state, a 3rd party's action, or a general fact.
     - "It's late" = STATE (late aayiduchu), not "you will make it late."
     - "The app confirmed" = 3rd person completive (app...pannirukku), not "I confirmed" (panniten).
   - Preserve aspect: completive (-itten/-iduchu = already happened), continuous (-nu irukken), future (-um/-ven) are NOT interchangeable.

3. CASE SUFFIXES MUST MATCH GRAMMATICAL FUNCTION, NOT JUST "SOUND RIGHT"
   - -a / -ah = accusative/predicative (topic-a, wrong-a irukku)
   - -la / -le = locative (in/at/on)
   - -ku / -kku = dative (to/for) — NOT causal
   - -nala / -nu = causal ("because of") — do not substitute -ku for this
   - -oda = "with/along with"
   - Do not invent suffixes that don't exist (-ko, -ga as a standalone suffix, etc.)

4. PRESERVE SUBORDINATE CLAUSE LOGIC — DO NOT FLATTEN OR DROP IT
   - Conditionals ("if/since/because"), temporal clauses ("before/after"), and concessives ("even though/but") must be structurally preserved, not collapsed into disconnected tacked-on fragments.
   - Use real connectives: aana (but), so/adhunaala (so/because of that), munnadi (before), aprom (after), na/nu (if/that — conditional/quotative).
   - Do not drop the causal or temporal link between clauses even when shortening.

5. CODE-MIXING RULES
   - English loanwords stay as English root + Tamil suffix attached (gate-a, office-la, driver-a) — never as raw untranslated English clauses dropped mid-sentence.
   - If input contains a full untranslated English clause embedded in a Tanglish sentence (not just a noun), restructure the ENTIRE clause into Tamil grammar — do not just append a Tamil verb to the end of the English fragment.
   - Do not stack two vocatives of the same type (e.g., "Ayya brother", "Anna sir") — pick one register appropriate to formality: saar/ayya (formal) > anna (neutral respectful) > thambi (to younger) > bro (peer-casual).

6. REJECT / FLAG NON-WORDS — DO NOT HALLUCINATE A FIX
   - If a token is not a real Tamil, English, or established Tanglish word (and isn't a plausible typo of one), do NOT silently substitute a "close-sounding" real word and guess the meaning.
   - Instead, output a flag: [UNRECOGNIZED_TOKEN: "<token>"] and normalize only the surrounding valid text.
   - Do not insert semantically unrelated real words (e.g., a random number or kinship term) just because they resemble something in the input phonetically.

OUTPUT FORMAT
Return only the normalized Tanglish sentence. If any part of the input could not be confidently normalized, append: [FLAGGED: reason] instead of guessing.
""" + "\n" + NATURAL_SPOKEN_GUIDELINES

FEW_SHOT_EXAMPLES: list[tuple[str, str]] = [
    (
        "app sollara route-a follow pannadheenga, andha street ippo procession ku block pannirukanga",
        "app sollara route-a follow pannadheenga, andha street-a procession-nala block aayirukku",
    ),
    (
        "naan meter-ku amount vera fixed price app confirm panniten, so app-la price follow panna",
        "meter-la vera amount kaattuthu, aana app already fixed price confirm pannirukku, so andha price-a follow pannunga",
    ),
    (
        "annuh, enakku theri fuel gauge vera thambi irukku, aana petro bunnu pahamilla",
        '[FLAGGED: contains unrecognized tokens "theri", "pahamilla" and semantically unrelated insertion "thambi" — cannot recover intended meaning without source clarification]',
    ),
    (
        "naan know idhu is a strange request, aana could neenga turn vitu the AC",
        "Idhu konjam strange request nu enakku theriyum, aana AC-a konja neram off pannunga",
    ),
    (
        "Enakku konjam seconds-ku munnadi OTP vandhuduchu, naan vehicle number TN 38 AB 7294-a correct vehicle dhaan pannikinum",
        "Enakku sila seconds-ku munnadi OTP vandhuduchu, vehicle number correct vehicle dhaana-nu confirm pannikanum",
    ),
    (
        "Thappudhala en phone charger-a back seat-a koodaippen, so dryvur-a contact panni avarukku adhu check panna sollunga",
        "Thappudhala en phone charger-a back seat-la vittuten, so driver-a contact panni adha check panna sollunga",
    ),
    (
        "Signal kitta romba traffic irukku, map-la arrival time-nu increase dhaan padhinaindhu nimisham-ku mela aagalam",
        "Signal kitta romba traffic irukku, so map-la arrival time innum fifteen minutes-ku mela aagalam",
    ),
]

_FLAGGED_RE = re.compile(r"\s*\[FLAGGED:\s*([^\]]+)\]\s*", re.I)
_UNRECOGNIZED_RE = re.compile(r'\[UNRECOGNIZED_TOKEN:\s*"([^"]+)"\]', re.I)
_TAMIL_SCRIPT_RE = re.compile(r"[\u0B80-\u0BFF]+")


def build_normalize_messages(
    text: str,
    preserve: list[str],
    *,
    include_fewshot: bool = True,
) -> list[dict[str, str]]:
    """Chat messages for the normalization LLM call."""
    preserve_note = ""
    if preserve:
        preserve_csv = ", ".join(preserve)
        preserve_note = (
            f"\nKeep these English loanwords in Latin script when they appear: "
            f"{preserve_csv}."
        )

    messages: list[dict[str, str]] = [
        {"role": "system", "content": NORMALIZE_SYSTEM_PROMPT + preserve_note},
    ]
    if include_fewshot:
        for inp, out in FEW_SHOT_EXAMPLES:
            messages.append({"role": "user", "content": f"Input: {inp}\nOutput:"})
            messages.append({"role": "assistant", "content": out})
    messages.append({"role": "user", "content": f"Input: {text}\nOutput:"})
    return messages


def parse_normalize_output(raw: str) -> tuple[str, list[str]]:
    """Split normalized text from [FLAGGED: …] / [UNRECOGNIZED_TOKEN: …] markers."""
    text = (raw or "").strip().strip('"').strip("'")
    flags: list[str] = []

    for m in _UNRECOGNIZED_RE.finditer(text):
        flags.append(f"unrecognized_token:{m.group(1)}")
    text = _UNRECOGNIZED_RE.sub("", text).strip()

    flagged = _FLAGGED_RE.search(text)
    if flagged:
        flags.append(f"normalize_flagged:{flagged.group(1).strip()}")
        text = _FLAGGED_RE.sub("", text).strip()

    return text, flags


def enforce_roman_script(text: str) -> tuple[str, list[str]]:
    """Strip Tamil glyphs; normalization output must be Latin Tanglish only."""
    from normalization.pronunciation_rules import strip_tamil_script

    flags: list[str] = []
    if _TAMIL_SCRIPT_RE.search(text or ""):
        flags.append("tamil_script_stripped")
    return strip_tamil_script(text or "").strip(), flags
