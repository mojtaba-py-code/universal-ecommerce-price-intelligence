"""Tests for the SSRF guard, domain matching and API access control."""

from __future__ import annotations

import pytest

from price_intel.scrapers.amazon import AmazonScraper
from price_intel.scrapers.registry import get_scraper_for_url
from price_intel.security import (
    UnsafeUrlError,
    domain_matches,
    ensure_public_url,
    ip_is_public,
)

# Hosts that a naive `"amazon." in url` substring test would happily accept.
SUBSTRING_TRAPS = [
    "http://169.254.169.254/latest/meta-data/?store=amazon.com",
    "http://127.0.0.1:8000/amazon.com/dp/B08N5WRWNW",
    "https://amazon.com.attacker.example/dp/B08N5WRWNW",
    "https://notamazon.com/dp/B08N5WRWNW",
    "https://evil.example/?redirect=https://amazon.com",
    "http://10.0.0.5/amazon./dp/B08N5WRWNW",
]


@pytest.mark.parametrize("url", SUBSTRING_TRAPS)
def test_can_handle_rejects_substring_lookalikes(url):
    assert AmazonScraper().can_handle(url) is False


@pytest.mark.parametrize("url", SUBSTRING_TRAPS)
def test_registry_rejects_substring_lookalikes(url):
    with pytest.raises(ValueError):
        get_scraper_for_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.amazon.com/dp/B08N5WRWNW",
        "https://amazon.com/dp/B08N5WRWNW",
        "https://www.amazon.co.uk/Some-Title/dp/B000123ABC",
        "https://smile.amazon.de/dp/B000123ABC",
        "https://WWW.AMAZON.COM/dp/B08N5WRWNW",
    ],
)
def test_can_handle_accepts_real_marketplaces(url):
    assert AmazonScraper().can_handle(url) is True


def test_domain_matches_ignores_trailing_dot():
    assert domain_matches("https://www.amazon.com./dp/X", ("amazon.com",)) is True


def test_domain_matches_requires_a_host():
    assert domain_matches("not a url", ("amazon.com",)) is False


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",  # cloud instance metadata
        "0.0.0.0",  # noqa: S104 - an address under test, not a bind target
        "::1",
        "fd00::1",
        "fe80::1",
        "224.0.0.1",
        "not-an-ip",
    ],
)
def test_ip_is_public_rejects_non_routable(address):
    assert ip_is_public(address) is False


@pytest.mark.parametrize("address", ["8.8.8.8", "1.1.1.1", "2606:4700:4700::1111"])
def test_ip_is_public_accepts_routable(address):
    assert ip_is_public(address) is True


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "gopher://127.0.0.1:11211/",
        "ftp://example.com/x",
    ],
)
def test_ensure_public_url_rejects_other_schemes(url):
    with pytest.raises(UnsafeUrlError):
        ensure_public_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://10.1.2.3/",
        "http://192.168.0.1:8080/admin",
    ],
)
def test_ensure_public_url_rejects_literal_private_addresses(url):
    """Literal addresses are checked without a DNS round-trip, so this is offline."""
    with pytest.raises(UnsafeUrlError):
        ensure_public_url(url)


def test_ensure_public_url_rejects_hostless_url():
    with pytest.raises(UnsafeUrlError):
        ensure_public_url("http:///nowhere")


def test_ensure_public_url_accepts_literal_public_address():
    assert ensure_public_url("https://8.8.8.8/") == "https://8.8.8.8/"


def test_ensure_public_url_rejects_resolved_private_address(monkeypatch):
    """A public-looking name that resolves inward is still refused."""
    monkeypatch.setattr(
        "price_intel.security.resolve_host",
        lambda host, port: ["93.184.216.34", "127.0.0.1"],
    )
    with pytest.raises(UnsafeUrlError, match="non-public"):
        ensure_public_url("https://rebind.example/")


def test_ensure_public_url_accepts_fully_public_resolution(monkeypatch):
    monkeypatch.setattr("price_intel.security.resolve_host", lambda host, port: ["93.184.216.34"])
    assert ensure_public_url("https://example.test/x") == "https://example.test/x"


# -- API access control ----------------------------------------------------


def test_writes_allowed_without_key_in_fixture_mode(client):
    r = client.post("/api/track", json={"url": "https://www.amazon.com/dp/B08N5WRWNW"})
    assert r.status_code == 200


def test_writes_rejected_without_key_in_live_mode(db, monkeypatch):
    from fastapi.testclient import TestClient

    from price_intel import config
    from price_intel.api.main import create_app

    monkeypatch.setenv("SCRAPER_MODE", "live")
    config._settings = None
    with TestClient(create_app()) as c:
        r = c.post("/api/track", json={"url": "https://www.amazon.com/dp/B08N5WRWNW"})
    config._settings = None
    assert r.status_code == 503
    assert "API_KEY" in r.json()["detail"]


def test_write_rejected_with_wrong_key(api_key, db):
    from fastapi.testclient import TestClient

    from price_intel.api.main import create_app

    with TestClient(create_app()) as c:
        r = c.post(
            "/api/track",
            json={"url": "https://www.amazon.com/dp/B08N5WRWNW"},
            headers={"X-API-Key": "wrong"},
        )
    assert r.status_code == 401


def test_write_rejected_with_missing_key(api_key, db):
    from fastapi.testclient import TestClient

    from price_intel.api.main import create_app

    with TestClient(create_app()) as c:
        r = c.post("/api/track", json={"url": "https://www.amazon.com/dp/B08N5WRWNW"})
    assert r.status_code == 401


def test_reads_stay_open_without_a_key(client):
    assert client.get("/api/products").status_code == 200
    assert client.get("/api/stores").status_code == 200
    assert client.get("/health").status_code == 200


def test_write_rate_limit_returns_429(client, monkeypatch):
    from price_intel import config

    monkeypatch.setenv("WRITE_RATE_LIMIT", "3")
    config._settings = None

    url = "https://www.amazon.com/dp/B08N5WRWNW"
    codes = [client.post("/api/track", json={"url": url}).status_code for _ in range(5)]
    config._settings = None

    assert codes[:3] == [200, 200, 200]
    assert codes[-1] == 429


def test_security_headers_present(client):
    headers = client.get("/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in headers["Content-Security-Policy"]


# -- live fetching ---------------------------------------------------------


@pytest.fixture()
def live_mode(monkeypatch):
    """Switch the scraper to live mode without any request delay."""
    from price_intel import config

    monkeypatch.setenv("SCRAPER_MODE", "live")
    monkeypatch.setenv("REQUEST_DELAY_SECONDS", "0")
    config._settings = None
    yield
    config._settings = None


class _FakeResponse:
    def __init__(self, url, status_code=200, location=None, text="<html>ok</html>"):
        import httpx

        self.url = httpx.URL(url)
        self.status_code = status_code
        self.headers = {"location": location} if location else {}
        self.text = text


def _fake_get(routes):
    """Build an ``httpx.get`` replacement that serves ``routes`` and records calls."""
    calls: list[str] = []

    def _get(url, **_kwargs):
        calls.append(str(url))
        return routes[str(url)]

    return _get, calls


def test_live_fetch_refuses_private_target(live_mode, monkeypatch):
    from price_intel.scrapers.base import ScraperError

    monkeypatch.setattr("price_intel.security.resolve_host", lambda host, port: ["127.0.0.1"])
    with pytest.raises(ScraperError, match="refusing to fetch"):
        AmazonScraper().fetch("https://www.amazon.com/dp/B08N5WRWNW")


def test_live_fetch_refuses_redirect_into_private_space(live_mode, monkeypatch):
    """A public store URL must not be able to bounce the fetch inward."""
    from price_intel.scrapers.base import ScraperError

    start = "https://www.amazon.com/dp/B08N5WRWNW"
    monkeypatch.setattr("price_intel.security.resolve_host", lambda host, port: ["93.184.216.34"])
    get, calls = _fake_get(
        {start: _FakeResponse(start, status_code=302, location="http://169.254.169.254/")}
    )
    monkeypatch.setattr("price_intel.scrapers.base.httpx.get", get)

    with pytest.raises(ScraperError, match="refusing to follow redirect"):
        AmazonScraper().fetch(start)
    # The metadata endpoint was never contacted.
    assert calls == [start]


def test_live_fetch_follows_public_redirect(live_mode, monkeypatch):
    start = "https://www.amazon.com/dp/B08N5WRWNW"
    final = "https://www.amazon.com/dp/B08N5WRWNW/ref=canonical"
    monkeypatch.setattr("price_intel.security.resolve_host", lambda host, port: ["93.184.216.34"])
    get, calls = _fake_get(
        {
            start: _FakeResponse(start, status_code=301, location=final),
            final: _FakeResponse(final, text="<html>final</html>"),
        }
    )
    monkeypatch.setattr("price_intel.scrapers.base.httpx.get", get)

    assert AmazonScraper().fetch(start) == "<html>final</html>"
    assert calls == [start, final]


def test_live_fetch_stops_after_too_many_redirects(live_mode, monkeypatch):
    from price_intel.scrapers.base import ScraperError

    url = "https://www.amazon.com/dp/B08N5WRWNW"
    monkeypatch.setattr("price_intel.security.resolve_host", lambda host, port: ["93.184.216.34"])
    get, calls = _fake_get({url: _FakeResponse(url, status_code=302, location=url)})
    monkeypatch.setattr("price_intel.scrapers.base.httpx.get", get)

    with pytest.raises(ScraperError, match="too many redirects"):
        AmazonScraper().fetch(url)
    assert len(calls) == 6  # _MAX_REDIRECTS + 1
