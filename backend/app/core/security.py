"""URL validation and SSRF protection.

The engine only ever fetches resources the user asked for, but a replicated
page can reference arbitrary URLs.  Before any network request we validate the
scheme and make sure the resolved IP address is a public one, blocking
loopback, private ranges, link-local addresses and the cloud metadata endpoint.
"""
from __future__ import annotations

import ipaddress
import socket
from functools import lru_cache
from urllib.parse import urlparse, urlsplit, urlunsplit

from app.config import settings

ALLOWED_SCHEMES = {"http", "https"}

# Host names that must never be contacted even if they resolve publicly.
BLOCKED_HOST_SUFFIXES = (
    ".local",
    ".internal",
    ".localhost",
)
BLOCKED_HOST_NAMES = {
    "localhost",
    "metadata.google.internal",
    "metadata",
}


class UnsafeUrlError(ValueError):
    """Raised when a URL is rejected by the security policy."""


def normalize_url(url: str) -> str:
    """Trim, add a scheme if missing, and drop fragments."""
    url = (url or "").strip()
    if not url:
        raise UnsafeUrlError("Empty URL")
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    # Strip the fragment; keep query (needed for some routed pages).
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", parts.query, ""))


def _ip_is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
    )


@lru_cache(maxsize=4096)
def _resolve_all_public(host: str) -> bool:
    """Return True only if every resolved address for ``host`` is public."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    if not infos:
        return False
    for info in infos:
        ip = info[4][0]
        if not _ip_is_public(ip):
            return False
    return True


def host_is_allowed(host: str | None) -> bool:
    if not host:
        return False
    host = host.lower().strip(".")
    if host in BLOCKED_HOST_NAMES:
        return False
    if any(host == s.lstrip(".") or host.endswith(s) for s in BLOCKED_HOST_SUFFIXES):
        return False
    # An IP literal can be checked directly.
    try:
        ipaddress.ip_address(host)
        return _ip_is_public(host)
    except ValueError:
        pass
    if not settings.block_private_hosts:
        return True
    return _resolve_all_public(host)


def is_safe_url(url: str) -> bool:
    try:
        parts = urlparse(url)
    except ValueError:
        return False
    if parts.scheme not in ALLOWED_SCHEMES:
        return False
    return host_is_allowed(parts.hostname)


def validate_target_url(url: str) -> str:
    """Validate and normalize a user-supplied seed URL, raising on rejection."""
    normalized = normalize_url(url)
    parts = urlparse(normalized)
    if parts.scheme not in ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"Unsupported scheme: {parts.scheme!r}")
    if not parts.hostname:
        raise UnsafeUrlError("URL has no host")
    if not host_is_allowed(parts.hostname):
        raise UnsafeUrlError(
            f"Host {parts.hostname!r} is not allowed (private/loopback/metadata addresses are blocked)"
        )
    return normalized
