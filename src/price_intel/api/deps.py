"""Access control for the write endpoints.

The read endpoints expose nothing but public product data and stay open. The
write endpoints do not: ``POST /api/track`` makes the server fetch a URL chosen
by the caller, and ``DELETE /api/products/{id}`` destroys stored history. On a
publicly reachable deployment both need a gate.

Two levels, because they carry different consequences:

``require_write_access``
    Guards tracking and refresh. If ``API_KEY`` is configured the header must
    match it. If it is not configured, the request is allowed **only** while the
    scraper runs in offline ``fixture`` mode, where no outbound request is made
    at all; in ``live`` mode an unconfigured key is a misconfiguration and the
    endpoint reports 503 rather than quietly acting as an open fetch proxy.

``require_admin_access``
    Guards deletion. Always requires a configured key — there is no mode in
    which anonymous destruction of data is the intended behaviour.

Comparison uses :func:`hmac.compare_digest` so a wrong key cannot be recovered
byte by byte from response timing.
"""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque

from fastapi import Depends, Header, HTTPException, Request, status

from ..config import ScraperMode, Settings, get_settings

_API_KEY_HEADER = "X-API-Key"


def _check_key(supplied: str | None, expected: str) -> bool:
    if not supplied:
        return False
    return hmac.compare_digest(supplied.strip(), expected)


def require_write_access(
    x_api_key: str | None = Header(default=None, alias=_API_KEY_HEADER),
    settings: Settings = Depends(get_settings),
) -> None:
    """Allow a write request, or raise 401/503."""
    expected = settings.api_key.strip()
    if expected:
        if not _check_key(x_api_key, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"a valid {_API_KEY_HEADER} header is required",
                headers={"WWW-Authenticate": _API_KEY_HEADER},
            )
        return

    if settings.scraper_mode is ScraperMode.LIVE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "write endpoints are disabled: set API_KEY before running with "
                "SCRAPER_MODE=live, otherwise this endpoint is an open fetch proxy"
            ),
        )


def require_admin_access(
    x_api_key: str | None = Header(default=None, alias=_API_KEY_HEADER),
    settings: Settings = Depends(get_settings),
) -> None:
    """Allow a destructive request, or raise 401/503."""
    expected = settings.api_key.strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="deletion is disabled: no API_KEY is configured",
        )
    if not _check_key(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"a valid {_API_KEY_HEADER} header is required",
            headers={"WWW-Authenticate": _API_KEY_HEADER},
        )


class _SlidingWindow:
    """Per-client request counter over a sliding time window.

    Deliberately in-process: it protects a single-instance deployment from a
    loop of write requests, and nothing more. A multi-instance deployment needs
    a shared store (Redis) or a limit at the reverse proxy.
    """

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, client: str, limit: int, window: float, now: float) -> bool:
        hits = self._hits[client]
        cutoff = now - window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


_write_limiter = _SlidingWindow()


def reset_rate_limiter() -> None:
    """Clear all recorded hits. Used by the test-suite."""
    _write_limiter.reset()


def rate_limit_writes(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> None:
    """Throttle write requests per client address."""
    client = request.client.host if request.client else "unknown"
    allowed = _write_limiter.allow(
        client,
        settings.write_rate_limit,
        settings.write_rate_window_seconds,
        time.monotonic(),
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="too many write requests; slow down",
            headers={"Retry-After": str(int(settings.write_rate_window_seconds))},
        )
