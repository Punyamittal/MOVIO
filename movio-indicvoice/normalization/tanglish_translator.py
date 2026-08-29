"""
Stateless English → Tanglish translation.

    Current English utterance
            ↓
      translation prompt          (built from this utterance only)
            ↓
          model
            ↓
    gold-style polish            (tanglish_style_normalizer — calques, time words)
            ↓
       validation                 (translation_validator)
            ↓  fail
       stricter retry             (bounded, still from the ORIGINAL source)
            ↓
    one Tanglish translation

Statelessness is the point. Every call builds a brand-new message list from
the current sentence. No conversation history, no previous source, and above
all no previous *output* is ever sent back to the model — a bad translation
can therefore never contaminate the next utterance.

The only context injected is a handful of gold English/Tanglish pairs
retrieved by similarity to the current sentence. That is derived purely from
the current input, is deterministic, and is what teaches a 3B model real
Chennai Tanglish instead of guessed Tamil.

Why the old prompt hallucinated: it listed Tamil pronouns and taxi loanwords
inline ("keep OTP, cab, parking, Guindy in Latin script"), and a small model
simply emitted that vocabulary list as its answer. Rules here never enumerate
target-language content words.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    OLLAMA_CHAT_URL,
    OLLAMA_GENERATE_URL,
    TANGLISH_CACHE_ENABLED,
    TANGLISH_CACHE_SIZE,
    TANGLISH_DEBUG,
    TANGLISH_FEWSHOT_K,
    TANGLISH_GOLD_PAIRS_PATH,
    TANGLISH_KEEP_ALIVE,
    TANGLISH_MAX_RETRIES,
    TANGLISH_MODEL,
    TANGLISH_NUM_CTX,
    TANGLISH_REPEAT_PENALTY,
    TANGLISH_SEED,
    TANGLISH_TEMPERATURE,
    TANGLISH_TIMEOUT_SEC,
    TANGLISH_TOP_K,
    TANGLISH_TOP_P,
    TRANSLATION_DEBUG_LOG,
)
from normalization.tanglish_normalize_spec import NATURAL_SPOKEN_GUIDELINES  # noqa: E402
from normalization.tanglish_style_normalizer import polish_tanglish_output  # noqa: E402
from normalization.tanglish_audit import audit_non_ollama_translation  # noqa: E402
from normalization.translation_validator import (  # noqa: E402
    TranslationReport,
    malformed_blocks_fallback,
    score as translation_score,
    validate_translation,
)
from normalization.tanglish_rewrite import looks_tanglish  # noqa: E402

logger = logging.getLogger("normalization.tanglish_translator")

# Bump when the prompt changes so cached translations are not reused across
# prompt versions.
PROMPT_VERSION = "v3-natural-spoken"

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are an English-to-Tanglish translator for a Chennai taxi phone call.\n"
    "Tanglish is spoken Chennai Tamil written in Latin script, keeping the "
    "everyday English words a Chennai speaker would say in English.\n"
    "\n"
    "Translate ONLY the sentence you are given.\n"
    "\n"
    "Do not add information.\n"
    "Do not remove information.\n"
    "Do not invent words, events, objects, locations, numbers, OTPs, times, "
    "people, or actions.\n"
    "Do not continue the conversation and do not answer the sentence.\n"
    "\n"
    "Return exactly ONE translation on a single line.\n"
    "Do not provide explanations.\n"
    "Do not provide alternatives.\n"
    "Do not repeat the English text.\n"
    "Do not add labels or quotation marks.\n"
    "\n"
    "Preserve exactly as written: names, numbers, OTPs, locations, times, "
    "quantities, directions and other entities.\n"
    "\n"
    "Use natural spoken Chennai Tanglish, not literary Tamil and not Tamil "
    "script.\n"
    "\n"
    + NATURAL_SPOKEN_GUIDELINES
)

FEWSHOT_NOTE = (
    "The next few exchanges are style examples. Copy their tone and sentence "
    "shape only — never copy their words, places, numbers or subject matter "
    "into a later answer."
)

RETRY_PROMPT = (
    "Your previous output introduced information that was not present in the "
    "source sentence, or sounded like stiff translated Tamil instead of "
    "natural spoken Chennai Tanglish.\n"
    "\n"
    "Translate ONLY the source sentence.\n"
    "\n"
    "Do not add any new information.\n"
    "Do not mention anything the source does not mention.\n"
    "Use natural modern spoken Tanglish: sila seconds (not konjam seconds), "
    "-la vittuten for left-behind objects, dhaana-nu confirm/check for "
    "verification, innum X nimisham-ku mela for time increases.\n"
    "Return one line of spoken Chennai Tanglish and nothing else.\n"
    "\n"
    "Source:\n"
    "{source}"
)

# ---------------------------------------------------------------------------
# Gold translation memory (retrieval source for few-shot)
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset(
    {
        "the", "a", "an", "is", "are", "am", "to", "of", "and", "but", "so",
        "in", "on", "at", "i", "me", "my", "he", "she", "it", "that", "this",
        "please", "for", "with", "will", "has", "have", "be", "you", "your",
        "him", "her", "they", "them", "we", "us", "there", "here", "was",
        "were", "been", "do", "does", "did", "can", "could", "would", "should",
    }
)

_GOLD_LOCK = threading.Lock()
_GOLD: list[tuple[str, str, frozenset[str]]] | None = None
_GOLD_MTIME: float | None = None


def _gold_file_mtime() -> float:
    try:
        return TANGLISH_GOLD_PAIRS_PATH.stat().st_mtime
    except OSError:
        return 0.0


def gold_pairs_version() -> str:
    """Fingerprint of tanglish_gold_pairs.json for cache invalidation."""
    try:
        raw = TANGLISH_GOLD_PAIRS_PATH.read_bytes()
    except OSError:
        return "0"
    return hashlib.sha256(raw).hexdigest()[:12]


def _key_tokens(text: str) -> frozenset[str]:
    return frozenset(
        w for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in _STOPWORDS
    )


def _gold_pairs() -> list[tuple[str, str, frozenset[str]]]:
    global _GOLD, _GOLD_MTIME
    mtime = _gold_file_mtime()
    with _GOLD_LOCK:
        if _GOLD is not None and _GOLD_MTIME == mtime:
            return _GOLD
        if _GOLD is not None and _GOLD_MTIME != mtime:
            logger.info("Gold pairs file changed — reloading index")
            _CACHE.clear()
        rows: list[tuple[str, str, frozenset[str]]] = []
        try:
            data = json.loads(TANGLISH_GOLD_PAIRS_PATH.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Gold Tanglish pairs unavailable (%s)", exc)
            data = []
        for row in data:
            en = (row.get("english") or "").strip()
            ta = (row.get("tanglish") or "").strip()
            if en and ta:
                rows.append((en, ta, _key_tokens(en)))
        _GOLD = rows
        _GOLD_MTIME = mtime
        return _GOLD


def _normalize_key(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"[\u201c\u201d\"]", "", t)
    # Expand contractions before stripping apostrophes (don't → do not, not dont).
    for pat, repl in (
        (r"\bdon't\b", "do not"),
        (r"\bcan't\b", "cannot"),
        (r"\bwon't\b", "will not"),
        (r"\bisn't\b", "is not"),
        (r"\baren't\b", "are not"),
        (r"\bwasn't\b", "was not"),
        (r"\bweren't\b", "were not"),
        (r"\bdoesn't\b", "does not"),
        (r"\bdidn't\b", "did not"),
        (r"\bwouldn't\b", "would not"),
        (r"\bshouldn't\b", "should not"),
        (r"\bthere's\b", "there is"),
        (r"\bit's\b", "it is"),
        (r"\bthat's\b", "that is"),
        (r"\bi'm\b", "i am"),
        (r"\bi've\b", "i have"),
        (r"\bi'll\b", "i will"),
        (r"\bwe're\b", "we are"),
        (r"\byou're\b", "you are"),
        (r"\bthey're\b", "they are"),
        (r"\blet's\b", "let us"),
    ):
        t = re.sub(pat, repl, t)
    t = t.replace("'", "")
    t = re.sub(r"\s+", " ", t)
    return re.sub(r"[.!?]+$", "", t).strip()


def exact_gold(text: str) -> str | None:
    key = _normalize_key(text)
    for en, ta, _ in _gold_pairs():
        if _normalize_key(en) == key:
            return ta
    return None


def retrieve_examples(text: str, k: int = TANGLISH_FEWSHOT_K) -> list[tuple[str, str]]:
    """k gold pairs most similar to THIS sentence.

    Deterministic (Jaccard, ties broken by example length then text), so the
    same input always produces the same prompt.
    """
    if k <= 0:
        return []
    q = _key_tokens(text)
    if not q:
        return []
    scored: list[tuple[float, int, str, str]] = []
    for en, ta, g in _gold_pairs():
        if not g:
            continue
        sim = len(q & g) / len(q | g)
        if sim <= 0.0:
            continue
        scored.append((sim, -len(en), en, ta))
    scored.sort(key=lambda r: (-r[0], -r[1], r[2]))
    # Most similar example goes last — closest to the real question.
    return [(en, ta) for _, _, en, ta in scored[:k]][::-1]


# ---------------------------------------------------------------------------
# Ollama call (stateless)
# ---------------------------------------------------------------------------


def build_messages(
    source: str,
    *,
    examples: list[tuple[str, str]] | None = None,
    retry_reason: str = "",
) -> list[dict[str, str]]:
    """Build a complete, self-contained message list for ONE utterance.

    Nothing here depends on any previous call.
    """
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if examples:
        messages.append({"role": "system", "content": FEWSHOT_NOTE})
        for src, tgt in examples:
            messages.append({"role": "user", "content": src})
            messages.append({"role": "assistant", "content": tgt})
    if retry_reason:
        # The failure is described, never the failed text itself.
        messages.append(
            {
                "role": "system",
                "content": f"A previous attempt was rejected because {retry_reason}.",
            }
        )
        messages.append({"role": "user", "content": RETRY_PROMPT.format(source=source)})
    else:
        messages.append({"role": "user", "content": source})
    return messages


_STRIP_LABEL_RE = re.compile(r"^\s*(tanglish|tamil|english|translation|output)\s*[:\-]\s*", re.I)
_FENCE_RE = re.compile(r"^```[\w]*\s*|\s*```$")


def clean_model_output(raw: str) -> str:
    """Normalize model text into one Tanglish sentence.

    Join soft-wrapped continuation lines (models sometimes break a long
    translation across newlines). Still drop second alternatives / lists.
    """
    out = (raw or "").strip()
    out = _FENCE_RE.sub("", out).strip()
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not lines:
        return ""
    # Keep consecutive continuation lines until a numbered/bulleted alternative.
    kept = [lines[0]]
    for line in lines[1:]:
        if re.match(r"^(\d+[.)]|[-*\u2022])\s+", line):
            break
        if re.match(r"^(tanglish|tamil|english|translation|output|alternative)\s*[:\-]", line, re.I):
            break
        kept.append(line)
    out = " ".join(kept)
    out = _STRIP_LABEL_RE.sub("", out).strip()
    out = re.sub(r"^\s*[-*\u2022]\s*", "", out)
    out = re.sub(r"^\s*\d+[.)]\s*", "", out)
    if len(out) >= 2 and out[0] in "\"'\u201c" and out[-1] in "\"'\u201d":
        out = out[1:-1].strip()
    return re.sub(r"\s{2,}", " ", out).strip()


def _num_predict(source: str) -> int:
    # Long multi-clause passenger lines need headroom; truncating mid-sentence
    # is what users hear as "incomplete Tanglish".
    words = max(1, len((source or "").split()))
    return max(128, min(384, words * 4 + 64))


def call_model(
    messages: list[dict[str, str]],
    *,
    model: str,
    source: str,
    temperature: float,
    timeout: float,
) -> tuple[str, float]:
    """One stateless /api/chat call. Returns (cleaned_text, latency_ms)."""
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        # Qwen-style reasoning models: translation needs no chain of thought.
        "think": False,
        "keep_alive": TANGLISH_KEEP_ALIVE,
        "options": {
            "temperature": temperature,
            "top_p": TANGLISH_TOP_P,
            "top_k": TANGLISH_TOP_K,
            "repeat_penalty": TANGLISH_REPEAT_PENALTY,
            "seed": TANGLISH_SEED,
            "num_predict": _num_predict(source),
            "num_ctx": TANGLISH_NUM_CTX,
        },
    }
    t0 = time.perf_counter()
    resp = requests.post(OLLAMA_CHAT_URL, json=payload, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    raw = (body.get("message") or {}).get("content") or body.get("response") or ""
    # Surface truncation so callers can retry with a larger budget once.
    done = body.get("done_reason") or (body.get("message") or {}).get("done_reason")
    out = clean_model_output(raw)
    if done == "length" or (out and not out[-1] in ".!?…" and len(out.split()) < len(source.split()) * 0.6):
        # Soft signal only — validator decides whether to retry.
        logger.debug("Tanglish generation may be truncated done_reason=%s", done)
    return out, (time.perf_counter() - t0) * 1000


# ---------------------------------------------------------------------------
# Cache — identical input, identical output, no repeat model call
# ---------------------------------------------------------------------------


class _TranslationCache:
    def __init__(self, maxsize: int) -> None:
        self._maxsize = maxsize
        self._data: OrderedDict[tuple[str, str, str], str] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str, str]) -> str | None:
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def put(self, key: tuple[str, str, str], value: str) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_CACHE = _TranslationCache(TANGLISH_CACHE_SIZE)


def clear_cache() -> None:
    _CACHE.clear()


def reload_gold() -> None:
    """Drop the in-memory gold index so newly added pairs are picked up."""
    global _GOLD, _GOLD_MTIME
    with _GOLD_LOCK:
        _GOLD = None
        _GOLD_MTIME = None
    clear_cache()


# ---------------------------------------------------------------------------
# Public result
# ---------------------------------------------------------------------------


def warmup(model: str | None = None, timeout: float | None = None) -> bool:
    """Load the translation model into VRAM ahead of the first utterance.

    Loading costs tens of seconds on a small laptop GPU while inference costs
    a couple of seconds, so a cold first call would blow the latency budget
    of a live call. Safe to call at server start; failures are non-fatal.
    """
    model = model or TANGLISH_MODEL
    try:
        # Empty generate with keep_alive pins the weights. Some Ollama builds
        # 400 on a prompt-less generate — fall back to a tiny chat ping.
        # CRITICAL: use the same num_ctx as live translation. Changing ctx
        # between warmup and the first request forces a ~7–9s VRAM reload.
        warm_opts = {"num_predict": 1, "num_ctx": TANGLISH_NUM_CTX, "temperature": 0}
        resp = requests.post(
            OLLAMA_GENERATE_URL,
            json={
                "model": model,
                "prompt": "ok",
                "keep_alive": TANGLISH_KEEP_ALIVE,
                "stream": False,
                "options": warm_opts,
            },
            timeout=timeout or max(120.0, TANGLISH_TIMEOUT_SEC),
        )
        if resp.status_code >= 400:
            resp = requests.post(
                OLLAMA_CHAT_URL,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "ok"}],
                    "stream": False,
                    "keep_alive": TANGLISH_KEEP_ALIVE,
                    "options": warm_opts,
                },
                timeout=timeout or max(120.0, TANGLISH_TIMEOUT_SEC),
            )
        resp.raise_for_status()
        logger.info("Tanglish model %s warm (num_ctx=%s)", model, TANGLISH_NUM_CTX)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tanglish warmup failed for %s: %s", model, exc)
        return False


@dataclass
class TanglishTranslation:
    text: str
    source: str
    engine: str
    model: str
    ok: bool
    attempts: int = 0
    latency_ms: float = 0.0
    cached: bool = False
    flags: list[str] = field(default_factory=list)
    candidates: list[str] = field(default_factory=list)

    def debug_block(self) -> str:
        return (
            f"SOURCE:\n{self.source}\n\n"
            f"MODEL:\n{self.model}\n\n"
            f"VALIDATION:\n{'PASS' if self.ok else 'FAIL'}"
            f"{' ' + ','.join(self.flags) if self.flags else ''}\n\n"
            f"RETRY:\n{'YES' if self.attempts > 1 else 'NO'}\n\n"
            f"FINAL:\n{self.text}\n\n"
            f"LATENCY:\n{self.latency_ms:.0f} ms\n\n"
            f"ENGINE:\n{self.engine}\n"
        )


def _log_debug(result: TanglishTranslation) -> None:
    """Full per-request trace. Off by default — it records utterance text."""
    if not TANGLISH_DEBUG:
        if not result.ok:
            # Production-safe: shape of the failure, none of the content.
            logger.warning(
                "Tanglish validation failed engine=%s attempts=%d flags=%s",
                result.engine,
                result.attempts,
                ",".join(result.flags),
            )
        return
    logger.info("Tanglish translation\n%s", result.debug_block())
    try:
        TRANSLATION_DEBUG_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "source": result.source,
            "final": result.text,
            "model": result.model,
            "engine": result.engine,
            "validation": "PASS" if result.ok else "FAIL",
            "retry": result.attempts > 1,
            "attempts": result.attempts,
            "flags": result.flags,
            "latency_ms": round(result.latency_ms, 1),
            "candidates": result.candidates,
        }
        with TRANSLATION_DEBUG_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not write translation debug log: %s", exc)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def translate_to_tanglish(
    text: str,
    *,
    model: str | None = None,
    max_retries: int | None = None,
    fewshot_k: int | None = None,
    temperature: float | None = None,
    use_cache: bool | None = None,
    timeout: float | None = None,
) -> TanglishTranslation:
    """Translate one English utterance into spoken Chennai Tanglish.

    Independent of every other call: the returned text is a function of
    `text` and the configuration alone.
    """
    source = (text or "").strip()
    model = model or TANGLISH_MODEL
    max_retries = TANGLISH_MAX_RETRIES if max_retries is None else max_retries
    fewshot_k = TANGLISH_FEWSHOT_K if fewshot_k is None else fewshot_k
    temperature = TANGLISH_TEMPERATURE if temperature is None else temperature
    timeout = TANGLISH_TIMEOUT_SEC if timeout is None else timeout
    caching = TANGLISH_CACHE_ENABLED if use_cache is None else use_cache

    if not source:
        return TanglishTranslation(
            text="", source="", engine="empty", model=model, ok=True
        )

    started = time.perf_counter()

    # 1) Exact translation-memory hit — instant and human-verified.
    gold = exact_gold(source)
    if gold:
        report = validate_translation(source, gold)
        audit = audit_non_ollama_translation(source, gold, "gold")
        result = TanglishTranslation(
            text=gold,
            source=source,
            engine="gold",
            model=model,
            ok=report.ok and (audit.ok if audit else report.ok),
            attempts=0,
            latency_ms=(time.perf_counter() - started) * 1000,
            flags=report.flags + (audit.mix_flags if audit else []),
        )
        _log_debug(result)
        return result

    cache_key = (model, f"{PROMPT_VERSION}:{gold_pairs_version()}", _normalize_key(source))
    if caching:
        hit = _CACHE.get(cache_key)
        if hit is not None:
            result = TanglishTranslation(
                text=hit,
                source=source,
                engine="cache",
                model=model,
                ok=True,
                attempts=0,
                latency_ms=(time.perf_counter() - started) * 1000,
                cached=True,
            )
            _log_debug(result)
            return result

    examples = retrieve_examples(source, fewshot_k)
    candidates: list[tuple[str, TranslationReport]] = []
    attempts = 0
    reason = ""
    last_error: Exception | None = None

    # 2) First attempt, then bounded stricter retries. Each attempt rebuilds
    #    the prompt from `source` — never from a previous candidate.
    #    Timeouts fail fast: retrying a cold/evicted model just stacks 45s waits.
    for attempt in range(max_retries + 1):
        attempts = attempt + 1
        messages = build_messages(
            source,
            examples=examples,
            retry_reason=reason if attempt > 0 else "",
        )
        try:
            out, _ = call_model(
                messages,
                model=model,
                source=source,
                temperature=temperature if attempt < max_retries else min(0.2, temperature + 0.2),
                timeout=timeout,
            )
            out = polish_tanglish_output(out, source=source)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.info("Tanglish model attempt %d failed: %s", attempts, exc)
            err = str(exc).lower()
            if "timed out" in err or "timeout" in err or "connection" in err:
                break
            continue

        report = validate_translation(source, out)
        candidates.append((out, report))
        if report.ok:
            if caching:
                _CACHE.put(cache_key, out)
            result = TanglishTranslation(
                text=out,
                source=source,
                engine="ollama" if attempt == 0 else f"ollama-retry{attempt}",
                model=model,
                ok=True,
                attempts=attempts,
                latency_ms=(time.perf_counter() - started) * 1000,
                flags=report.soft_flags,
                candidates=[c for c, _ in candidates],
            )
            _log_debug(result)
            return result
        reason = report.reason() or "it did not faithfully translate the source"

    # 3) Every attempt failed validation. Prefer the least-bad candidate, but
    #    only when it did not invent or lose an entity — a fluent sentence
    #    with the wrong OTP is worse than plain English.
    best_text = ""
    best_report: TranslationReport | None = None
    for out, report in sorted(candidates, key=lambda cr: translation_score(source, cr[0])):
        if any(
            f.split(":", 1)[0]
            in (
                "number_invented",
                "number_missing",
                "time_invented",
                "time_missing",
                "code_invented",
                "code_missing",
                "name_invented",
                "empty_output",
            )
            for f in report.hard_flags
        ):
            continue
        if any(malformed_blocks_fallback(f) for f in report.hard_flags):
            continue
        if not looks_tanglish(out):
            continue
        best_text, best_report = out, report
        break

    if not best_text:
        # Last resort: Tanglish that only failed soft register checks beats English.
        for out, report in sorted(
            candidates, key=lambda cr: translation_score(source, cr[0])
        ):
            if not looks_tanglish(out):
                continue
            if any(malformed_blocks_fallback(f) for f in report.hard_flags):
                continue
            if any(f.startswith("not_translated") for f in report.hard_flags):
                continue
            best_text, best_report = out, report
            break

    if best_text:
        result = TanglishTranslation(
            text=best_text,
            source=source,
            engine="ollama-unvalidated",
            model=model,
            ok=False,
            attempts=attempts,
            latency_ms=(time.perf_counter() - started) * 1000,
            flags=best_report.flags if best_report else [],
            candidates=[c for c, _ in candidates],
        )
        _log_debug(result)
        return result

    # 4) Nothing usable. Speaking the English source keeps the meaning intact;
    #    emitting an unvalidated hallucination would not.
    result = TanglishTranslation(
        text=source,
        source=source,
        engine="fallback-source" if not last_error else "fallback-unavailable",
        model=model,
        ok=False,
        attempts=attempts,
        latency_ms=(time.perf_counter() - started) * 1000,
        flags=(candidates[-1][1].flags if candidates else ["model_unavailable"]),
        candidates=[c for c, _ in candidates],
    )
    _log_debug(result)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    samples = [
        "I'm standing near the security gate with a red suitcase, but the driver "
        "has stopped on the opposite side of the road, so please ask him to turn "
        "around and come to the main entrance.",
        "The driver will arrive in five minutes.",
        "Please share the OTP 4821.",
        "I need to reach the airport before 7:30 PM.",
    ]
    for s in samples:
        r = translate_to_tanglish(s)
        print(r.debug_block())
        print("-" * 90)
