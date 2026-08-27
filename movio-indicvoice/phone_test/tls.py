"""Optional self-signed TLS for LAN microphone access (Chrome requires secure context)."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("phone_test.tls")

CERT_DIR = Path(__file__).resolve().parent / ".certs"
CERT_FILE = CERT_DIR / "cert.pem"
KEY_FILE = CERT_DIR / "key.pem"


def ensure_self_signed_cert() -> tuple[Path, Path] | None:
    """
    Create a self-signed cert with openssl if missing.
    Returns (cert, key) or None if openssl is unavailable.
    """
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    if CERT_FILE.exists() and KEY_FILE.exists():
        return CERT_FILE, KEY_FILE

    # SAN covers localhost + common LAN use; browsers still warn (expected for local test).
    conf = CERT_DIR / "openssl.cnf"
    conf.write_text(
        "\n".join(
            [
                "[req]",
                "distinguished_name = req_distinguished_name",
                "x509_extensions = v3_req",
                "prompt = no",
                "[req_distinguished_name]",
                "CN = movio-phone-test",
                "[v3_req]",
                "keyUsage = keyEncipherment, dataEncipherment",
                "extendedKeyUsage = serverAuth",
                "subjectAltName = @alt_names",
                "[alt_names]",
                "DNS.1 = localhost",
                "IP.1 = 127.0.0.1",
            ]
        ),
        encoding="utf-8",
    )

    cmd = [
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-keyout",
        str(KEY_FILE),
        "-out",
        str(CERT_FILE),
        "-days",
        "825",
        "-nodes",
        "-config",
        str(conf),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info("Created self-signed TLS cert at %s", CERT_FILE)
        return CERT_FILE, KEY_FILE
    except FileNotFoundError:
        logger.warning("openssl not found — cannot enable HTTPS automatically")
        return None
    except subprocess.CalledProcessError as exc:
        logger.warning("openssl failed: %s", exc.stderr or exc)
        return None
