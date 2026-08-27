"""
Append-only synthesis telemetry for the Movio overview dashboard.

Stores recent TTS events as JSONL under server/data/synthesis_events.jsonl.
Aggregation is in-process and cheap — safe to call on every successful synth.
"""
from __future__ import annotations

import json
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import PROJECT_ROOT

DATA_DIR = PROJECT_ROOT / "server" / "data"
EVENTS_PATH = DATA_DIR / "synthesis_events.jsonl"
MAX_EVENTS = 5000
_LOCK = threading.Lock()

_VOICE_HINTS = (
    ("jaya", "jaya"),
    ("kavitha", "kavitha"),
    ("divya", "divya"),
    ("rohit", "rohit"),
    ("pallavi", "pallavi"),
    ("valluvar", "valluvar"),
    ("neerja", "neerja"),
    ("prabhat", "prabhat"),
)


def voice_label(voice_style: str | None, backend: str | None = None) -> str:
    s = (voice_style or "").lower()
    for needle, label in _VOICE_HINTS:
        if needle in s:
            return label
    if backend:
        return str(backend)
    return "default"


def _ensure_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def record_synthesis(
    *,
    text: str,
    normalized_text: str = "",
    voice_style: str = "",
    backend: str = "",
    detected_lang: str = "",
    target_lang: str = "",
    ttfa_ms: float | None = None,
    full_synthesis_ms: float | None = None,
    audio_duration_sec: float = 0.0,
    cache_hit: bool = False,
    source: str = "api",
) -> None:
    """Best-effort append; never raise into the TTS path."""
    try:
        event = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "epoch": time.time(),
            "text": (text or "")[:400],
            "normalized_text": (normalized_text or "")[:400],
            "voice": voice_label(voice_style, backend),
            "voice_style": (voice_style or "")[:160],
            "backend": backend or "",
            "detected_lang": detected_lang or "",
            "target_lang": target_lang or "",
            "ttfa_ms": round(float(ttfa_ms), 2) if ttfa_ms is not None else None,
            "full_synthesis_ms": (
                round(float(full_synthesis_ms), 2) if full_synthesis_ms is not None else None
            ),
            "audio_duration_sec": round(float(audio_duration_sec or 0.0), 3),
            "cache_hit": bool(cache_hit),
            "source": source,
        }
        line = json.dumps(event, ensure_ascii=False)
        with _LOCK:
            _ensure_dir()
            with EVENTS_PATH.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            _maybe_trim_unlocked()
    except Exception:  # noqa: BLE001
        pass


def _maybe_trim_unlocked() -> None:
    if not EVENTS_PATH.exists():
        return
    try:
        raw = EVENTS_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(raw) <= MAX_EVENTS:
        return
    EVENTS_PATH.write_text("\n".join(raw[-MAX_EVENTS:]) + "\n", encoding="utf-8")


def load_events(limit: int | None = None) -> list[dict[str, Any]]:
    if not EVENTS_PATH.exists():
        return []
    try:
        lines = EVENTS_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if limit is not None and limit > 0:
        return out[-limit:]
    return out


def _percentile(sorted_vals: list[float], p: float) -> float | None:
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _day_key(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d")


def _parse_ts(ev: dict[str, Any]) -> datetime | None:
    raw = ev.get("ts")
    if isinstance(raw, str) and raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    epoch = ev.get("epoch")
    if isinstance(epoch, (int, float)):
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc)
    return None


def aggregate_overview(events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    events = events if events is not None else load_events()
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)

    ttfa_vals: list[float] = []
    full_vals: list[float] = []
    audio_sec = 0.0
    last_24h = 0
    lang_counts: Counter[str] = Counter()
    voice_counts: Counter[str] = Counter()
    backend_counts: Counter[str] = Counter()
    daily: dict[str, int] = defaultdict(int)
    daily_by_voice: dict[str, Counter[str]] = defaultdict(Counter)
    daily_by_lang: dict[str, Counter[str]] = defaultdict(Counter)
    heatmap: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    ttfa_buckets = {
        "0-200": 0,
        "200-400": 0,
        "400-600": 0,
        "600-800": 0,
        "800-1000": 0,
        "1000+": 0,
    }
    funnel = {"studio": 0, "batch": 0, "comparison": 0, "evaluation": 0}

    for ev in events:
        ts = _parse_ts(ev) or now
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        src = (ev.get("source") or "api").lower()
        if src in ("batch", "comparison", "evaluation", "studio", "api", "stream", "ws"):
            if src in ("api", "stream", "ws", "studio"):
                funnel["studio"] += 1
            elif src == "batch":
                funnel["batch"] += 1
            elif src == "comparison":
                funnel["comparison"] += 1
            elif src == "evaluation":
                funnel["evaluation"] += 1
        else:
            funnel["studio"] += 1

        if ts >= day_ago:
            last_24h += 1
        if ts < week_ago:
            continue

        dk = _day_key(ts)
        daily[dk] += 1
        voice = str(ev.get("voice") or "default")
        lang = str(ev.get("target_lang") or ev.get("detected_lang") or "unknown").lower()
        if lang in ("ta-in", "tamil"):
            lang = "ta"
        if lang in ("en-in", "english"):
            lang = "en"
        lang_counts[lang] += 1
        voice_counts[voice] += 1
        backend_counts[str(ev.get("backend") or "unknown")] += 1
        daily_by_voice[dk][voice] += 1
        daily_by_lang[dk][lang] += 1
        heatmap[ts.strftime("%a")][ts.hour] += 1

        audio_sec += float(ev.get("audio_duration_sec") or 0.0)
        ttfa = ev.get("ttfa_ms")
        if isinstance(ttfa, (int, float)):
            t = float(ttfa)
            ttfa_vals.append(t)
            if t < 200:
                ttfa_buckets["0-200"] += 1
            elif t < 400:
                ttfa_buckets["200-400"] += 1
            elif t < 600:
                ttfa_buckets["400-600"] += 1
            elif t < 800:
                ttfa_buckets["600-800"] += 1
            elif t < 1000:
                ttfa_buckets["800-1000"] += 1
            else:
                ttfa_buckets["1000+"] += 1
        full = ev.get("full_synthesis_ms")
        if isinstance(full, (int, float)):
            full_vals.append(float(full))

    ttfa_vals.sort()
    full_vals.sort()
    week_days = [(now - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(6, -1, -1)]
    weekday_order = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]

    recent = []
    for ev in reversed(events[-40:]):
        recent.append(
            {
                "text": ev.get("normalized_text") or ev.get("text") or "",
                "lang": ev.get("target_lang") or ev.get("detected_lang") or "",
                "voice": ev.get("voice") or "",
                "backend": ev.get("backend") or "",
                "ttfa_ms": ev.get("ttfa_ms"),
                "ts": ev.get("ts"),
            }
        )

    return {
        "syntheses_total": len(events),
        "syntheses_24h": last_24h,
        "syntheses_7d": sum(daily.values()),
        "avg_ttfa_ms": round(sum(ttfa_vals) / len(ttfa_vals), 1) if ttfa_vals else None,
        "min_ttfa_ms": round(ttfa_vals[0], 1) if ttfa_vals else None,
        "max_ttfa_ms": round(ttfa_vals[-1], 1) if ttfa_vals else None,
        "p99_ttfa_ms": round(_percentile(ttfa_vals, 99) or 0, 1) if ttfa_vals else None,
        "p99_full_ms": round(_percentile(full_vals, 99) or 0, 1) if full_vals else None,
        "audio_minutes": round(audio_sec / 60.0, 2),
        "ttfa_target_ms": 500,
        "language_mix": dict(lang_counts),
        "voice_usage": dict(voice_counts),
        "backend_usage": dict(backend_counts),
        "activity_7d": [{"day": d, "count": daily.get(d, 0)} for d in week_days],
        "trend_by_voice": [
            {
                "day": d,
                "voices": dict(daily_by_voice.get(d, {})),
            }
            for d in week_days
        ],
        "trend_by_lang": [
            {"day": d, "langs": dict(daily_by_lang.get(d, {}))} for d in week_days
        ],
        "ttfa_distribution": ttfa_buckets,
        "heatmap": {
            day: {str(h): heatmap[day].get(h, 0) for h in range(24)}
            for day in weekday_order
        },
        "funnel": funnel,
        "recent": recent[:12],
    }
