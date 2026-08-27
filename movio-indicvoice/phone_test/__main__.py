"""
Start the movio-indicvoice server in two-phone test mode.

Usage:
  python -m phone_test
  python -m phone_test --https
  python -m phone_test --port 8001 --no-browser
  python -m phone_test --simulate-only
"""
from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Ensure project root is on path when run as python -m phone_test
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import SERVER_HOST, SERVER_PORT  # noqa: E402
from phone_test.lan import detect_lan_ips, format_startup_banner, pick_default_ip  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("phone_test")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Two-phone local voice translation test server")
    p.add_argument("--host", default=SERVER_HOST, help="Bind address (default from config)")
    p.add_argument("--port", type=int, default=SERVER_PORT, help="Port (default from config)")
    p.add_argument(
        "--https",
        action="store_true",
        help="Serve HTTPS with a self-signed cert (needed for Chrome mic on LAN)",
    )
    p.add_argument("--no-browser", action="store_true", help="Do not open the laptop dashboard")
    p.add_argument(
        "--simulate-only",
        action="store_true",
        help="Run automated text self-test against a live server, then exit",
    )
    p.add_argument(
        "--preload-stt",
        action="store_true",
        default=True,
        help="Warm Whisper/ASR at startup (default on)",
    )
    p.add_argument("--no-preload-stt", action="store_false", dest="preload_stt")
    return p.parse_args()


def _open_dashboard(url: str) -> None:
    time.sleep(1.2)
    try:
        webbrowser.open(url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not open browser: %s", exc)


def main() -> None:
    args = _parse_args()

    if args.simulate_only:
        from phone_test.simulate import run_self_test

        ok = run_self_test(base_url=f"http://127.0.0.1:{args.port}")
        sys.exit(0 if ok else 1)

    # Import app after path setup; phone routes are mounted in server.main
    import uvicorn

    from server.main import app  # noqa: F401

    scheme = "http"
    ssl_kwargs: dict = {}
    if args.https:
        from phone_test.tls import ensure_self_signed_cert

        pair = ensure_self_signed_cert()
        if not pair:
            logger.error(
                "HTTPS requested but openssl cert generation failed. "
                "Install OpenSSL or run without --https."
            )
            sys.exit(1)
        cert, key = pair
        ssl_kwargs = {"ssl_certfile": str(cert), "ssl_keyfile": str(key)}
        scheme = "https"
        logger.info(
            "HTTPS enabled (self-signed). Phones must accept the certificate warning once."
        )

    lan_ips = detect_lan_ips()
    print(format_startup_banner(args.port, scheme=scheme, lan_ips=lan_ips))

    if args.preload_stt:
        def _warm() -> None:
            try:
                from phone_test import stt as stt_mod

                logger.info("Preloading STT (Whisper/ASR)…")
                st = stt_mod.status()
                logger.info("STT status: %s", st)
            except Exception as exc:  # noqa: BLE001
                logger.warning("STT preload failed: %s", exc)

        threading.Thread(target=_warm, daemon=True).start()

    dash = f"{scheme}://127.0.0.1:{args.port}/test/"
    if not args.no_browser:
        threading.Thread(target=_open_dashboard, args=(dash,), daemon=True).start()

    default_ip = pick_default_ip(lan_ips)
    if default_ip:
        logger.info("Primary phone URL base: %s://%s:%s/test/", scheme, default_ip, args.port)

    uvicorn.run(
        "server.main:app",
        host=args.host,
        port=args.port,
        reload=False,
        **ssl_kwargs,
    )


if __name__ == "__main__":
    main()
