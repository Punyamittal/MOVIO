"""
Half-duplex conversation FSM for the two-phone test environment.

Priority order: turn detection → echo prevention → speaker routing →
no translation loops. Latency is secondary.
"""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Literal

Role = Literal["A", "B"]

LogFn = Callable[[str], Any]


class ProcessingState(str, Enum):
    IDLE = "IDLE"
    LISTENING_A = "LISTENING_A"
    LISTENING_B = "LISTENING_B"
    PROCESSING = "PROCESSING"
    TRANSLATING = "TRANSLATING"
    TTS_A = "TTS_A"
    TTS_B = "TTS_B"
    OVERLAP = "OVERLAP"
    BARGE_IN = "BARGE_IN"
    ERROR = "ERROR"
    DISCONNECTED = "DISCONNECTED"


class ClaimResult(str, Enum):
    ACCEPTED = "ACCEPTED"
    OVERLAP_REJECTED = "OVERLAP_REJECTED"
    BARGE_IN = "BARGE_IN"
    BUSY = "BUSY"
    ECHO_SUPPRESSED = "ECHO_SUPPRESSED"


def new_utterance_id() -> str:
    return f"utt-{uuid.uuid4().hex[:12]}"


@dataclass
class ConversationController:
    """Per-session half-duplex turn lock + echo / barge-in bookkeeping."""

    session_id: str
    state: ProcessingState = ProcessingState.IDLE
    active_speaker: Role | None = None
    active_utterance_id: str | None = None
    tts_target: Role | None = None  # phone currently playing / about to play TTS
    interruption_of: str | None = None  # utterance_id flagged as interruption
    processed_ids: set[str] = field(default_factory=set)
    pending_replay_blocked: set[str] = field(default_factory=set)
    last_error: str | None = None
    state_history: list[dict[str, Any]] = field(default_factory=list)
    _lock: threading.RLock = field(default_factory=threading.RLock)
    _cancel_tts: bool = False
    _log: LogFn | None = None

    def bind_logger(self, fn: LogFn) -> None:
        self._log = fn

    def _emit(self, message: str, **extra: Any) -> None:
        if self._log:
            self._log(message, **extra)

    def transition(self, new_state: ProcessingState, reason: str = "") -> None:
        with self._lock:
            old = self.state
            if old == new_state and not reason:
                return
            self.state = new_state
            entry = {
                "ts": time.time(),
                "from": old.value,
                "to": new_state.value,
                "reason": reason,
                "speaker": self.active_speaker,
                "utterance_id": self.active_utterance_id,
                "tts_target": self.tts_target,
            }
            self.state_history.append(entry)
            if len(self.state_history) > 120:
                self.state_history = self.state_history[-120:]
            self._emit(
                f"FSM {old.value} → {new_state.value}"
                + (f" ({reason})" if reason else ""),
                speaker=self.active_speaker,
                utterance_id=self.active_utterance_id,
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "fsm_state": self.state.value,
                "active_speaker": self.active_speaker,
                "active_utterance_id": self.active_utterance_id,
                "tts_target": self.tts_target,
                "echo_suppress_a": self.tts_target == "A",
                "echo_suppress_b": self.tts_target == "B",
                "last_error": self.last_error,
                "cancel_tts": self._cancel_tts,
                "recent_transitions": self.state_history[-12:],
            }

    def is_duplicate(self, utterance_id: str | None) -> bool:
        if not utterance_id:
            return False
        with self._lock:
            return utterance_id in self.processed_ids

    def mark_processed(self, utterance_id: str) -> None:
        with self._lock:
            self.processed_ids.add(utterance_id)
            if len(self.processed_ids) > 500:
                # Drop oldest arbitrarily via list slice of sorted ids
                keep = list(self.processed_ids)[-300:]
                self.processed_ids = set(keep)

    def block_stale_replay(self, utterance_id: str) -> None:
        """On disconnect, mark in-flight TTS so reconnect does not replay it."""
        with self._lock:
            if utterance_id:
                self.pending_replay_blocked.add(utterance_id)

    def is_replay_blocked(self, utterance_id: str | None) -> bool:
        if not utterance_id:
            return False
        with self._lock:
            return utterance_id in self.pending_replay_blocked

    def clear_replay_block(self, utterance_id: str) -> None:
        with self._lock:
            self.pending_replay_blocked.discard(utterance_id)

    def listening_state_for(self, role: Role) -> ProcessingState:
        return ProcessingState.LISTENING_A if role == "A" else ProcessingState.LISTENING_B

    def tts_state_for(self, role: Role) -> ProcessingState:
        return ProcessingState.TTS_A if role == "A" else ProcessingState.TTS_B

    def partner(self, role: Role) -> Role:
        return "B" if role == "A" else "A"

    def try_claim_speaker(
        self,
        role: Role,
        *,
        utterance_id: str | None = None,
        is_barge_in: bool = False,
    ) -> ClaimResult:
        """
        Half-duplex claim.

        - IDLE → accept speaker
        - Same speaker already listening → accept (continue)
        - Other speaker during listening → OVERLAP (first speaker wins)
        - During partner TTS → BARGE_IN (stop TTS, switch speaker)
        - During own TTS echo → ECHO_SUPPRESSED (ignore mic hearing TTS)
        - During PROCESSING/TRANSLATING → BUSY (unless barge-in from partner)
        """
        with self._lock:
            uid = utterance_id or new_utterance_id()
            partner = self.partner(role)

            # Echo: this phone is the TTS target — mic is hearing translated audio
            if self.tts_target == role and self.state in (
                ProcessingState.TTS_A,
                ProcessingState.TTS_B,
            ):
                if not is_barge_in:
                    self._emit(f"ECHO_SUPPRESSED phone={role}", utterance_id=uid)
                    return ClaimResult.ECHO_SUPPRESSED
                # Explicit barge-in from the receiving phone while TTS plays
                self._cancel_tts = True
                self.interruption_of = self.active_utterance_id
                self.transition(ProcessingState.BARGE_IN, f"barge_in_from_{role}")
                self.active_speaker = role
                self.active_utterance_id = uid
                self.tts_target = None
                self.transition(self.listening_state_for(role), "after_barge_in")
                return ClaimResult.BARGE_IN

            if self.state == ProcessingState.IDLE or self.state in (
                ProcessingState.ERROR,
                ProcessingState.DISCONNECTED,
            ):
                self._cancel_tts = False
                self.active_speaker = role
                self.active_utterance_id = uid
                self.interruption_of = None
                self.transition(self.listening_state_for(role), "speaker_detected")
                return ClaimResult.ACCEPTED

            if self.active_speaker == role and self.state in (
                ProcessingState.LISTENING_A,
                ProcessingState.LISTENING_B,
                ProcessingState.BARGE_IN,
            ):
                if utterance_id:
                    self.active_utterance_id = uid
                return ClaimResult.ACCEPTED

            # Other phone starts while we are listening to first speaker
            if self.state in (ProcessingState.LISTENING_A, ProcessingState.LISTENING_B):
                if self.active_speaker and self.active_speaker != role:
                    self.transition(ProcessingState.OVERLAP, f"{role}_interrupted")
                    self.interruption_of = uid
                    self._emit(
                        f"OVERLAP: keep {self.active_speaker}, flag {role} as interruption",
                        utterance_id=uid,
                    )
                    # Return to listening for original speaker
                    self.transition(
                        self.listening_state_for(self.active_speaker),
                        "overlap_resolved_keep_first",
                    )
                    return ClaimResult.OVERLAP_REJECTED

            # Partner barges in during our TTS (listener speaks over translated audio)
            if self.state in (ProcessingState.TTS_A, ProcessingState.TTS_B):
                if self.tts_target == partner or self.active_speaker != role:
                    # role is speaking while partner should be listening to TTS —
                    # classic barge-in: stop TTS, give floor to new speaker
                    if role != self.active_speaker:
                        self._cancel_tts = True
                        self.interruption_of = self.active_utterance_id
                        self.transition(ProcessingState.BARGE_IN, f"barge_in_{role}")
                        self.active_speaker = role
                        self.active_utterance_id = uid
                        self.tts_target = None
                        self.transition(self.listening_state_for(role), "floor_to_new_speaker")
                        return ClaimResult.BARGE_IN

            if self.state in (ProcessingState.PROCESSING, ProcessingState.TRANSLATING):
                if is_barge_in and role != self.active_speaker:
                    self._cancel_tts = True
                    self.interruption_of = self.active_utterance_id
                    self.transition(ProcessingState.BARGE_IN, f"barge_during_proc_{role}")
                    self.active_speaker = role
                    self.active_utterance_id = uid
                    self.tts_target = None
                    self.transition(self.listening_state_for(role), "floor_stolen")
                    return ClaimResult.BARGE_IN
                return ClaimResult.BUSY

            if self.state == ProcessingState.OVERLAP:
                return ClaimResult.OVERLAP_REJECTED

            return ClaimResult.BUSY

    def begin_processing(self, utterance_id: str, speaker: Role) -> bool:
        with self._lock:
            if self.is_duplicate(utterance_id):
                return False
            self.active_speaker = speaker
            self.active_utterance_id = utterance_id
            self._cancel_tts = False
            self.transition(ProcessingState.PROCESSING, "utterance_finalized")
            return True

    def begin_translating(self) -> None:
        self.transition(ProcessingState.TRANSLATING, "asr_done")

    def begin_tts(self, target: Role, utterance_id: str) -> None:
        with self._lock:
            self.tts_target = target
            self.active_utterance_id = utterance_id
            self.transition(self.tts_state_for(target), f"tts_to_{target}")

    def tts_finished(self, utterance_id: str | None = None) -> None:
        with self._lock:
            if utterance_id and self.active_utterance_id and utterance_id != self.active_utterance_id:
                # Stale completion from interrupted TTS
                self._emit("ignore_stale_tts_done", utterance_id=utterance_id)
                return
            self.tts_target = None
            self.active_speaker = None
            if self.active_utterance_id:
                self.mark_processed(self.active_utterance_id)
            self.active_utterance_id = None
            self._cancel_tts = False
            self.transition(ProcessingState.IDLE, "tts_complete")

    def fail(self, error: str) -> None:
        with self._lock:
            self.last_error = error
            self.tts_target = None
            self.transition(ProcessingState.ERROR, error[:120])

    def recover_idle(self, reason: str = "recover") -> None:
        with self._lock:
            self.tts_target = None
            self.active_speaker = None
            self.active_utterance_id = None
            self._cancel_tts = False
            self.transition(ProcessingState.IDLE, reason)

    def should_cancel(self) -> bool:
        with self._lock:
            return self._cancel_tts

    def on_disconnect(self, role: Role) -> None:
        with self._lock:
            if self.tts_target == role and self.active_utterance_id:
                self.block_stale_replay(self.active_utterance_id)
            if self.active_speaker == role:
                self.recover_idle(f"{role}_disconnected")
            else:
                self.transition(ProcessingState.DISCONNECTED, f"{role}_left")
                # Soft: other phone may still be connected — return to idle if not mid-turn
                if self.state == ProcessingState.DISCONNECTED and not self.active_speaker:
                    self.transition(ProcessingState.IDLE, "await_reconnect")

    def on_reconnect(self, role: Role) -> None:
        with self._lock:
            self._emit(f"PHONE {role} RECONNECTED — resume without replaying stale TTS")
            if self.state == ProcessingState.DISCONNECTED:
                self.transition(ProcessingState.IDLE, "reconnect")
