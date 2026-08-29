"""
Audit agent for non-Ollama Tanglish outputs (gold, offline lexicon, passthrough).

Ollama paths already run translation_validator + retries. Gold and offline
engines skip the GPU but still need a regression check that:
  1. Meaning was preserved (same validator as Ollama)
  2. Code-mix ratio looks like spoken Tanglish, not passthrough English

Thresholds are calibrated from normalization/tanglish_gold_pairs.json
(median Tamil-token ratio ~0.75, p10 ~0.55).
"""
from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import (  # noqa: E402
    TANGLISH_AUDIT_ENABLED,
    TANGLISH_AUDIT_LOG,
    TANGLISH_MIX_ENGLISH_MAX,
    TANGLISH_MIX_TAMIL_MIN,
)
from normalization.tanglish_vocab import english_vocabulary, gold_vocabulary  # noqa: E402
from normalization.translation_validator import validate_translation  # noqa: E402

logger = logging.getLogger("normalization.tanglish_audit")

_WORD_RE = re.compile(r"[A-Za-z]+")
_TAMIL_STEM_RE = re.compile(
    r"(?:pann|iruk|soll|vand|var|aag|nikk|paak|theriy|mudiy|eduk|venaam|"
    r"konjam|romba|munnadi|pakkathula|kitta|vaang|edung|sollung|nikkung)",
    re.I,
)

_FUNCTION_WORDS = frozenset(
    {
        "a", "an", "the", "and", "or", "but", "so", "if", "to", "for", "of", "in",
        "on", "at", "by", "with", "from", "as", "is", "are", "was", "were", "be",
        "been", "being", "have", "has", "had", "do", "does", "did", "will", "would",
        "can", "could", "should", "may", "might", "i", "you", "he", "she", "it", "we",
        "they", "my", "your", "our", "their", "this", "that", "these", "those",
        "please", "not", "no", "yes", "ok", "okay",
    }
)

# Domain loanwords a Chennai taxi speaker keeps in English (from gold + preserve list).
_ENGLISH_LOANWORDS = frozenset(
    {
        "driver", "cab", "otp", "pickup", "drop", "fare", "gps", "app", "map", "maps",
        "booking", "payment", "cancel", "traffic", "airport", "station", "toll", "eta",
        "upi", "gpay", "cash", "route", "gate", "entrance", "exit", "building", "mall",
        "flight", "ac", "pin", "sms", "id", "km", "meter", "highway", "flyover",
        "signal", "lane", "road", "street", "bridge", "bypass", "petrol", "bunk",
        "gauge", "receipt", "email", "package", "luggage", "suitcase", "shirt",
        "phone", "battery", "headlight", "indicator", "procession", "vip", "underpass",
        "pharmacy", "bus", "stop", "security", "cabin", "apartment", "block", "location",
        "screen", "searching", "match", "trip", "child", "lock", "back", "seat", "plan",
        "delay", "rebook", "shared", "ride", "share", "main", "side", "inner", "outer",
        "service", "ground", "wrong", "left", "right", "minutes", "minute", "hour",
        "school", "zone", "roundabout", "railway", "platform", "office", "hospital",
        "college", "metro", "floor", "parking", "area", "complex", "number", "code",
        "vehicle", "car", "auto", "rickshaw", "uber", "ola", "wifi", "atm", "qr",
        "brother", "uncle", "anna", "sir", "madam", "boss", "bro", "easy", "fast",
        "slow", "extra", "full", "empty", "late", "early", "fixed", "price", "wait",
        "time", "strange", "request", "description", "stretch", "bumpy", "usual",
        "highway", "highways", "streets", "street", "lanes", "lane", "flyover",
    }
)

_TAMIL_SUFFIX_RE = re.compile(
    r"-(?:a|ah|ku|kku|ukku|la|le|oda|dhan|nu|um|in|ai|e)$",
    re.I,
)
_SHORT_READOUT_RE = re.compile(
    r"^\s*(?:otp|pin|booking(?:\s*id)?|phone|fare|id)\b",
    re.I,
)

_OLLAMA_ENGINES = frozenset(
    {
        "ollama",
        "ollama-retry1",
        "ollama-retry2",
        "ollama-retry3",
        "ollama-unvalidated",
        "cache",
    }
)


@dataclass
class CodeMixProfile:
    """Tamil vs English token counts in Latin Tanglish."""

    tamil_tokens: int = 0
    english_tokens: int = 0
    unknown_tokens: int = 0
    function_tokens: int = 0
    content_tokens: int = 0
    tamil_ratio: float = 0.0
    english_ratio: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AuditReport:
    engine: str
    source: str
    output: str
    meaning_ok: bool
    hard_flags: list[str] = field(default_factory=list)
    soft_flags: list[str] = field(default_factory=list)
    mix_flags: list[str] = field(default_factory=list)
    mix: CodeMixProfile = field(default_factory=CodeMixProfile)
    ok: bool = True
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        d = asdict(self)
        d["mix"] = self.mix.to_dict()
        return d


def is_ollama_engine(engine: str) -> bool:
    eng = (engine or "").lower().strip()
    if eng in _OLLAMA_ENGINES:
        return True
    return eng.startswith("ollama")


def classify_token(token: str) -> str:
    """Classify one Latin token: tamil | english | function | other."""
    t = (token or "").lower().strip().strip(".,;:!?")
    if not t or len(t) <= 1:
        return "other"
    if _TAMIL_SUFFIX_RE.search(t):
        return "tamil"
    if t in _FUNCTION_WORDS:
        return "function"
    if t in _ENGLISH_LOANWORDS or t in english_vocabulary():
        return "english"
    if t in gold_vocabulary():
        return "tamil"
    if _TAMIL_STEM_RE.search(t):
        return "tamil"
    return "unknown"


def _is_short_domain_readout(source: str, output: str) -> bool:
    out = (output or "").strip()
    if len(_WORD_RE.findall(out)) > 4:
        return False
    return bool(_SHORT_READOUT_RE.search(out))


def code_mix_profile(text: str) -> CodeMixProfile:
    """Tamil/English word ratio for spoken Latin Tanglish."""
    counts = {"tamil": 0, "english": 0, "unknown": 0, "function": 0, "other": 0}
    for raw in _WORD_RE.findall(text or ""):
        counts[classify_token(raw)] += 1

    content = counts["tamil"] + counts["english"] + counts["unknown"]
    tamil_r = counts["tamil"] / content if content else 0.0
    english_r = counts["english"] / content if content else 0.0
    return CodeMixProfile(
        tamil_tokens=counts["tamil"],
        english_tokens=counts["english"],
        unknown_tokens=counts["unknown"],
        function_tokens=counts["function"],
        content_tokens=content,
        tamil_ratio=round(tamil_r, 3),
        english_ratio=round(english_r, 3),
    )


def _mix_flags(source: str, output: str, mix: CodeMixProfile) -> list[str]:
    flags: list[str] = []
    src_low = (source or "").lower().strip()
    out_low = (output or "").lower().strip()

    if out_low == src_low:
        flags.append("mix:untranslated_echo")

    if (
        mix.tamil_tokens == 0
        and not _TAMIL_STEM_RE.search(output or "")
        and not _is_short_domain_readout(source, output)
    ):
        flags.append("mix:not_tanglish")

    if mix.content_tokens < 3:
        flags.append("mix:too_short")

    if mix.tamil_ratio < TANGLISH_MIX_TAMIL_MIN:
        flags.append(f"mix:tamil_ratio_low:{mix.tamil_ratio:.2f}")

    if mix.english_ratio > TANGLISH_MIX_ENGLISH_MAX:
        flags.append(f"mix:english_ratio_high:{mix.english_ratio:.2f}")

    # Source echoed with only a suffix tweak — high English, almost no Tamil grammar.
    if mix.tamil_tokens < 2 and mix.english_tokens >= 4:
        flags.append("mix:english_clause_collapse")

    return flags


def audit_non_ollama_translation(
    source: str,
    output: str,
    engine: str,
    *,
    enabled: bool | None = None,
    log: bool = True,
) -> AuditReport | None:
    """
    Audit a non-Ollama Tanglish result for meaning + code-mix ratio.

    Returns None when the engine is Ollama-derived (already validated elsewhere).
    """
    if is_ollama_engine(engine):
        return None
    if enabled is None:
        enabled = TANGLISH_AUDIT_ENABLED
    if not enabled:
        return None

    validation = validate_translation(source or "", output or "")
    mix = code_mix_profile(output or "")
    mix_flags = _mix_flags(source, output, mix)

    hard = list(validation.hard_flags)
    soft = list(validation.soft_flags)
    ok = validation.ok

    hard_mix_prefixes = ("mix:untranslated", "mix:not_tanglish", "mix:english_clause")
    if any(f.startswith(hard_mix_prefixes) for f in mix_flags):
        ok = False

    report = AuditReport(
        engine=engine,
        source=source or "",
        output=output or "",
        meaning_ok=validation.ok,
        hard_flags=hard,
        soft_flags=soft,
        mix_flags=mix_flags,
        mix=mix,
        ok=ok,
    )

    if log:
        _log_audit(report)
    if not report.ok:
        logger.warning(
            "Tanglish audit FAIL engine=%s mix=%s meaning_ok=%s flags=%s mix_flags=%s",
            engine,
            f"ta={mix.tamil_ratio:.2f} en={mix.english_ratio:.2f}",
            validation.ok,
            hard[:3],
            mix_flags,
        )
    return report


def _log_audit(report: AuditReport) -> None:
    path = Path(TANGLISH_AUDIT_LOG)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(report.to_dict(), ensure_ascii=False) + "\n")


def audit_gold_corpus(path: Path | None = None) -> list[AuditReport]:
    """Run audit over every gold pair (regression: gold must always pass)."""
    from config import TANGLISH_GOLD_PAIRS_PATH  # noqa: E402

    gold_path = path or TANGLISH_GOLD_PAIRS_PATH
    rows = json.loads(gold_path.read_text(encoding="utf-8"))
    reports: list[AuditReport] = []
    for row in rows:
        rep = audit_non_ollama_translation(
            row.get("english", ""),
            row.get("tanglish", ""),
            "gold",
            log=False,
        )
        if rep is not None:
            reports.append(rep)
    return reports
