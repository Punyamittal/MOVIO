"""
Language translator for the taxi TTS pipeline.

Sits BETWEEN input and TTS:
  raw text → detect → translate(target) → deterministic normalizer → … → TTS

Targets:
  - tanglish  spoken Chennai code-mix, Latin script (default)
  - en        Indian English
  - ta        Tamil script
  - auto      keep detected language (normalize only)

English → Tanglish lives in normalization/tanglish_translator.py: a stateless,
strict-prompt model call with semantic validation and bounded retries. This
module only routes to it and keeps the other language directions.

Tanglish engines, in order:
  1. gold — exact English→natural Tanglish pair (instant, human-verified)
  2. ollama — stateless strict translation, validated, retried if it drifts
  3. offline lexicon — only when its rewrite passes the same validation
  4. fallback-source — speak the English rather than a hallucination
"""
from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    DEFAULT_TARGET_LANG,
    OLLAMA_CHAT_URL,
    OLLAMA_GENERATE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT_SEC,
    PRESERVE_ENGLISH_LIST_PATH,
    TANGLISH_OLLAMA_ONLY_WHEN_NEEDED,
    TRANSLATOR_ENABLED,
    TRANSLATOR_OLLAMA_ENABLED,
)
from normalization.pronunciation_rules import strip_tamil_script  # noqa: E402
from normalization.tanglish_style_normalizer import polish_tanglish_output  # noqa: E402
from normalization.tanglish_rewrite import looks_tanglish, rewrite_en_to_tanglish  # noqa: E402
from normalization.tanglish_translator import (  # noqa: E402
    exact_gold,
    translate_to_tanglish,
)
from normalization.tanglish_audit import audit_non_ollama_translation  # noqa: E402
from normalization.translation_validator import validate_translation  # noqa: E402

logger = logging.getLogger("normalization.translator")

_TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_TANGLISH_MARKERS = (
    " la ",
    " ah ",
    " nu ",
    "pannu",
    "irukku",
    "unga",
    "naan",
    "vandhu",
    "varum",
    "aagum",
)


def _num_word(tok: str) -> str:
    t = (tok or "").strip().lower()
    words = {
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
    return words.get(t, tok)


# Offline taxi-domain EN → Tanglish (phrase rules; longer patterns first)
_OFFLINE_EN_TANGLISH = [
    (
        re.compile(
            r"\b(?:please )?ask (?:him|her|the driver) to wait(?: there)?\b",
            re.I,
        ),
        "avarait ange wait panna sollunga",
    ),
    (
        re.compile(
            r"\b(?:the )?driver told me (?:that )?(?:he|she) would arrive in about (\d+|five|ten|two|three) minutes?\b",
            re.I,
        ),
        lambda m: f"driver {_num_word(m.group(1))} minutes la varuvaaru nu sonnaaru",
    ),
    (
        re.compile(
            r"\b(?:the )?driver (?:will |has )?(?:arrive|arrived|is arriving) in about (\d+|five|ten|two|three) minutes?\b",
            re.I,
        ),
        lambda m: f"driver {_num_word(m.group(1))} minutes la vandhuruvaanga",
    ),
    (re.compile(r"\byour driver (?:will |has )?(?:arrive|arrived|is arriving)\b", re.I), "unga driver vandhuruvaanga"),
    (re.compile(r"\bdriver (?:will |has )?(?:arrive|arrived)\b", re.I), "driver vandhuruvaanga"),
    (re.compile(r"\bin about (\d+|five|ten|two|three) minutes?\b", re.I), lambda m: f"{_num_word(m.group(1))} minutes la"),
    (re.compile(r"\bin (\d+) minutes?\b", re.I), r"\1 minutes la"),
    (re.compile(r"\babout (\d+|five|ten) minutes?\b", re.I), lambda m: f"{_num_word(m.group(1))} minutes"),
    (re.compile(r"\bI am standing outside\b", re.I), "naan veliya nikkiren"),
    (re.compile(r"\bI'?m standing outside\b", re.I), "naan veliya nikkiren"),
    (re.compile(r"\bI am standing\b", re.I), "naan nikkiren"),
    (re.compile(r"\bI'?m standing\b", re.I), "naan nikkiren"),
    (
        re.compile(
            r"\b(?:the )?main entrance of the building near the security gate\b",
            re.I,
        ),
        "building main entrance / security gate near-la",
    ),
    (re.compile(r"\boutside the main entrance\b", re.I), "main entrance veliya"),
    (re.compile(r"\bmain entrance of the building\b", re.I), "building-oda main entrance"),
    (re.compile(r"\bof the building\b", re.I), "building"),
    (re.compile(r"\bnear the security gate\b", re.I), "security gate near-la"),
    (re.compile(r"\bthe building-oda main entrance\b", re.I), "building-oda main entrance"),
    (re.compile(r"\bthe building main entrance\b", re.I), "building main entrance"),
    (re.compile(r"\bsecurity gate\b", re.I), "security gate"),
    (re.compile(r"\bI have two suitcases\b", re.I), "enakku rendu suitcase irukku"),
    (re.compile(r"\btwo suitcases\b", re.I), "rendu suitcase"),
    (re.compile(r"\bone laptop bag\b", re.I), "oru laptop bag"),
    (re.compile(r"\ban? important document\b", re.I), "important document"),
    (
        re.compile(
            r"\bI do not want to walk all the way to the parking area\b",
            re.I,
        ),
        "parking area varaikum walk panna vendaam",
    ),
    (
        re.compile(r"\bdon'?t want to walk all the way to the parking(?: area)?\b", re.I),
        "parking varaikum walk panna vendaam",
    ),
    (re.compile(r"\bparking area\b", re.I), "parking"),
    (re.compile(r"\bplease wait(?: there)?\b", re.I), "ange wait pannunga"),
    (re.compile(r"\bplease share (?:your )?otp\b", re.I), "OTP share pannunga"),
    (re.compile(r"\bshare (?:your )?otp\b", re.I), "OTP share pannunga"),
    (re.compile(r"\bbooking (?:is )?confirmed\b", re.I), "booking confirm aagiruchu"),
    (re.compile(r"\bheavy traffic\b", re.I), "traffic heavy ah irukku"),
    (re.compile(r"\btraffic is heavy\b", re.I), "traffic heavy ah irukku"),
    (re.compile(r"\bcab is (?:on the way|coming)\b", re.I), "cab varuthu"),
    (re.compile(r"\bthank you\b", re.I), "thanks"),
    (re.compile(r"\bwith me\b", re.I), "ennoda irukku"),
    (re.compile(r"\bbecause\b", re.I), "so"),
]

# Offline Tanglish → English (longer phrases first)
_OFFLINE_TANGLISH_EN = [
    (
        re.compile(
            r"\bunga\s+driver\s+(\d+)\s*minutes?\s+la\s+vandhuruvaanga\.?\s*"
            r"(?:otp\s+(\d+)\s+)?share\s+pannunga\b",
            re.I,
        ),
        lambda m: (
            f"your driver will arrive in {m.group(1)} minutes. "
            f"please share the OTP{(' ' + m.group(2)) if m.group(2) else ''}"
        ).rstrip(),
    ),
    (
        re.compile(
            r"\bunga\s+driver\s+(\d+)\s*minutes?\s+la\s+vandhuruvaanga\b",
            re.I,
        ),
        r"your driver will arrive in \1 minutes",
    ),
    (
        re.compile(r"\bunga\s+driver\s+vandhuruvaanga\b", re.I),
        "your driver will arrive",
    ),
    (
        re.compile(r"\b(\d+)\s*minutes?\s+la\s+vandhuruvaanga\b", re.I),
        r"will arrive in \1 minutes",
    ),
    (
        re.compile(r"\b(\d+)\s*minutes?\s+la\b", re.I),
        r"in \1 minutes",
    ),
    (
        re.compile(r"\botp\s+(\d+)\s+share\s+pannunga\b", re.I),
        r"please share the OTP \1",
    ),
    (re.compile(r"\botp\s+share\s+pannunga\b", re.I), "please share the OTP"),
    (re.compile(r"\bshare\s+pannunga\b", re.I), "please share"),
    (re.compile(r"\bunga\s+driver\b", re.I), "your driver"),
    (re.compile(r"\bvandhuruvaanga\b", re.I), "will arrive"),
    (re.compile(r"\bvaruthu\b", re.I), "is coming"),
    (re.compile(r"\bvarum\b", re.I), "will come"),
    (re.compile(r"\btraffic\s+heavy\s+ah\s+irukku\b", re.I), "traffic is heavy"),
    (re.compile(r"\bheavy\s+ah\s+irukku\b", re.I), "is heavy"),
    (re.compile(r"\bconfirm\s+aagiruchu\b", re.I), "is confirmed"),
    (re.compile(r"\bbook\s+pannunga\b", re.I), "please book"),
    (re.compile(r"\bcancel\s+pannunga\b", re.I), "please cancel"),
    (re.compile(r"\bdrop\s+pannunga\b", re.I), "please drop"),
    (re.compile(r"\bpannunga\b", re.I), "please"),
    (re.compile(r"\birukku\b", re.I), "is there"),
    (re.compile(r"\baagum\b", re.I), "will happen"),
    (re.compile(r"\s+\bla\b", re.I), ""),
    (re.compile(r"\s+\bah\b", re.I), ""),
]

_OFFLINE_EN_TA = [
    (re.compile(r"\byour driver\b", re.I), "உங்க driver"),
    (re.compile(r"\bminutes?\b", re.I), "நிமிடம்"),
    (re.compile(r"\bplease share\b", re.I), "பகிருங்க"),
    (re.compile(r"\bthank you\b", re.I), "நன்றி"),
]

_BAD_MT_MARKERS = (
    "error 500",
    "server error",
    "that's an error",
    "there was an error",
    "please try again later",
    "that's all we know",
    "<html",
    "<!doctype",
    "our systems have detected",
    "unusual traffic",
    "captcha",
)


@dataclass
class TranslateResult:
    text: str
    detected_lang: str
    target_lang: str
    engine: str
    skipped: bool = False
    audit: dict | None = None


def load_preserve_list(path: Path = PRESERVE_ENGLISH_LIST_PATH) -> list[str]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return sorted(
        (str(x).strip() for x in data if str(x).strip()),
        key=len,
        reverse=True,
    )


def detect_language(text: str) -> str:
    t = text or ""
    has_ta = bool(_TAMIL_RE.search(t))
    has_latin = bool(_LATIN_RE.search(t))
    lower = f" {t.lower()} "
    if any(m in lower for m in _TANGLISH_MARKERS) or (has_ta and has_latin):
        return "tanglish"
    if has_ta and not has_latin:
        return "ta"
    if has_latin and not has_ta:
        return "en"
    if has_ta:
        return "ta"
    if has_latin:
        return "en"
    return "unknown"


def _is_bad_mt_output(text: str, source: str) -> bool:
    """Reject Google/HTML error pages and empty garbage."""
    t = (text or "").strip()
    if not t:
        return True
    lower = t.lower()
    if any(m in lower for m in _BAD_MT_MARKERS):
        return True
    # Gross length blow-up vs source usually means an error page
    if len(t) > max(80, len(source) * 4) and ("error" in lower or "http" in lower):
        return True
    return False


def _protect_loanwords(text: str, preserve: list[str]) -> tuple[str, dict[str, str]]:
    mapping: dict[str, str] = {}
    out = text
    for i, term in enumerate(preserve):
        if not term:
            continue
        pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)

        def _sub(m: re.Match, idx: int = i) -> str:
            key = f"ZXLOAN{idx}ZX"
            mapping[key] = m.group(0)
            return key

        out = pattern.sub(_sub, out)
    return out, mapping


def _restore_loanwords(text: str, mapping: dict[str, str]) -> str:
    out = text
    for key, val in mapping.items():
        out = out.replace(key, val)
        out = out.replace(key.lower(), val)
    return out


def _google_translate(text: str, source: str, target: str) -> str:
    """Google MT with timeout; raises if response looks like an error page."""
    import concurrent.futures

    from deep_translator import GoogleTranslator

    src = source if source in ("en", "ta") else "auto"
    tgt = "ta" if target in ("ta", "tanglish") else "en"
    if src == tgt and src != "auto":
        return text

    def _call() -> str:
        return (GoogleTranslator(source=src, target=tgt).translate(text) or "").strip()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_call)
        out = fut.result(timeout=8.0)

    if _is_bad_mt_output(out, text):
        raise RuntimeError(f"google returned error page: {out[:80]!r}")
    return out


def _ollama_translate(text: str, target: str) -> str:
    """Fast generate-API call against the small OLLAMA_MODEL.

    Tanglish is NOT handled here — see normalization/tanglish_translator.py.
    The prompt this function used to carry for Tanglish listed Tamil pronouns
    and taxi loanwords inline, and small models answered by reciting that
    list, which is what produced the hallucinated output.
    """
    if target == "ta":
        prompt = (
            "Translate to Tamil script for speech. Keep OTP/driver/cab in Latin if present. "
            f"Return ONLY the translation.\n\n{text}\n\nTamil:"
        )
    else:
        prompt = (
            "Translate to clear Indian English for a taxi agent. "
            f"Return ONLY the English.\n\n{text}\n\nEnglish:"
        )

    timeout = min(float(OLLAMA_TIMEOUT_SEC), 45.0)
    approx_tokens = max(80, min(220, len(text.split()) * 2 + 40))
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "num_predict": approx_tokens,
            "temperature": 0.15,
            "top_p": 0.9,
        },
    }
    try:
        resp = requests.post(OLLAMA_GENERATE_URL, json=payload, timeout=timeout)
        resp.raise_for_status()
        body = resp.json()
        out = (body.get("response") or "").strip().strip('"').strip("'")
        # Drop accidental "Tanglish:" prefix / markdown fences
        out = re.sub(r"^(tanglish|tamil|english)\s*:\s*", "", out, flags=re.I)
        out = re.sub(r"^```\w*\n?|\n?```$", "", out).strip()
        if out and not _is_bad_mt_output(out, text):
            return out
        raise RuntimeError("empty or bad ollama output")
    except Exception as exc:  # noqa: BLE001
        # Fallback to chat API once
        try:
            chat_payload = {
                "model": OLLAMA_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"num_predict": approx_tokens, "temperature": 0.15},
            }
            resp = requests.post(OLLAMA_CHAT_URL, json=chat_payload, timeout=timeout)
            resp.raise_for_status()
            msg = (resp.json().get("message") or {}).get("content") or ""
            out = msg.strip().strip('"').strip("'")
            if out and not _is_bad_mt_output(out, text):
                return out
        except Exception:
            pass
        raise RuntimeError(f"ollama translate failed: {exc}") from exc


def _offline_rewrite(text: str, target: str) -> str:
    if target == "tanglish":
        return polish_tanglish_output(rewrite_en_to_tanglish(text), source=text)
    out = text
    if target == "en":
        rules = _OFFLINE_TANGLISH_EN
    elif target == "ta":
        rules = _OFFLINE_EN_TA
    else:
        return text
    for pattern, repl in rules:
        out = pattern.sub(repl, out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    out = re.sub(r"\s+([.,!?])", r"\1", out)
    return out


def _mostly_tamil_script(text: str) -> bool:
    """True when Tamil script dominates (real ta MT), not a few swapped tokens."""
    letters = re.findall(r"[\u0B80-\u0BFFa-zA-Z]", text or "")
    if not letters:
        return False
    ta = sum(1 for c in letters if "\u0B80" <= c <= "\u0BFF")
    return ta / len(letters) >= 0.45


def _offline_complete_enough(source: str, offline: str) -> bool:
    """True when the offline rewrite is a full Tanglish sentence we can speak.

    Used as a fast path before Ollama so a cold/evicted GPU does not leave the
    caller waiting through stacked timeouts. Rejects shredded word-swap output.
    """
    off = (offline or "").strip()
    src = (source or "").strip()
    if not off or off.lower() == src.lower():
        return False
    if _mostly_tamil_script(off):
        return False
    if not looks_tanglish(off):
        return False
    src_n = len(src.split())
    off_n = len(off.split())
    # Template rewrites preserve length; word-by-word shredding collapses it
    # or leaves bare English leftovers.
    if off_n < max(4, int(0.55 * src_n)):
        return False
    leftovers = re.findall(
        r"\b(the|is|are|of|to|for|with|and|please|because|has|have|will|"
        r"standing|stopped|ask|come|turn|around|near|outside|inside)\b",
        off,
        re.I,
    )
    if len(leftovers) >= 2:
        return False
    report = validate_translation(src, off)
    hard = " ".join(report.hard_flags)
    for bad in (
        "concept_added:otp",
        "concept_added:parking",
        "concept_added:cab",
        "number_invented",
        "number_missing",
        "time_invented",
        "time_missing",
        "name_invented",
        "repeated_token",
        "empty_output",
        "meaning_loss",
    ):
        if bad in hard:
            return False
    return True


def to_tanglish(text: str, detected: str, preserve: list[str] | None = None) -> tuple[str, str]:
    """English → spoken Chennai Tanglish (Latin script).

    Latency-first order (target: preprocess << 100ms on known lines):
      1. exact gold pair — instant
      2. complete offline template — instant (when OLLAMA_ONLY_WHEN_NEEDED)
      3. Ollama for novel / incomplete leftovers
    """
    _ = preserve if preserve is not None else load_preserve_list()
    if detected == "tanglish":
        return text, "passthrough"

    # 1) Exact gold — never touches the GPU.
    gold = exact_gold(text)
    if gold:
        return gold, "gold"

    offline = rewrite_en_to_tanglish(text)
    offline_ok = _offline_complete_enough(text, offline)

    # 2) Complete offline rewrite — GPU-free (default for low TTFA).
    if TANGLISH_OLLAMA_ONLY_WHEN_NEEDED and offline_ok:
        return offline, "offline-lexicon"

    # 3) Ollama for leftovers / novel phrasing / quality-first mode.
    if TRANSLATOR_OLLAMA_ENABLED:
        result = translate_to_tanglish(text)
        if result.text and result.engine not in ("fallback-source", "fallback-unavailable"):
            return result.text, result.engine
        logger.info(
            "Tanglish translator returned %s (flags=%s)", result.engine, ",".join(result.flags)
        )

    if offline_ok:
        return offline, "offline-lexicon-fallback"

    if offline.strip() and offline.strip().lower() != text.strip().lower():
        # Judge what will actually be spoken. Tamil glyphs are stripped further
        # down the pipeline, so a Latin+Tamil rewrite that looks like Tanglish
        # here can reach the TTS engine as bare English.
        spoken = strip_tamil_script(offline).strip()
        if (
            spoken
            and looks_tanglish(spoken)
            and not _mostly_tamil_script(offline)
            and len(spoken.split()) >= max(4, int(0.4 * len(text.split())))
        ):
            weak_hard = " ".join(validate_translation(text, spoken).hard_flags)
            if not any(
                bad in weak_hard
                for bad in (
                    "not_translated",
                    "tamil_script",
                    "number_invented",
                    "meaning_loss",
                    "malformed",
                )
            ):
                return spoken, "offline-lexicon-weak"
        if validate_translation(text, offline).ok:
            return offline, "offline-lexicon"

    return text, "fallback-source"


def to_english(text: str, detected: str) -> tuple[str, str]:
    """Tanglish/Tamil → English with offline-first engines."""
    offline = _offline_rewrite(text, "en")
    if offline.strip().lower() != text.strip().lower():
        return offline, "offline-lexicon"

    if TRANSLATOR_OLLAMA_ENABLED:
        try:
            return _ollama_translate(text, "en"), "ollama"
        except Exception as exc:  # noqa: BLE001
            logger.info("Ollama EN unavailable: %s", exc)

    try:
        return _google_translate(text, "auto", "en"), "google"
    except Exception as exc:  # noqa: BLE001
        logger.info("Google EN unavailable: %s", exc)

    return text, "passthrough-fallback"


def translate(
    text: str,
    target_lang: str | None = None,
    enabled: bool | None = None,
) -> TranslateResult:
    raw = (text or "").strip()
    target = (target_lang or DEFAULT_TARGET_LANG or "tanglish").lower().strip()
    if target in ("tamil", "ta-in"):
        target = "ta"
    if target in ("english", "en-in"):
        target = "en"
    if target in ("auto", "none", "off"):
        target = "auto"

    use = TRANSLATOR_ENABLED if enabled is None else enabled
    detected = detect_language(raw)

    if not raw or not use or target == "auto":
        return TranslateResult(raw, detected, target, "skip", skipped=True)

    if target == detected or (target == "tanglish" and detected == "tanglish"):
        return TranslateResult(raw, detected, target, "passthrough", skipped=True)

    try:
        if target == "en":
            if detected in ("ta", "tanglish"):
                out, engine = to_english(raw, detected)
                if _is_bad_mt_output(out, raw):
                    return TranslateResult(raw, detected, target, "blocked-fallback", skipped=True)
                return TranslateResult(out, detected, target, engine)
            return TranslateResult(raw, detected, target, "passthrough", skipped=True)

        if target == "ta":
            if detected in ("en", "tanglish", "unknown"):
                offline = _offline_rewrite(raw, "ta")
                # Tiny lexicon only swaps a few words — reject mostly-English leftovers.
                if _mostly_tamil_script(offline):
                    return TranslateResult(offline, detected, target, "offline-lexicon")
                if TRANSLATOR_OLLAMA_ENABLED:
                    try:
                        out = _ollama_translate(raw, "ta")
                        if out and not _is_bad_mt_output(out, raw):
                            return TranslateResult(out, detected, target, "ollama")
                    except Exception as exc:  # noqa: BLE001
                        logger.info("Ollama TA unavailable: %s", exc)
                    preserve = load_preserve_list()
                    protected, mapping = _protect_loanwords(raw, preserve)
                    try:
                        out = _google_translate(protected, "auto", "ta")
                        out = _restore_loanwords(out, mapping)
                        if out and not _is_bad_mt_output(out, raw):
                            return TranslateResult(out, detected, target, "google+preserve")
                    except Exception as exc:  # noqa: BLE001
                        logger.info("Google TA unavailable: %s", exc)
                if offline.strip().lower() != raw.strip().lower():
                    return TranslateResult(offline, detected, target, "offline-lexicon-weak")
                return TranslateResult(raw, detected, target, "passthrough-fallback", skipped=True)
            return TranslateResult(raw, detected, target, "passthrough", skipped=True)

        if target == "tanglish":
            out, engine = to_tanglish(raw, detected)
            if _is_bad_mt_output(out, raw):
                return TranslateResult(raw, detected, target, "blocked-fallback", skipped=True)
            audit = audit_non_ollama_translation(raw, out, engine)
            return TranslateResult(
                out,
                detected,
                target,
                engine,
                audit=audit.to_dict() if audit else None,
            )

    except Exception as exc:  # noqa: BLE001
        logger.warning("Translator failed (%s) — using original text", exc)
        return TranslateResult(raw, detected, target, "error-fallback", skipped=True)

    return TranslateResult(raw, detected, target, "passthrough", skipped=True)


if __name__ == "__main__":
    samples = [
        ("Your driver will arrive in 5 minutes. Share OTP 4821.", "tanglish"),
        ("Unga driver 5 minutes la vandhuruvaanga. OTP share pannunga.", "en"),
    ]
    for s, tgt in samples:
        r = translate(s, tgt)
        print(f"[{r.detected_lang}→{r.target_lang}|{r.engine}] {s!r}")
        print(f"  => {r.text!r}\n")
