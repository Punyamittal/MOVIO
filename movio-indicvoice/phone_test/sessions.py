"""In-memory test session store for two-phone pairing."""
from __future__ import annotations

import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["A", "B"]

SESSION_TTL_SEC = 2 * 60 * 60  # 2 hours
MAX_LOG_ENTRIES = 80


def _session_id() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "TEST-" + "".join(secrets.choice(alphabet) for _ in range(4))


def _token() -> str:
    return secrets.token_urlsafe(18)


@dataclass
class PhoneSide:
    role: Role
    token: str
    connected: bool = False
    input_lang: str = "en"
    output_lang: str = "tanglish"
    mic_active: bool = False
    receiving: bool = False
    last_seen: float = 0.0


@dataclass
class UtteranceEvent:
    direction: str  # "A→B" or "B→A"
    source_text: str
    translated_text: str
    normalized_text: str
    latency_sec: float
    stt_ms: float
    translate_tts_ms: float
    stages: list[str] = field(default_factory=list)
    error: str | None = None
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "source_text": self.source_text,
            "translated_text": self.translated_text,
            "normalized_text": self.normalized_text,
            "latency_sec": round(self.latency_sec, 3),
            "stt_ms": round(self.stt_ms, 1),
            "translate_tts_ms": round(self.translate_tts_ms, 1),
            "stages": self.stages,
            "error": self.error,
            "ts": self.ts,
        }


@dataclass
class TestSession:
    id: str
    token_a: str
    token_b: str
    created_at: float
    expires_at: float
    phone_a: PhoneSide
    phone_b: PhoneSide
    debug: bool = True
    utterances: list[UtteranceEvent] = field(default_factory=list)
    event_log: list[dict[str, Any]] = field(default_factory=list)
    avg_latency_ab: float = 0.0
    avg_latency_ba: float = 0.0
    _lat_ab: list[float] = field(default_factory=list)
    _lat_ba: list[float] = field(default_factory=list)

    def phone(self, role: Role) -> PhoneSide:
        return self.phone_a if role == "A" else self.phone_b

    def partner(self, role: Role) -> PhoneSide:
        return self.phone_b if role == "A" else self.phone_a

    def validate_token(self, role: Role, token: str) -> bool:
        expected = self.token_a if role == "A" else self.token_b
        return secrets.compare_digest(expected, token or "")

    def expired(self) -> bool:
        return time.time() > self.expires_at

    def log(self, message: str, **extra: Any) -> dict[str, Any]:
        entry = {
            "ts": time.time(),
            "iso": time.strftime("%H:%M:%S"),
            "message": message,
            **extra,
        }
        self.event_log.append(entry)
        if len(self.event_log) > 200:
            self.event_log = self.event_log[-200:]
        return entry

    def add_utterance(self, ev: UtteranceEvent) -> None:
        self.utterances.append(ev)
        if len(self.utterances) > MAX_LOG_ENTRIES:
            self.utterances = self.utterances[-MAX_LOG_ENTRIES:]
        if ev.error:
            return
        if ev.direction == "A→B":
            self._lat_ab.append(ev.latency_sec)
            self.avg_latency_ab = sum(self._lat_ab) / len(self._lat_ab)
        else:
            self._lat_ba.append(ev.latency_sec)
            self.avg_latency_ba = sum(self._lat_ba) / len(self._lat_ba)

    def public_state(self, host_base: str | None = None) -> dict[str, Any]:
        last_ab = next((u for u in reversed(self.utterances) if u.direction == "A→B"), None)
        last_ba = next((u for u in reversed(self.utterances) if u.direction == "B→A"), None)
        # Tokens are intentional for local laptop dashboard QR rebuilds.
        urls: dict[str, str] = {}
        if host_base:
            base = host_base.rstrip("/")
            urls = {
                "A": f"{base}/test/{self.id}/A?token={self.token_a}",
                "B": f"{base}/test/{self.id}/B?token={self.token_b}",
            }
        return {
            "session_id": self.id,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "expired": self.expired(),
            "token_a": self.token_a,
            "token_b": self.token_b,
            "urls": urls,
            "phone_a": {
                "role": "A",
                "connected": self.phone_a.connected,
                "input_lang": self.phone_a.input_lang,
                "output_lang": self.phone_a.output_lang,
                "mic_active": self.phone_a.mic_active,
                "receiving": self.phone_a.receiving,
            },
            "phone_b": {
                "role": "B",
                "connected": self.phone_b.connected,
                "input_lang": self.phone_b.input_lang,
                "output_lang": self.phone_b.output_lang,
                "mic_active": self.phone_b.mic_active,
                "receiving": self.phone_b.receiving,
            },
            "last_ab": last_ab.to_dict() if last_ab else None,
            "last_ba": last_ba.to_dict() if last_ba else None,
            "avg_latency_ab": round(self.avg_latency_ab, 3),
            "avg_latency_ba": round(self.avg_latency_ba, 3),
            "event_log": self.event_log[-40:],
            "debug": self.debug,
        }


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, TestSession] = {}
        self.active_id: str | None = None

    def create(
        self,
        *,
        input_a: str = "en",
        output_a: str = "tanglish",
        input_b: str = "tanglish",
        output_b: str = "en",
        debug: bool = True,
        ttl_sec: float = SESSION_TTL_SEC,
    ) -> TestSession:
        now = time.time()
        sid = _session_id()
        while sid in self._sessions:
            sid = _session_id()
        token_a, token_b = _token(), _token()
        session = TestSession(
            id=sid,
            token_a=token_a,
            token_b=token_b,
            created_at=now,
            expires_at=now + ttl_sec,
            phone_a=PhoneSide(role="A", token=token_a, input_lang=input_a, output_lang=output_a),
            phone_b=PhoneSide(role="B", token=token_b, input_lang=input_b, output_lang=output_b),
            debug=debug,
        )
        session.log("SESSION CREATED")
        self._sessions[sid] = session
        self.active_id = sid
        self._purge_expired()
        return session

    def get(self, session_id: str) -> TestSession | None:
        self._purge_expired()
        s = self._sessions.get(session_id)
        if s and s.expired():
            self.end(session_id)
            return None
        return s

    def active(self) -> TestSession | None:
        if self.active_id:
            return self.get(self.active_id)
        return None

    def end(self, session_id: str) -> bool:
        s = self._sessions.pop(session_id, None)
        if self.active_id == session_id:
            self.active_id = None
        return s is not None

    def _purge_expired(self) -> None:
        now = time.time()
        dead = [k for k, v in self._sessions.items() if v.expires_at < now]
        for k in dead:
            self._sessions.pop(k, None)
            if self.active_id == k:
                self.active_id = None


store = SessionStore()
