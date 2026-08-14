"""Outbound-request safety: SSRF guard and store-domain matching.

The tracking API accepts a product URL from whoever calls it and the scraper
then fetches that URL server-side. That is the textbook shape of a Server-Side
Request Forgery: without a guard, ``POST /api/products`` with a URL pointing at
``169.254.169.254`` or an address on the deployment's private network turns this
service into a proxy into its own infrastructure.

Two independent checks run before any live fetch:

``domain_matches``
    The host must belong to a store the project actually supports. Matching is
    done on the parsed *hostname*, never on a substring of the whole URL — a
    substring test accepts ``http://10.0.0.5/?x=amazon.`` and
    ``http://amazon.attacker.example`` alike.

``ensure_public_url``
    Every address the host resolves to must be a globally-routable unicast
    address. Loopback, private, link-local (including the cloud metadata
    endpoint), reserved, multicast and unspecified ranges are all rejected.

This does not defend against DNS rebinding, which needs connect-time pinning of
the validated address. It does close every vector that does not require the
attacker to control a resolver, and redirects are disabled at the call site so a
validated host cannot bounce the request onward to a private address.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

_ALLOWED_SCHEMES = frozenset({"http", "https"})


class UnsafeUrlError(ValueError):
    """Raised when a URL may not be fetched server-side."""


def domain_matches(url: str, domains: tuple[str, ...]) -> bool:
    """Return True if ``url``'s hostname is, or is a subdomain of, a listed domain.

    ``domains`` holds registrable suffixes such as ``("amazon.com", "amazon.co.uk")``.
    A hostname matches when it equals one of them or ends with ``"." + domain``,
    so ``www.amazon.com`` matches ``amazon.com`` while ``amazon.com.evil.test``
    and ``notamazon.com`` do not.
    """
    host = urlsplit(url).hostname
    if not host:
        return False
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in domains)


def ip_is_public(raw: str) -> bool:
    """Return True only for globally-routable unicast addresses."""
    try:
        addr = ipaddress.ip_address(raw)
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


def resolve_host(host: str, port: int) -> list[str]:
    """Return every address ``host`` resolves to, or raise :class:`UnsafeUrlError`."""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"could not resolve host: {host}") from exc
    return [str(info[4][0]) for info in infos]


def ensure_public_url(url: str) -> str:
    """Validate ``url`` for a server-side fetch and return it unchanged.

    Raises :class:`UnsafeUrlError` if the scheme is not http(s), the host is
    missing, or *any* resolved address is not publicly routable.
    """
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsafeUrlError(f"only http(s) URLs may be fetched, got {parts.scheme!r}")

    host = parts.hostname
    if not host:
        raise UnsafeUrlError("URL has no host")

    # A literal address must clear the check on its own; resolution of a literal
    # is a no-op and would otherwise be the only thing standing between an
    # attacker and http://169.254.169.254/.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not ip_is_public(host):
            raise UnsafeUrlError(f"destination address is not public: {host}")
        return url

    port = parts.port or (443 if scheme == "https" else 80)
    for address in resolve_host(host, port):
        if not ip_is_public(address):
            raise UnsafeUrlError(f"{host} resolves to a non-public address ({address})")
    return url
