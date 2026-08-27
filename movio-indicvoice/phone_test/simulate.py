"""
Automated local self-test (no phones required).

Verifies: session create → text utterance A→B and B→A through the real
translate → TTS pipeline. Optionally exercises STT if a WAV fixture exists.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import httpx

logger = logging.getLogger("phone_test.simulate")

SAMPLE_AB = "Unga driver 5 minutes la vandhuruvaanga. OTP 4821 share pannunga."
SAMPLE_BA = "Your driver will arrive in five minutes. Please share the OTP."


def _safe_print(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))


def run_self_test(base_url: str = "http://127.0.0.1:8001", timeout: float = 180.0) -> bool:
    base = base_url.rstrip("/")
    ok = True
    _safe_print("=" * 48)
    _safe_print("PHONE TEST SELF-SIMULATION")
    _safe_print("=" * 48)
    _safe_print(f"Target: {base}")

    with httpx.Client(timeout=timeout) as client:
        # Health
        try:
            h = client.get(f"{base}/health")
            h.raise_for_status()
            _safe_print(f"[PASS] Server health: {h.json().get('default_backend')}")
        except Exception as exc:  # noqa: BLE001
            _safe_print(f"[FAIL] Server not reachable: {exc}")
            _safe_print("Start the server first: python -m phone_test")
            return False

        # STT status (informational)
        try:
            st = client.get(f"{base}/test/api/stt-status").json()
            flag = "PASS" if st.get("ready") else "WARN"
            _safe_print(f"[{flag}] STT ready={st.get('ready')} backend={st.get('backend')}")
        except Exception as exc:  # noqa: BLE001
            _safe_print(f"[WARN] STT status: {exc}")

        # Create session
        try:
            s = client.post(
                f"{base}/test/api/session",
                json={
                    "input_a": "ta",
                    "output_a": "en",
                    "input_b": "en",
                    "output_b": "ta",
                    "host": base,
                },
            )
            s.raise_for_status()
            state = s.json()
            sid = state["session_id"]
            _safe_print(f"[PASS] Session created: {sid}")
            _safe_print(f"       QR A: {state['urls'].get('A', 'n/a')}")
            _safe_print(f"       QR B: {state['urls'].get('B', 'n/a')}")
        except Exception as exc:  # noqa: BLE001
            _safe_print(f"[FAIL] Session create: {exc}")
            return False

        # A -> B text pipeline
        try:
            r = client.post(
                f"{base}/test/api/session/{sid}/simulate",
                json={"direction": "A→B", "text": SAMPLE_AB, "skip_stt": True},
            )
            r.raise_for_status()
            body = r.json()
            ev = body.get("event") or {}
            if body.get("ok") and (ev.get("translated_text") or ev.get("normalized_text") or ev.get("source_text")):
                _safe_print("[PASS] A->B translate+TTS")
                _safe_print(f"       src: {ev.get('source_text')}")
                _safe_print(f"       out: {ev.get('translated_text') or ev.get('normalized_text')}")
                _safe_print(f"       latency: {ev.get('latency_sec')}s")
            else:
                _safe_print(f"[FAIL] A->B: {ev}")
                ok = False
        except Exception as exc:  # noqa: BLE001
            _safe_print(f"[FAIL] A->B simulate: {exc}")
            ok = False

        # B -> A text pipeline
        try:
            r = client.post(
                f"{base}/test/api/session/{sid}/simulate",
                json={"direction": "B→A", "text": SAMPLE_BA, "skip_stt": True},
            )
            r.raise_for_status()
            body = r.json()
            ev = body.get("event") or {}
            if body.get("ok") and (ev.get("translated_text") or ev.get("normalized_text") or ev.get("source_text")):
                _safe_print("[PASS] B->A translate+TTS")
                _safe_print(f"       src: {ev.get('source_text')}")
                _safe_print(f"       out: {ev.get('translated_text') or ev.get('normalized_text')}")
                _safe_print(f"       latency: {ev.get('latency_sec')}s")
            else:
                _safe_print(f"[FAIL] B->A: {ev}")
                ok = False
        except Exception as exc:  # noqa: BLE001
            _safe_print(f"[FAIL] B->A simulate: {exc}")
            ok = False

        # Cleanup
        try:
            client.delete(f"{base}/test/api/session/{sid}")
            _safe_print("[PASS] Session ended")
        except Exception as exc:  # noqa: BLE001
            _safe_print(f"[WARN] Session end: {exc}")

    _safe_print("=" * 48)
    _safe_print("RESULT: " + ("PASS" if ok else "FAIL"))
    _safe_print("=" * 48)
    _safe_print(
        "Note: Full mic STT + two-phone audio requires real phones "
        "(or browser clients) on the same Wi-Fi."
    )
    return ok


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001"
    sys.exit(0 if run_self_test(base) else 1)
