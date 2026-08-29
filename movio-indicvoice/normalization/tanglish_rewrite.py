"""
Deterministic English → spoken Tanglish rewrite for taxi TTS.

Used as the first (instant) engine before small Ollama polish.
Designed for long multi-clause passenger messages that the short
phrase lexicon alone cannot rewrite end-to-end.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_NUM = {
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
    "ten": "10",
}

_MARKER_RE = re.compile(
    r"\b(la|ah|nu|unga|naan|pannu|pannunga|pannirunden|panraaru|pola|"
    r"irukku|vandhu|varum|aagum|aana|nikkiren|sollunga|vendaam|ennoda|"
    r"avarait|avaru|rendu|oru|moonu)\b",
    re.I,
)


def num_word(tok: str) -> str:
    return _NUM.get((tok or "").strip().lower(), tok)


def looks_tanglish(text: str) -> bool:
    t = f" {text or ''} "
    if _MARKER_RE.search(t):
        return True
    # Latin + Tamil script mix
    if re.search(r"[\u0B80-\u0BFF]", t) and re.search(r"[A-Za-z]", t):
        return True
    return False


# Longer patterns first
_CLAUSE_RULES: list[tuple[re.Pattern[str], str | object]] = [
    (
        re.compile(
            r"\bI was supposed to meet the driver at the main gate,?\s*"
            r"but (?:he|she|they) seems? to be waiting near the back entrance\b",
            re.I,
        ),
        "நான் driver-ஐ முன் வாசல்ல சந்திக்க plan பண்ணிருந்தேன், "
        "ஆனா அவர் பின்புற நுழைவாயில் அருகில் காத்திருக்காரு போல இருக்கு",
    ),
    (
        re.compile(
            r"\bI was supposed to meet the driver at the (?P<place>[\w\s]+?),?\s*"
            r"but (?:he|she|they) seems? to be waiting near the (?P<where>[\w\s]+?)(?:\.|$)",
            re.I,
        ),
        lambda m: (
            f"naan driver-a {m.group('place').strip()}-la meet panna plan pannirunden, "
            f"aana avaru {m.group('where').strip()} near-la wait panraaru pola irukku"
        ),
    ),
    (
        re.compile(
            r"\bI am standing outside the main entrance of the building near the security gate\b",
            re.I,
        ),
        "naan building main entrance / security gate near-la veliya nikkiren",
    ),
    (
        re.compile(
            r"\bI'?m standing outside the main entrance of the building near the security gate\b",
            re.I,
        ),
        "naan building main entrance / security gate near-la veliya nikkiren",
    ),
    (
        re.compile(
            r"\b(?:the )?driver told me (?:that )?(?:he|she) would arrive in about (\d+|five|ten|two|three) minutes?\b",
            re.I,
        ),
        lambda m: f"driver {_NUM.get(m.group(1).lower(), m.group(1))} minutes la varuvaaru nu sonnaaru",
    ),
    (
        re.compile(
            r"\b(?:please )?ask (?:him|her|the driver) to wait(?: there)?\b",
            re.I,
        ),
        "driver-ஐ அங்கேயே காத்திருக்கச் சொல்லுங்கள்",
    ),
    (
        re.compile(
            r"\bbecause I have two suitcases, one laptop bag, and an? important document with me\b",
            re.I,
        ),
        "enakku rendu suitcase, oru laptop bag, important document ennoda irukku",
    ),
    (
        re.compile(
            r"\bI have two suitcases, one laptop bag, and an? important document with me\b",
            re.I,
        ),
        "enakku rendu suitcase, oru laptop bag, important document ennoda irukku",
    ),
    (
        re.compile(
            r"\band I do not want to walk all the way to the parking area\b",
            re.I,
        ),
        "parking varaikum walk panna vendaam",
    ),
    (
        re.compile(
            r"\bI do not want to walk all the way to the parking area\b",
            re.I,
        ),
        "parking varaikum walk panna vendaam",
    ),
    (
        re.compile(r"\bdon'?t want to walk all the way to the parking(?: area)?\b", re.I),
        "parking varaikum walk panna vendaam",
    ),
    (
        re.compile(
            r"\bPlease confirm my booking for tomorrow morning and tell the driver I will be at the hotel lobby with three bags\b",
            re.I,
        ),
        "booking confirm pannunga tomorrow morning-ku, driver-kitta sollunga naan hotel lobby-la rendu/three bags-oda irukken",
    ),
    (
        re.compile(
            r"\btell the driver I will be at the (?P<place>[\w\s]+?) with (?P<n>\d+|one|two|three|four|five) bags?\b",
            re.I,
        ),
        lambda m: (
            f"driver-kitta sollunga naan {m.group('place').strip()}-la "
            f"{num_word(m.group('n'))} bags-oda irukken"
        ),
    ),
    (re.compile(r"\bPlease confirm my booking\b", re.I), "booking confirm pannunga"),
    (re.compile(r"\bconfirm my booking\b", re.I), "booking confirm pannunga"),
    (re.compile(r"\btomorrow morning\b", re.I), "tomorrow morning"),
    (re.compile(r"\bhotel lobby\b", re.I), "hotel lobby"),
    (re.compile(r"\bI will be at\b", re.I), "naan irukken"),
    (re.compile(r"\bI was supposed to meet\b", re.I), "naan meet panna plan pannirunden"),
    (re.compile(r"\bmeet the driver at\b", re.I), "driver-a meet panna"),
    (re.compile(r"\b(?:he|she) seems to be waiting near\b", re.I), "அவர் அருகில் காத்திருக்காரு போல"),
    (re.compile(r"\bseems to be waiting\b", re.I), "காத்திருக்காரு போல இருக்கு"),
    (re.compile(r"\bwaiting near the back entrance\b", re.I), "பின்புற நுழைவாயில் அருகில் காத்திருக்காரு"),
    (
        re.compile(
            r"\b(?:the )?driver is waiting near the opposite side of the building because of (?:heavy )?traffic\b",
            re.I,
        ),
        "driver கட்டிடத்துக்கு எதிர்ப்பக்கம் அருகில் காத்திருக்காரு, போக்குவரத்து நெரிசலா இருக்கு",
    ),
    (re.compile(r"\b(?:the )?driver is waiting near the\b", re.I), "driver அருகில் காத்திருக்காரு"),
    (re.compile(r"\bis waiting near the\b", re.I), "அருகில் காத்திருக்காரு"),
    (re.compile(r"\bwaiting near the\b", re.I), "அருகில் காத்திருக்காரு"),
    (re.compile(r"\bwait(?:ing)? near\b", re.I), "அருகில் காத்திரு"),
    (re.compile(r"\b(?:the )?driver is\b", re.I), "driver"),
    (re.compile(r"\bThe driver\b", re.I), "driver"),
    (re.compile(r"\bthe driver\b", re.I), "driver"),
    (re.compile(r"\bat the main gate\b", re.I), "முதன்மை கேட்-ல"),
    (re.compile(r"\bnear the back entrance\b", re.I), "பின்புற நுழைவாயில் அருகில்"),
    (re.compile(r"\bback entrance\b", re.I), "பின்புற நுழைவாயில்"),
    (re.compile(r"\bmain gate\b", re.I), "முதன்மை கேட்"),
    (re.compile(r"\bthree bags\b", re.I), "மூணு bags"),
    (re.compile(r"\btwo bags\b", re.I), "ரெண்டு bags"),
    (re.compile(r"\bone bag\b", re.I), "ஒரு bag"),
    (
        re.compile(r"\bmain entrance of the building near the security gate\b", re.I),
        "கட்டிட முன்வாசல் / security கேட் அருகில்",
    ),
    (re.compile(r"\boutside the main entrance\b", re.I), "முன்வாசல் வெளியில"),
    (re.compile(r"\bmain entrance of the building\b", re.I), "கட்டிடத்துக்கு முன்வாசல்"),
    (re.compile(r"\bnear the security gate\b", re.I), "security கேட் அருகில்"),
    (re.compile(r"\bin about (\d+|five|ten|two|three) minutes?\b", re.I), lambda m: f"சுமார் {num_word(m.group(1))} நிமிடத்துல"),
    (re.compile(r"\bin (\d+) minutes?\b", re.I), r"\1 நிமிடத்துல"),
    (re.compile(r"\byour driver (?:will |has )?(?:arrive|arrived|is arriving)\b", re.I), "unga driver வந்துருவாங்க"),
    (re.compile(r"\bdriver (?:will |has )?(?:arrive|arrived)\b", re.I), "driver வந்துருவாங்க"),
    (re.compile(r"\bI have two suitcases\b", re.I), "எனக்கு ரெண்டு suitcase இருக்கு"),
    (re.compile(r"\btwo suitcases\b", re.I), "ரெண்டு suitcase"),
    (re.compile(r"\bone laptop bag\b", re.I), "ஒரு laptop bag"),
    (re.compile(r"\ban? important document\b", re.I), "முக்கியமான document"),
    (re.compile(r"\bparking area\b", re.I), "parking"),
    (re.compile(r"\bplease wait(?: there)?\b", re.I), "அங்கேயே காத்திருங்க"),
    (re.compile(r"\bplease share (?:your )?otp\b", re.I), "OTP share பண்ணுங்கள்"),
    (re.compile(r"\bshare (?:your )?otp\b", re.I), "OTP share பண்ணுங்கள்"),
    (re.compile(r"\bbooking (?:is )?confirmed\b", re.I), "booking confirm ஆயிடுச்சு"),
    (re.compile(r"\bheavy traffic\b", re.I), "போக்குவரத்து நெரிசலா இருக்கு"),
    (re.compile(r"\btraffic is (?:unusually )?heavy(?: right now)?\b", re.I), "போக்குவரத்து ரொம்ப நெரிசலா இருக்கு"),
    (re.compile(r"\bunusually heavy\b", re.I), "ரொம்ப நெரிசல்"),
    (
        re.compile(
            r"\bI need to reach the airport before (?P<when>.+?)(?:\.|,|$)",
            re.I,
        ),
        lambda m: f"எனக்கு airport {m.group('when').strip()}-க்கு முன்னாடி போகணும்",
    ),
    (
        re.compile(
            r"\bplease ask the driver to take the fastest(?: available)? route\b",
            re.I,
        ),
        "driver-ஐ வேகமான வழி எடுக்கச் சொல்லுங்கள்",
    ),
    (
        re.compile(
            r"\blet me know if the estimated arrival time changes\b",
            re.I,
        ),
        "ETA மாறினா என்கிட்ட சொல்லுங்கள்",
    ),
    (re.compile(r"\bestimated arrival time\b", re.I), "ETA"),
    (re.compile(r"\bfastest(?: available)? route\b", re.I), "வேகமான வழி"),
    (re.compile(r"\bright now\b", re.I), "இப்போ"),
    # Broader Tamil-vocab lexicon (keep loanwords Latin)
    (re.compile(r"\bI need to\b", re.I), "எனக்கு"),
    (re.compile(r"\bI want to\b", re.I), "எனக்கு வேணும்"),
    (re.compile(r"\bI am\b", re.I), "நான்"),
    (re.compile(r"\bI'?m\b", re.I), "நான்"),
    (re.compile(r"\bThe driver is\b", re.I), "driver"),
    (re.compile(r"\bthe driver is\b", re.I), "driver"),
    (re.compile(r"\bplease ask the driver to wait(?: near the)?\b", re.I), "driver-ஐ அருகில் காத்திருக்கச் சொல்லுங்கள்"),
    (re.compile(r"\bask the driver to wait\b", re.I), "driver-ஐ காத்திருக்கச் சொல்லுங்கள்"),
    (re.compile(r"\bI cannot find the (?P<what>[\w\s]+?) because of\b", re.I),
     lambda m: f"எனக்கு {m.group('what').strip()} கண்டுபிடிக்க முடியல காரணமா"),
    (re.compile(r"\bI cannot find the\b", re.I), "எனக்கு கண்டுபிடிக்க முடியல"),
    (re.compile(r"\bcannot find the\b", re.I), "கண்டுபிடிக்க முடியல"),
    (re.compile(r"\bcannot find\b", re.I), "கண்டுபிடிக்க முடியல"),
    (re.compile(r"\bI cannot see\b", re.I), "எனக்கு தெரியல"),
    (re.compile(r"\bnear the\b", re.I), "அருகில்"),
    (re.compile(r"\bnear\b", re.I), "அருகில்"),
    (re.compile(r"\bplease tell the driver\b", re.I), "driver-கிட்ட சொல்லுங்கள்"),
    (re.compile(r"\bplease ask the driver\b", re.I), "driver-ஐ சொல்லுங்கள்"),
    (re.compile(r"\bask the driver to\b", re.I), "driver-ஐ"),
    (re.compile(r"\btell the driver to\b", re.I), "driver-ஐ"),
    (re.compile(r"\bplease\b", re.I), "தயவுசெய்து"),
    (re.compile(r"\breach the airport\b", re.I), "airport போகணும்"),
    (re.compile(r"\breach\b", re.I), "சேரணும்"),
    (re.compile(r"\bbefore\b", re.I), "முன்னாடி"),
    (re.compile(r"\bafter\b", re.I), "அப்புறம்"),
    (re.compile(r"\bwaiting\b", re.I), "காத்திருக்க"),
    (re.compile(r"\bcome closer\b", re.I), "கிட்ட வாங்க"),
    (re.compile(r"\bcome here\b", re.I), "இங்கே வாங்க"),
    (re.compile(r"\bopposite side\b", re.I), "எதிர்ப்பக்கம்"),
    (re.compile(r"\bother side\b", re.I), "மறுபக்கம்"),
    (re.compile(r"\bmain entrance\b", re.I), "முன்வாசல்"),
    (re.compile(r"\bsecurity gate\b", re.I), "security கேட்"),
    (re.compile(r"\bparking (?:area|lot|entrance)\b", re.I), "parking"),
    (re.compile(r"\bpickup (?:point|location)\b", re.I), "பிக்அப் இடம்"),
    (re.compile(r"\bwrong (?:location|entrance|place)\b", re.I), "தவறான இடம்"),
    (re.compile(r"\balternate route\b", re.I), "மாற்று வழி"),
    (re.compile(r"\bU-?turn\b", re.I), "U-turn"),
    (re.compile(r"\btraffic\b", re.I), "போக்குவரத்து"),
    (re.compile(r"\bdelay(?:ed)?\b", re.I), "தாமதம்"),
    (re.compile(r"\bminutes?\b", re.I), "நிமிடம்"),
    (re.compile(r"\bcannot see\b", re.I), "தெரியல"),
    (re.compile(r"\bcoming downstairs\b", re.I), "கீழே வரேன்"),
    (re.compile(r"\bluggage\b", re.I), "சாமான்"),
    (re.compile(r"\bsuitcases?\b", re.I), "suitcase"),
    (re.compile(r"\balready arrived\b", re.I), "ஏற்கனவே வந்துட்டாரு"),
    (re.compile(r"\bon the way\b", re.I), "வழில வராரு"),
    (re.compile(r"\blet me know\b", re.I), "என்கிட்ட சொல்லுங்கள்"),
    (re.compile(r"\bif it changes\b", re.I), "மாறினா"),
    (re.compile(r"\bcab is (?:on the way|coming)\b", re.I), "cab வராது"),
    (re.compile(r"\bthank you\b", re.I), "நன்றி"),
    (re.compile(r"\bwith me\b", re.I), "என்னோட இருக்கு"),
    (re.compile(r"\bbecause of\b", re.I), "காரணமா"),
    (re.compile(r"\bbecause\b", re.I), "காரணமா"),
    (re.compile(r"\bof the building\b", re.I), "கட்டிடத்துக்கு"),
    (re.compile(r"\bbuilding\b", re.I), "கட்டிடம்"),
    (re.compile(r"\bbut\b", re.I), "ஆனா"),
    (re.compile(r"\band\b", re.I), "அப்பறம்"),
    (re.compile(r"\bso\b", re.I), "so"),
]


_CONNECTOR_CLEANUP = [
    (re.compile(r"\s*,\s*so\s+so\b", re.I), ", so"),
    (re.compile(r"\bso so\b", re.I), "so"),
    (re.compile(r"\band and\b", re.I), "and"),
    (re.compile(r"\s{2,}"), " "),
    (re.compile(r"\s+([.,!?])"), r"\1"),
]

# ---------------------------------------------------------------------------
# Pronouns + prepositions → always Tamil script in Tanglish
# (longer / multi-word patterns first)
# ---------------------------------------------------------------------------
_PRONOUN_PREP_EN: list[tuple[re.Pattern[str], str]] = [
    # pronoun phrases
    (re.compile(r"\bwith me\b", re.I), "என்னோட"),
    (re.compile(r"\bto me\b", re.I), "எனக்கு"),
    (re.compile(r"\bfor me\b", re.I), "எனக்காக"),
    (re.compile(r"\bfrom me\b", re.I), "என்னிடமிருந்து"),
    (re.compile(r"\babout me\b", re.I), "என்னைப் பத்தி"),
    (re.compile(r"\bwith you\b", re.I), "உங்களோட"),
    (re.compile(r"\bto you\b", re.I), "உங்களுக்கு"),
    (re.compile(r"\bfor you\b", re.I), "உங்களுக்காக"),
    (re.compile(r"\bwith him\b", re.I), "அவரோட"),
    (re.compile(r"\bto him\b", re.I), "அவருக்கு"),
    (re.compile(r"\bfor him\b", re.I), "அவருக்காக"),
    (re.compile(r"\bfrom him\b", re.I), "அவரிடமிருந்து"),
    (re.compile(r"\bwith her\b", re.I), "அவரோட"),
    (re.compile(r"\bto her\b", re.I), "அவருக்கு"),
    (re.compile(r"\bfor her\b", re.I), "அவருக்காக"),
    (re.compile(r"\bwith us\b", re.I), "நம்மளோட"),
    (re.compile(r"\bto us\b", re.I), "நம்மளுக்கு"),
    (re.compile(r"\bfor us\b", re.I), "நம்மளுக்காக"),
    (re.compile(r"\bwith them\b", re.I), "அவங்களோட"),
    (re.compile(r"\bto them\b", re.I), "அவங்களுக்கு"),
    (re.compile(r"\bfor them\b", re.I), "அவங்களுக்காக"),
    (re.compile(r"\beach other\b", re.I), "ஒருத்தர ஒருத்தர"),
    (re.compile(r"\bone another\b", re.I), "ஒருத்தர ஒருத்தர"),
    # subject / object / possessive pronouns
    (re.compile(r"\bI'?m\b", re.I), "நான்"),
    (re.compile(r"\bI am\b", re.I), "நான்"),
    (re.compile(r"\bI'?ve\b", re.I), "எனக்கு"),
    (re.compile(r"\bI have\b", re.I), "எனக்கு"),
    (re.compile(r"\bI\b", re.I), "நான்"),
    (re.compile(r"\bme\b", re.I), "என்னை"),
    (re.compile(r"\bmy\b", re.I), "என்"),
    (re.compile(r"\bmine\b", re.I), "என்னோடது"),
    (re.compile(r"\bmyself\b", re.I), "நானே"),
    (re.compile(r"\byou'?re\b", re.I), "நீங்க"),
    (re.compile(r"\byou are\b", re.I), "நீங்க"),
    (re.compile(r"\byou\b", re.I), "நீங்க"),
    (re.compile(r"\byour\b", re.I), "உங்க"),
    (re.compile(r"\byours\b", re.I), "உங்களுடையது"),
    (re.compile(r"\byourself\b", re.I), "நீங்களே"),
    (re.compile(r"\bhe'?s\b", re.I), "அவர்"),
    (re.compile(r"\bhe is\b", re.I), "அவர்"),
    (re.compile(r"\bhe\b", re.I), "அவர்"),
    (re.compile(r"\bhim\b", re.I), "அவரை"),
    (re.compile(r"\bhis\b", re.I), "அவருடைய"),
    (re.compile(r"\bhimself\b", re.I), "அவரே"),
    (re.compile(r"\bshe'?s\b", re.I), "அவர்"),
    (re.compile(r"\bshe is\b", re.I), "அவர்"),
    (re.compile(r"\bshe\b", re.I), "அவர்"),
    (re.compile(r"\bher\b", re.I), "அவரை"),
    (re.compile(r"\bhers\b", re.I), "அவருடையது"),
    (re.compile(r"\bherself\b", re.I), "அவரே"),
    (re.compile(r"\bwe'?re\b", re.I), "நாங்க"),
    (re.compile(r"\bwe are\b", re.I), "நாங்க"),
    (re.compile(r"\bwe\b", re.I), "நாங்க"),
    (re.compile(r"\bus\b", re.I), "நம்மளை"),
    (re.compile(r"\bour\b", re.I), "நம்ம"),
    (re.compile(r"\bours\b", re.I), "நம்மளுடையது"),
    (re.compile(r"\bourselves\b", re.I), "நாங்களே"),
    (re.compile(r"\bthey'?re\b", re.I), "அவங்க"),
    (re.compile(r"\bthey are\b", re.I), "அவங்க"),
    (re.compile(r"\bthey\b", re.I), "அவங்க"),
    (re.compile(r"\bthem\b", re.I), "அவங்களை"),
    (re.compile(r"\btheir\b", re.I), "அவங்களுடைய"),
    (re.compile(r"\btheirs\b", re.I), "அவங்களுடையது"),
    (re.compile(r"\bthemselves\b", re.I), "அவங்களே"),
    (re.compile(r"\bit'?s\b", re.I), "அது"),
    (re.compile(r"\bit is\b", re.I), "அது"),
    (re.compile(r"\bit\b", re.I), "அது"),
    (re.compile(r"\bits\b", re.I), "அதோட"),
    (re.compile(r"\bitself\b", re.I), "அதே"),
    (re.compile(r"\bthis\b", re.I), "இது"),
    (re.compile(r"\bthat\b", re.I), "அது"),
    (re.compile(r"\bthese\b", re.I), "இவை"),
    (re.compile(r"\bthose\b", re.I), "அவை"),
    (re.compile(r"\bwho\b", re.I), "யார்"),
    (re.compile(r"\bwhom\b", re.I), "யாரை"),
    (re.compile(r"\bwhose\b", re.I), "யாருடைய"),
    (re.compile(r"\bwhich\b", re.I), "எந்த"),
    (re.compile(r"\bwhat\b", re.I), "என்ன"),
    (re.compile(r"\banyone\b", re.I), "யாராவது"),
    (re.compile(r"\bsomeone\b", re.I), "யாரோ"),
    (re.compile(r"\beveryone\b", re.I), "எல்லாரும்"),
    (re.compile(r"\bnobody\b", re.I), "யாரும் இல்ல"),
    (re.compile(r"\bnothing\b", re.I), "ஒன்னும் இல்ல"),
    (re.compile(r"\bsomething\b", re.I), "ஏதோ"),
    (re.compile(r"\beverything\b", re.I), "எல்லாம்"),
    # multi-word prepositions
    (re.compile(r"\bin front of\b", re.I), "முன்னாடி"),
    (re.compile(r"\bin back of\b", re.I), "பின்னாடி"),
    (re.compile(r"\bnext to\b", re.I), "அருகில்"),
    (re.compile(r"\bclose to\b", re.I), "கிட்ட"),
    (re.compile(r"\binstead of\b", re.I), "பதிலா"),
    (re.compile(r"\bbecause of\b", re.I), "காரணமா"),
    (re.compile(r"\bout of\b", re.I), "வெளியில இருந்து"),
    (re.compile(r"\baway from\b", re.I), "தள்ளி"),
    (re.compile(r"\bin to\b", re.I), "உள்ளே"),
    (re.compile(r"\bon to\b", re.I), "மேல"),
    (re.compile(r"\bin between\b", re.I), "இடையில"),
    (re.compile(r"\baccording to\b", re.I), "படி"),
    (re.compile(r"\bdue to\b", re.I), "காரணமா"),
    (re.compile(r"\bprior to\b", re.I), "முன்னாடி"),
    (re.compile(r"\bas for\b", re.I), "பொறுத்தவரை"),
    (re.compile(r"\bas of\b", re.I), "முதல்"),
    (re.compile(r"\bup to\b", re.I), "வரைக்கும்"),
    (re.compile(r"\bout from\b", re.I), "வெளியில இருந்து"),
    # single prepositions
    (re.compile(r"\bnear\b", re.I), "அருகில்"),
    (re.compile(r"\bbeside\b", re.I), "அருகில்"),
    (re.compile(r"\bbesides\b", re.I), "தவிர"),
    (re.compile(r"\bbehind\b", re.I), "பின்னாடி"),
    (re.compile(r"\bbeyond\b", re.I), "தள்ளி"),
    (re.compile(r"\binside\b", re.I), "உள்ளே"),
    (re.compile(r"\boutside\b", re.I), "வெளியில"),
    (re.compile(r"\bwithin\b", re.I), "உள்ளே"),
    (re.compile(r"\bwithout\b", re.I), "இல்லாம"),
    (re.compile(r"\bwith\b", re.I), "உடன்"),
    (re.compile(r"\bfrom\b", re.I), "இருந்து"),
    (re.compile(r"\binto\b", re.I), "உள்ளே"),
    (re.compile(r"\bonto\b", re.I), "மேல"),
    (re.compile(r"\bupon\b", re.I), "மேல"),
    (re.compile(r"\bover\b", re.I), "மேல"),
    (re.compile(r"\bunder\b", re.I), "கீழே"),
    (re.compile(r"\bbeneath\b", re.I), "கீழே"),
    (re.compile(r"\bbelow\b", re.I), "கீழே"),
    (re.compile(r"\babove\b", re.I), "மேல"),
    (re.compile(r"\bbetween\b", re.I), "இடையில"),
    (re.compile(r"\bamong\b", re.I), "நடுவுல"),
    (re.compile(r"\bamongst\b", re.I), "நடுவுல"),
    (re.compile(r"\bthrough\b", re.I), "வழியா"),
    (re.compile(r"\bthroughout\b", re.I), "முழுவதும்"),
    (re.compile(r"\bacross\b", re.I), "குறுக்கே"),
    (re.compile(r"\baround\b", re.I), "சுத்தி"),
    (re.compile(r"\balong\b", re.I), "வழியா"),
    (re.compile(r"\btoward(?:s)?\b", re.I), "நோக்கி"),
    (re.compile(r"\bagainst\b", re.I), "எதிரா"),
    (re.compile(r"\bduring\b", re.I), "போது"),
    (re.compile(r"\bbefore\b", re.I), "முன்னாடி"),
    (re.compile(r"\bafter\b", re.I), "அப்புறம்"),
    (re.compile(r"\buntil\b", re.I), "வரைக்கும்"),
    (re.compile(r"\btill\b", re.I), "வரைக்கும்"),
    (re.compile(r"\bsince\b", re.I), "இருந்து"),
    (re.compile(r"\babout\b", re.I), "பத்தி"),
    (re.compile(r"\bacross from\b", re.I), "எதிரே"),
    (re.compile(r"\bopposite side\b", re.I), "எதிர்ப்பக்கம்"),
    (re.compile(r"\bother side\b", re.I), "மறுபக்கம்"),
    (re.compile(r"\bopposite\b", re.I), "எதிர்ப்பக்கம்"),
    (re.compile(r"\bpast\b", re.I), "கடந்து"),
    (re.compile(r"\bvia\b", re.I), "வழியா"),
    (re.compile(r"\bper\b", re.I), "ஒன்றுக்கு"),
    (re.compile(r"\bversus\b", re.I), "எதிரா"),
    (re.compile(r"\bvs\.?\b", re.I), "எதிரா"),
    (re.compile(r"\blike\b", re.I), "மாதிரி"),
    (re.compile(r"\bunlike\b", re.I), "மாதிரி இல்லாம"),
    (re.compile(r"\bas\b", re.I), "மாதிரி"),
    (re.compile(r"\bby\b", re.I), "மூலமா"),
    (re.compile(r"\bat\b", re.I), "ல"),
    (re.compile(r"\bin\b", re.I), "ல"),
    (re.compile(r"\bon\b", re.I), "மேல"),
    (re.compile(r"\boff\b", re.I), "விட்டு"),
    (re.compile(r"\bup\b", re.I), "மேல"),
    (re.compile(r"\bdown\b", re.I), "கீழே"),
    (re.compile(r"\bout\b", re.I), "வெளியில"),
    # carefully scoped "to" / "for" / "of" (bare forms are risky)
    (re.compile(r"\bof the\b", re.I), ""),
    (re.compile(r"\bof\b", re.I), "உடைய"),
]

# Latin-script Tanglish pronouns/prepositions → Tamil script
# Avoid matching inside hyphen compounds (suitcase-oda, vehicle-kulla, entrance-ku)
def _lat(word: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9_]){word}(?![A-Za-z0-9_])", re.I)


_LATIN_PRONOUN_PREP_TO_TA: list[tuple[re.Pattern[str], str]] = [
    (_lat(r"naan"), "நான்"),
    (_lat(r"nan"), "நான்"),
    (_lat(r"enakku"), "எனக்கு"),
    (_lat(r"enaku"), "எனக்கு"),
    (_lat(r"ennoda"), "என்னோட"),
    (_lat(r"ennodaya"), "என்னோட"),
    (_lat(r"enna"), "என்னை"),
    (_lat(r"ennai"), "என்னை"),
    (_lat(r"en"), "என்"),
    (_lat(r"neenga"), "நீங்க"),
    (_lat(r"unga"), "உங்க"),
    (_lat(r"ungalukku"), "உங்களுக்கு"),
    (_lat(r"avaru"), "அவர்"),
    (_lat(r"avara"), "அவரை"),
    (_lat(r"avarait"), "அவரை"),
    (_lat(r"avanga"), "அவங்க"),
    (_lat(r"naanga"), "நாங்க"),
    (_lat(r"namma"), "நம்ம"),
    (_lat(r"adhu"), "அது"),
    (_lat(r"idhu"), "இது"),
    (_lat(r"yaar"), "யார்"),
    (_lat(r"aana"), "ஆனா"),
    (_lat(r"pakkathula"), "அருகில்"),
    (_lat(r"pakkathil"), "அருகில்"),
    (_lat(r"kitta"), "கிட்ட"),
    (_lat(r"kittaye"), "கிட்ட"),
    (_lat(r"munnaadi"), "முன்னாடி"),
    (_lat(r"munnadi"), "முன்னாடி"),
    (_lat(r"pinnaadi"), "பின்னாடி"),
    (_lat(r"pinnadi"), "பின்னாடி"),
    (_lat(r"veliya"), "வெளியில"),
    (_lat(r"keezha"), "கீழே"),
    (_lat(r"mela"), "மேல"),
    (_lat(r"irundhu"), "இருந்து"),
    (_lat(r"varaikkum"), "வரைக்கும்"),
    (_lat(r"appuram"), "அப்புறம்"),
    (_lat(r"apram"), "அப்புறம்"),
    (_lat(r"ethir"), "எதிரே"),
    (_lat(r"ethire"), "எதிரே"),
    (_lat(r"nokki"), "நோக்கி"),
    (_lat(r"suthi"), "சுத்தி"),
    (_lat(r"pathi"), "பத்தி"),
    (_lat(r"paththi"), "பத்தி"),
    (_lat(r"illama"), "இல்லாம"),
    (re.compile(r"\bnear-la\b", re.I), "அருகில்"),
    (re.compile(r"\bopp(?:osite)?-la\b", re.I), "எதிர்ப்பக்கம்"),
    # standalone location words only (not -ulla / -kulla / -oda suffixes)
    (re.compile(r"(?<![A-Za-z0-9_-])ulla(?![A-Za-z0-9_-])", re.I), "உள்ளே"),
    (re.compile(r"(?<![A-Za-z0-9_-])oda(?![A-Za-z0-9_-])", re.I), "உடன்"),
]


def force_tamil_pronouns_preps(text: str) -> str:
    """Force pronouns & prepositions into Tamil script for Tanglish TTS."""
    out = (text or "").strip()
    if not out:
        return out
    for pattern, repl in _PRONOUN_PREP_EN:
        out = pattern.sub(repl, out)
    for pattern, repl in _LATIN_PRONOUN_PREP_TO_TA:
        out = pattern.sub(repl, out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = re.sub(r"\s+([.,!?])", r"\1", out)
    return out


_GOLD_PATH = Path(__file__).resolve().parent / "tanglish_gold_pairs.json"


def _norm_key(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"[“”\"']", "", t)
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[.!?]+$", "", t).strip()
    return t


def lookup_gold_tanglish(text: str) -> str | None:
    """Exact (normalized) English → natural Tanglish gold hit."""
    from normalization.tanglish_translator import exact_gold

    return exact_gold(text)


def rewrite_en_to_tanglish(text: str) -> str:
    """Apply gold pairs, then clause/phrase rules. Always returns a string."""
    out = (text or "").strip()
    if not out:
        return out

    gold = lookup_gold_tanglish(out)
    if gold:
        return force_tamil_pronouns_preps(gold)

    # Security gate + opposite side of road + turn around to main entrance
    m = re.search(
        r"standing (?:near )?(?:the )?security gate.+red suitcase.+"
        r"driver has stopped on the opposite side.+turn around.+main entrance",
        out,
        re.I | re.S,
    )
    if m:
        return force_tamil_pronouns_preps(
            "Naan security gate pakkathula red suitcase-oda nikkiren, "
            "aana driver road-oda opposite side-la stop pannitaanga, "
            "so avara thirumbi main entrance-ku vara sollunga."
        )

    # Prefer whole-message templates for common passenger lines
    m = re.search(
        r"standing outside.+security gate.+driver told me.+five minutes.+wait there.+suitcases.+parking",
        out,
        re.I | re.S,
    )
    if m:
        return force_tamil_pronouns_preps(
            "நான் கட்டிட முன்வாசல் / security gate அருகில் வெளியில நிற்கிறேன். "
            "driver ஐந்து நிமிடத்துல வருவாருன்னு சொன்னாரு, so அங்கேயே காத்திருக்கச் சொல்லுங்கள் — "
            "எனக்கு ரெண்டு suitcase, ஒரு laptop bag, முக்கியமான document இருக்கு, "
            "parking வரைக்கும் நடக்க வேண்டாம்."
        )

    m = re.search(
        r"supposed to meet the driver.+main gate.+waiting near the back entrance",
        out,
        re.I | re.S,
    )
    if m:
        return force_tamil_pronouns_preps(
            "நான் driver-ஐ முன் வாசல்ல சந்திக்க plan பண்ணிருந்தேன், "
            "ஆனா அவர் பின்புற நுழைவாயில் அருகில் காத்திருக்காரு போல இருக்கு."
        )

    # Airport + heavy traffic + fastest route (common passenger urgency line)
    m = re.search(
        r"need to reach the airport before (?P<when>.+?)[,.]?\s*"
        r"(?:aana|but|,)?\s*(?:the )?traffic is (?:unusually )?heavy(?: right now)?[,.]?\s*"
        r"(?:so )?please ask the driver to take the fastest(?: available)? route"
        r"(?: and let me know if the estimated arrival time changes)?",
        out,
        re.I | re.S,
    )
    if m:
        when = m.group("when").strip().rstrip(".,")
        return force_tamil_pronouns_preps(
            f"எனக்கு airport {when}-க்கு முன்னாடி போகணும், "
            "ஆனா இப்போ போக்குவரத்து ரொம்ப நெரிசலா இருக்கு, "
            "so driver-ஐ வேகமான வழி எடுக்கச் சொல்லுங்கள், "
            "ETA மாறினா என்கிட்ட சொல்லுங்கள்."
        )

    for pattern, repl in _CLAUSE_RULES:
        out = pattern.sub(repl, out)

    for pattern, repl in _CONNECTOR_CLEANUP:
        out = pattern.sub(repl, out)

    return force_tamil_pronouns_preps(out.strip())
