"""Detect LAN IPv4 addresses for phone QR pairing."""
from __future__ import annotations

import socket
from typing import Iterable

# Host-only / hypervisor adapters phones on real Wi-Fi can never reach.
_VIRTUAL_PREFIXES = (
    "192.168.56.",  # VirtualBox host-only
    "192.168.59.",
    "192.168.99.",  # Docker Toolbox / old VirtualBox
    "172.17.",  # Docker bridge
    "172.18.",
    "172.19.",
    "172.20.",
    "172.21.",
    "172.22.",
    "172.23.",
    "172.24.",
    "172.25.",
    "172.26.",
    "172.27.",
    "172.28.",
    "172.29.",
    "172.30.",
    "172.31.",
)


def _is_private(ip: str) -> bool:
    if ip.startswith("127.") or ip.startswith("169.254."):
        return False
    parts = ip.split(".")
    if len(parts) != 4:
        return False
    try:
        a, b = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    if a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    if a == 192 and b == 168:
        return True
    return False


def _is_virtual(ip: str) -> bool:
    return any(ip.startswith(p) for p in _VIRTUAL_PREFIXES)


def detect_lan_ips() -> list[str]:
    """Return unique private IPv4 addresses on this machine (best-effort).

    Real Wi-Fi / Ethernet addresses are listed first. VirtualBox / Docker
    host-only adapters are kept last so QR codes do not accidentally point
    at an IP phones can never reach.
    """
    found: list[str] = []

    def add(ip: str) -> None:
        if ip and _is_private(ip) and ip not in found:
            found.append(ip)

    # UDP connect trick — no packets sent; reveals preferred outbound interface
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(("8.8.8.8", 80))
        add(s.getsockname()[0])
        s.close()
    except OSError:
        pass

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            add(info[4][0])
    except OSError:
        pass

    try:
        import psutil  # type: ignore

        for addrs in psutil.net_if_addrs().values():
            for addr in addrs:
                if getattr(addr, "family", None) == socket.AF_INET:
                    add(addr.address)
    except Exception:  # noqa: BLE001
        pass

    real = [ip for ip in found if not _is_virtual(ip)]
    virt = [ip for ip in found if _is_virtual(ip)]
    return real + virt


def pick_default_ip(ips: Iterable[str] | None = None) -> str | None:
    ips = list(ips) if ips is not None else detect_lan_ips()
    for ip in ips:
        if not _is_virtual(ip):
            return ip
    return ips[0] if ips else None


def format_startup_banner(port: int, scheme: str = "http", lan_ips: list[str] | None = None) -> str:
    lan_ips = lan_ips if lan_ips is not None else detect_lan_ips()
    lines = [
        "",
        "========================================",
        "  TWO-PHONE VOICE TRANSLATION TEST",
        "========================================",
        "",
        "Testing server started.",
        "",
        "Laptop:",
        f"  {scheme}://localhost:{port}/test/",
        "",
        "Phone connections:",
    ]
    if lan_ips:
        for ip in lan_ips:
            tag = "  (VirtualBox/Docker — phones cannot use this)" if _is_virtual(ip) else ""
            lines.append(f"  {scheme}://{ip}:{port}/test/{tag}")
    else:
        lines.append("  (no LAN IP detected — connect phones via Wi-Fi and restart)")
    lines.extend(
        [
            "",
            "Make sure both phones are connected",
            "to the same Wi-Fi network as this laptop.",
            "",
            "If phones cannot open the page:",
            "  • Use the Wi-Fi IP above, NOT 192.168.56.x (VirtualBox)",
            "  • Allow inbound TCP on this port in the firewall",
            "  • Some campus/office Wi-Fi blocks phone→laptop (AP isolation)",
            "  • Prefer HTTPS mode if the browser blocks the microphone on HTTP LAN",
            "========================================",
            "",
        ]
    )
    return "\n".join(lines)
