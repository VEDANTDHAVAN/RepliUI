"""URL validation for the analysis pipeline.

Kept deterministic and free of network access: this is a pre-flight check, not a
reachability test. Blocking local and private addresses avoids turning the
analyzer's browser into a request proxy for internal services.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

ALLOWED_SCHEMES = {"http", "https"}
MAX_URL_LENGTH = 2048


class InvalidURLError(ValueError):
    """Raised with a user-facing message; never a stack trace."""


def validate_url(raw: str) -> str:
    """Return a normalized URL or raise `InvalidURLError` with a safe message."""
    if not raw or not raw.strip():
        raise InvalidURLError("A website URL is required")
    candidate = raw.strip()
    if len(candidate) > MAX_URL_LENGTH:
        raise InvalidURLError("URL is too long")
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise InvalidURLError("Only http and https URLs are supported")
    host = (parsed.hostname or "").strip()
    if not host:
        raise InvalidURLError("URL is missing a hostname")
    if "." not in host and host != "localhost":
        raise InvalidURLError("URL hostname is not valid")
    if _is_blocked_host(host):
        raise InvalidURLError("URL points to a local or private address")
    return parsed.geturl()


def _is_blocked_host(host: str) -> bool:
    lowered = host.lower()
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
    )


def is_reachable_host(host: str) -> bool:
    """Best-effort DNS check used only to produce a clearer error message."""
    try:
        socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    return True
