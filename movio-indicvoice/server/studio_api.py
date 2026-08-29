"""
Studio platform APIs: normalize preview, pronunciation lexicon, scenario library.
Mounted alongside the TTS server — does not change the core /tts path.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import EVALUATION_RESULTS_DIR, PRONUNCIATION_LEXICON_PATH, PROJECT_ROOT
from normalization.deterministic_normalizer import (
    apply_lexicon,
    normalize,
    normalize_booking_ids_and_plates,
    normalize_cardinal_numbers,
    normalize_currency,
    normalize_dates,
    normalize_distances,
    normalize_otp_and_short_codes,
    normalize_phone_numbers,
    normalize_times,
)
from normalization.language_translator import detect_language

logger = logging.getLogger("server.studio_api")
router = APIRouter(tags=["studio"])

DATA_DIR = PROJECT_ROOT / "server" / "data"
OVERRIDES_PATH = DATA_DIR / "lexicon_overrides.json"
COMPARISONS_PATH = DATA_DIR / "saved_comparisons.jsonl"

RULE_META = {
    "otp": {
        "label": "OTP",
        "id": "otp",
        "description": "OTP / PIN / short codes are spoken digit-by-digit for clarity.",
    },
    "phone": {
        "label": "Phone",
        "id": "phone",
        "description": "Phone numbers are expanded digit-by-digit for natural TTS.",
    },
    "booking_id": {
        "label": "Booking ID",
        "id": "booking_id",
        "description": "Vehicle/booking IDs are spelled out character by character so each digit and letter is pronounced distinctly.",
    },
    "currency": {
        "label": "Currency+Distance",
        "id": "currency",
        "description": "Currency amounts and distances become spoken rupees / kilometres.",
    },
    "time": {
        "label": "Time",
        "id": "time",
        "description": "Clock times become natural spoken forms (e.g. 7:30 PM → seven thirty PM).",
    },
    "date": {
        "label": "Time",
        "id": "date",
        "description": "Numeric dates expand into spoken calendar forms.",
    },
    "cardinal": {
        "label": "Time",
        "id": "cardinal",
        "description": "Standalone cardinals become spoken number words.",
    },
    "lexicon": {
        "label": "Tanglish",
        "id": "lexicon",
        "description": "Pronunciation lexicon / place-name overrides applied.",
    },
}

SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "book-en",
        "category": "Booking",
        "lang": "en",
        "title": "New Ride Booking — English",
        "blurb": "Confirm a new booking with pickup, drop, vehicle and fare.",
        "text": "Thank you for booking with Movio. Your cab has been confirmed. Pickup at Chennai Central, drop at T Nagar. Vehicle: sedan. Fare: ₹185. Your booking ID is TN45AB1234. The driver will arrive in 10 minutes.",
        "tags": ["booking", "confirmation", "fare"],
    },
    {
        "id": "book-ta",
        "category": "Booking",
        "lang": "ta",
        "title": "New Ride Booking — Tamil",
        "blurb": "Tamil confirmation for a new ride booking.",
        "text": "வணக்கம். உங்கள் பயணம் உறுதி செய்யப்பட்டது. பிக்அப்: சென்னை சென்ட்ரல். டிராப்: திருநகர். வாகனம்: செடான். கட்டணம்: 185 ரூபாய். ஓட்டுநர் 10 நிமிடங்களில் வருவார்.",
        "tags": ["booking", "tamil", "confirmation"],
    },
    {
        "id": "book-tanglish",
        "category": "Booking",
        "lang": "tanglish",
        "title": "New Ride Booking — Tanglish",
        "blurb": "Code-mixed Tamil-English booking confirmation.",
        "text": "உங்கள் pickup location Chennai Central-ல இருக்கா? Your cab will arrive in 10 minutes. Booking ID: TN45AB1234. Fare: ₹185.",
        "tags": ["booking", "tanglish", "code-mix"],
    },
    {
        "id": "status-en",
        "category": "Ride Status",
        "lang": "en",
        "title": "Ride Status — ETA Update",
        "blurb": "Driver is approaching the pickup location.",
        "text": "Your driver Karthik is on the way and will arrive in approximately 4 minutes. Vehicle number: TN45AB1234. Please be ready at the pickup point.",
        "tags": ["eta", "status", "driver"],
    },
    {
        "id": "status-ta",
        "category": "Ride Status",
        "lang": "ta",
        "title": "Ride Status — Tamil",
        "blurb": "Tamil ride status update.",
        "text": "உங்கள் ஓட்டுநர் கார்த்திக் 4 நிமிடங்களில் வந்து சேர்வார். வாகன எண்: TN45AB1234. தயவு செய்து பிக்அப் இடத்தில் காத்திருக்கவும்.",
        "tags": ["status", "tamil", "eta"],
    },
    {
        "id": "cancel-en",
        "category": "Cancellation",
        "lang": "en",
        "title": "Cancellation — Customer Initiated",
        "blurb": "Acknowledge a customer cancellation request.",
        "text": "Your booking TN45AB1234 has been cancelled successfully. A cancellation fee of ₹25 will apply. Would you like to book another ride?",
        "tags": ["cancel", "fee"],
    },
    {
        "id": "cancel-ta",
        "category": "Cancellation",
        "lang": "ta",
        "title": "Cancellation — Tamil",
        "blurb": "Tamil cancellation acknowledgment.",
        "text": "உங்கள் பயணம் TN45AB1234 ரத்து செய்யப்பட்டது. ரத்து கட்டணம் 25 ரூபாய் பொருந்தும். மீண்டும் பயணம் பதிவு செய்யவா?",
        "tags": ["cancel", "tamil"],
    },
    {
        "id": "driver-en",
        "category": "Driver Coordination",
        "lang": "en",
        "title": "Driver Coordination — Pickup instruction",
        "blurb": "Agent instructs driver about pickup point details.",
        "text": "Driver, your customer is waiting at Gate 2, Chennai Central. Customer phone: 9876543210. Please call before arriving. OTP for trip start: 4821.",
        "tags": ["driver", "pickup", "otp"],
    },
    {
        "id": "driver-tanglish",
        "category": "Driver Coordination",
        "lang": "tanglish",
        "title": "Driver Coordination — Tanglish",
        "blurb": "Tanglish driver coordination message.",
        "text": "Driver, customer Gate 2-ல காத்திருக்காரு. Phone: 9876543210. Reach ஆகும் முன்னாடி call பண்ணுங்க. Trip start OTP: 4821.",
        "tags": ["driver", "tanglish", "pickup"],
    },
    {
        "id": "support-en",
        "category": "Customer Support",
        "lang": "en",
        "title": "Customer Support — Fare dispute",
        "blurb": "Acknowledge a fare dispute and offer resolution.",
        "text": "I understand your concern about the fare. The final amount was ₹210 instead of the estimated ₹185. This is due to a route change of 3.2 km. I can offer a ₹15 refund to your wallet.",
        "tags": ["support", "refund", "fare"],
    },
    {
        "id": "support-ta",
        "category": "Customer Support",
        "lang": "ta",
        "title": "Customer Support — Lost item",
        "blurb": "Tamil support for a lost-item report.",
        "text": "உங்கள் பொருள் காரில் கிடைத்தது. ஓட்டுநர் உங்கள் இடத்திற்கு 30 நிமிடங்களில் கொண்டு வருவார். தொடர்பு எண்: 9876543210.",
        "tags": ["support", "lost", "tamil"],
    },
    {
        "id": "otp-en",
        "category": "OTP",
        "lang": "en",
        "title": "OTP Delivery — English",
        "blurb": "OTP verification for trip start.",
        "text": "Your OTP for starting the trip is 4821. Please share this with the driver to begin your ride.",
        "tags": ["otp", "verification"],
    },
    {
        "id": "otp-tanglish",
        "category": "OTP",
        "lang": "tanglish",
        "title": "OTP Delivery — Tanglish",
        "blurb": "Tanglish OTP delivery.",
        "text": "Trip ஆரம்பிக்க OTP: 4821. Driver கிட்ட சொல்லுங்க. Please do not share with anyone else.",
        "tags": ["otp", "tanglish"],
    },
]

AGENT_FLOWS: dict[str, list[dict[str, str]]] = {
    "book-en": [
        {"role": "user", "text": "I need a cab from Chennai Central to T Nagar."},
        {
            "role": "agent",
            "text": "Thank you for booking with Movio. Your cab has been confirmed. Pickup at Chennai Central, drop at T Nagar. Fare: ₹185. Booking ID: TN45AB1234. The driver will arrive in 10 minutes.",
        },
        {"role": "user", "text": "What is the OTP?"},
        {
            "role": "agent",
            "text": "Your OTP for starting the trip is 4821. Please share this with the driver to begin your ride.",
        },
    ],
    "status-en": [
        {"role": "user", "text": "Where is my driver?"},
        {
            "role": "agent",
            "text": "Your driver Karthik is on the way and will arrive in approximately 4 minutes. Vehicle number: TN45AB1234. Please be ready at the pickup point.",
        },
    ],
    "otp-en": [
        {"role": "user", "text": "Send me the trip OTP."},
        {
            "role": "agent",
            "text": "Your OTP for starting the trip is 4821. Please share this with the driver to begin your ride.",
        },
    ],
    "cancel-en": [
        {"role": "user", "text": "Please cancel my booking."},
        {
            "role": "agent",
            "text": "Your booking TN45AB1234 has been cancelled successfully. A cancellation fee of ₹25 will apply. Would you like to book another ride?",
        },
    ],
    "support-en": [
        {"role": "user", "text": "Why was I charged more than the estimate?"},
        {
            "role": "agent",
            "text": "I understand your concern about the fare. The final amount was ₹210 instead of the estimated ₹185. This is due to a route change of 3.2 km. I can offer a ₹15 refund to your wallet.",
        },
    ],
}


class NormalizeRequest(BaseModel):
    text: str = Field(..., min_length=1)
    target_lang: Optional[str] = None
    use_overrides: bool = True


class LexiconItem(BaseModel):
    word: str = Field(..., min_length=1)
    spoken: str = Field(..., min_length=1)
    lang: str = "all"
    note: str = ""


class ComparisonSave(BaseModel):
    text: str
    lang: str = "en"
    side_a: dict[str, Any]
    side_b: dict[str, Any]
    winner: str = ""  # a | b | tie | ""


def _load_base_lexicon() -> dict[str, str]:
    try:
        raw = json.loads(PRONUNCIATION_LEXICON_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return {k: v for k, v in raw.items() if not str(k).startswith("_") and str(v).strip()}


def _load_overrides() -> list[dict[str, Any]]:
    if not OVERRIDES_PATH.exists():
        return []
    try:
        data = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
        return list(data) if isinstance(data, list) else []
    except Exception:  # noqa: BLE001
        return []


def _save_overrides(items: list[dict[str, Any]]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OVERRIDES_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _merged_lexicon(use_overrides: bool = True) -> dict[str, str]:
    lex = _load_base_lexicon()
    if use_overrides:
        for item in _load_overrides():
            w = str(item.get("word") or "").strip()
            s = str(item.get("spoken") or "").strip()
            if w and s:
                lex[w] = s
    return lex


def _find_token_diffs(before: str, after: str) -> list[tuple[str, str]]:
    if before == after:
        return []
    # Prefer concrete alnum/token replacements.
    bw = re.findall(r"[A-Za-z0-9₹.]+|[\u0B80-\u0BFF]+", before)
    aw = re.findall(r"[A-Za-z0-9₹.]+|[\u0B80-\u0BFF]+", after)
    if bw != aw:
        # Simple sequence diff for first changed span
        i = 0
        while i < min(len(bw), len(aw)) and bw[i] == aw[i]:
            i += 1
        j = 0
        while j < min(len(bw) - i, len(aw) - i) and bw[-(j + 1)] == aw[-(j + 1)]:
            j += 1
        left_b = " ".join(bw[i : len(bw) - j if j else None])
        left_a = " ".join(aw[i : len(aw) - j if j else None])
        if left_b or left_a:
            return [(left_b or before, left_a or after)]
    return [(before, after)]


def _rule_breakdown(text: str, lexicon: dict[str, str]) -> tuple[str, list[dict[str, Any]]]:
    steps: list[tuple[str, Any]] = [
        ("otp", normalize_otp_and_short_codes),
        ("phone", normalize_phone_numbers),
        ("booking_id", normalize_booking_ids_and_plates),
        ("currency", lambda t: normalize_distances(normalize_currency(t))),
        ("time", normalize_times),
        ("date", normalize_dates),
        ("cardinal", normalize_cardinal_numbers),
        ("lexicon", lambda t: apply_lexicon(t, lexicon) if lexicon else t),
    ]
    cur = text
    rules: list[dict[str, Any]] = []
    for key, fn in steps:
        nxt = fn(cur)
        if nxt != cur:
            meta = RULE_META[key]
            for src, dst in _find_token_diffs(cur, nxt):
                rules.append(
                    {
                        "label": meta["label"],
                        "id": meta["id"],
                        "description": meta["description"],
                        "from": src,
                        "to": dst,
                    }
                )
            cur = nxt
    return cur, rules


class NormalizeRequestModel(NormalizeRequest):
    pass


@router.post("/studio/normalize")
async def studio_normalize(body: NormalizeRequest):
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "text required")
    detected = detect_language(text)
    target = (body.target_lang or detected or "tanglish").lower().strip()
    if target in ("tamil", "ta-in"):
        target = "ta"
    if target in ("english", "en-in"):
        target = "en"

    # English → Tanglish must use the same translate path as POST /tts.
    if target == "tanglish" and detected == "en":
        from server.pipeline import preview_tts_text

        normalized, meta = preview_tts_text(text, target_lang="tanglish")
        return {
            "ok": True,
            "input": text,
            "normalized": normalized,
            "detected_lang": detected,
            "target_lang": target,
            "translator_engine": meta.get("translator_engine", ""),
            "translated_text": meta.get("translated_text", ""),
            "tanglish_audit": meta.get("tanglish_audit"),
            "chars": len(text),
            "transformations": 0,
            "rules": [],
            "tabs": ["Booking ID", "OTP", "Phone", "Time", "Currency+Distance", "Tanglish"],
        }

    lex = _merged_lexicon(body.use_overrides)
    normalized, rules = _rule_breakdown(text, lex)
    # Ensure full pipeline match
    full = normalize(text, lexicon=lex)
    if full != normalized:
        normalized = full
    return {
        "ok": True,
        "input": text,
        "normalized": normalized,
        "detected_lang": detected,
        "target_lang": body.target_lang or detected,
        "chars": len(text),
        "transformations": len(rules),
        "rules": rules,
        "tabs": ["Booking ID", "OTP", "Phone", "Time", "Currency+Distance", "Tanglish"],
    }


@router.get("/studio/lexicon")
async def get_lexicon():
    base = _load_base_lexicon()
    overrides = _load_overrides()
    return {
        "ok": True,
        "base": [{"word": k, "spoken": v, "source": "base"} for k, v in base.items()],
        "overrides": overrides,
        "count": len(overrides),
    }


@router.post("/studio/lexicon")
async def add_lexicon(item: LexiconItem):
    items = _load_overrides()
    entry = {
        "word": item.word.strip(),
        "spoken": item.spoken.strip(),
        "lang": item.lang or "all",
        "note": item.note or "",
    }
    # Replace existing same word
    items = [x for x in items if str(x.get("word", "")).lower() != entry["word"].lower()]
    items.append(entry)
    _save_overrides(items)
    return {"ok": True, "overrides": items, "count": len(items)}


@router.delete("/studio/lexicon")
async def clear_lexicon():
    _save_overrides([])
    return {"ok": True, "overrides": [], "count": 0}


@router.delete("/studio/lexicon/{word}")
async def delete_lexicon_word(word: str):
    items = [x for x in _load_overrides() if str(x.get("word", "")).lower() != word.lower()]
    _save_overrides(items)
    return {"ok": True, "overrides": items, "count": len(items)}


@router.get("/studio/scenarios")
async def list_scenarios():
    cats: dict[str, int] = {}
    for s in SCENARIOS:
        cats[s["category"]] = cats.get(s["category"], 0) + 1
    # Merge acceptance test count for realism
    acceptance_n = 0
    path = EVALUATION_RESULTS_DIR / "acceptance_results.json"
    if path.exists():
        try:
            acceptance_n = int(json.loads(path.read_text(encoding="utf-8")).get("total") or 0)
        except Exception:  # noqa: BLE001
            acceptance_n = 0
    return {
        "ok": True,
        "categories": cats,
        "scenarios": SCENARIOS,
        "acceptance_cases": acceptance_n,
        "total": len(SCENARIOS),
    }


@router.get("/studio/agent/flows")
async def agent_flows():
    return {
        "ok": True,
        "flows": [
            {
                "id": sid,
                "title": next((s["title"] for s in SCENARIOS if s["id"] == sid), sid),
                "turns": turns,
            }
            for sid, turns in AGENT_FLOWS.items()
        ],
    }


@router.get("/studio/voices")
async def studio_voices():
    return {
        "ok": True,
        "voices": [
            {
                "id": "jaya",
                "label": "Jaya",
                "tagline": "Warm & friendly",
                "lang": "ta",
                "style": "Jaya speaks in a clear, calm, moderate-pitched voice at a moderate pace. The recording is of very high quality with no background noise.",
            },
            {
                "id": "kavitha",
                "label": "Kavitha",
                "tagline": "Lively & bright",
                "lang": "ta",
                "style": "Kavitha's voice is clear and slightly expressive, with a moderate pitch and pace. The recording is very high quality with no background noise.",
            },
            {
                "id": "divya",
                "label": "Divya",
                "tagline": "Clear English",
                "lang": "en",
                "style": "Divya's voice is monotone yet slightly fast in delivery, with a very close recording that almost has no background noise.",
            },
            {
                "id": "rohit",
                "label": "Rohit",
                "tagline": "Clear male English",
                "lang": "en",
                "style": "Rohit speaks in a clear male voice at a moderate pace and pitch. The recording is of very high quality with no background noise.",
            },
        ],
        "speeds": [0.5, 1.0, 2.0],
        "default_voice": "jaya",
        "default_speed": 1.0,
        "backend": "edge_fast",
    }


@router.get("/studio/comparisons")
async def list_comparisons():
    if not COMPARISONS_PATH.exists():
        return {"ok": True, "items": [], "count": 0}
    items = []
    for line in COMPARISONS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    items.reverse()
    return {"ok": True, "items": items[:50], "count": len(items)}


@router.post("/studio/comparisons")
async def save_comparison(body: ComparisonSave):
    from datetime import datetime, timezone

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "text": body.text,
        "lang": body.lang,
        "side_a": body.side_a,
        "side_b": body.side_b,
        "winner": body.winner,
    }
    with COMPARISONS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {"ok": True, "item": entry}
