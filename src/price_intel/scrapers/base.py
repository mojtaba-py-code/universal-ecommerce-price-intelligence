"""Scraper plugin interface.

Every store scraper subclasses :class:`BaseScraper` and implements three things:

* ``store_slug`` / ``store_name`` - identity of the store.
* :meth:`can_handle`  - does this scraper understand a given URL?
* :meth:`extract_external_id` - pull the store's product id from the URL.
* :meth:`parse` - turn raw HTML into a normalized :class:`ProductData`.

Fetching (network vs. saved fixture) is handled once in the base class so
concrete scrapers only ever deal with parsing. This is the seam that lets the
project run identically online (`live`) and offline (`fixture`).
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from ..config import ScraperMode, get_settings
from ..security import UnsafeUrlError, domain_matches, ensure_public_url

# A realistic desktop browser fingerprint. Live scraping without this is
# rejected almost immediately by most stores.
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Redirect handling for live fetches. Each hop is re-validated, so the cap is
# about bounding work, not safety.
_MAX_REDIRECTS = 5
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


@dataclass
class ProductData:
    """Normalized product record produced by a scraper.

    Prices are kept in major units (e.g. dollars) here; the persistence layer
    converts to integer minor units when storing.
    """

    external_id: str
    url: str
    store_slug: str
    title: str = ""
    brand: str | None = None
    image_url: str | None = None
    price: float | None = None
    currency: str = "USD"
    in_stock: bool = True
    discount_percent: float | None = None
    rating: float | None = None
    review_count: int | None = None
    specs: dict[str, str] = field(default_factory=dict)


class ScraperError(RuntimeError):
    """Raised when a page cannot be fetched or parsed."""


class BlockedError(ScraperError):
    """Raised when the store returns an anti-bot / CAPTCHA challenge."""


class BaseScraper(ABC):
    """Base class for all store scrapers."""

    store_slug: str = ""
    store_name: str = ""
    base_url: str = ""
    #: Registrable domains this scraper serves, e.g. ``("amazon.com",)``. The
    #: default :meth:`can_handle` matches the parsed hostname against these.
    domains: tuple[str, ...] = ()

    # -- identity ----------------------------------------------------------
    def can_handle(self, url: str) -> bool:
        """Return True if ``url``'s hostname belongs to this scraper's store.

        Hostname matching — not a substring search over the whole URL — is what
        keeps this from doubling as an SSRF entry point: the URL reaches
        :meth:`_fetch_live` only if a scraper claims it, so a loose claim is an
        open redirect into the deployment's own network.
        """
        return domain_matches(url, self.domains)

    @abstractmethod
    def extract_external_id(self, url: str) -> str:
        """Extract the store-specific product id (e.g. ASIN) from ``url``."""

    # -- parsing -----------------------------------------------------------
    @abstractmethod
    def parse(self, html: str, url: str) -> ProductData:
        """Parse raw HTML into a :class:`ProductData`."""

    # -- fetching (shared) -------------------------------------------------
    def fetch(self, url: str) -> str:
        """Return raw HTML for ``url`` according to the configured mode."""
        settings = get_settings()
        if settings.scraper_mode is ScraperMode.FIXTURE:
            return self._read_fixture(url)
        return self._fetch_live(url)

    def scrape(self, url: str) -> ProductData:
        """Full pipeline: fetch then parse."""
        html = self.fetch(url)
        return self.parse(html, url)

    # -- fetch backends ----------------------------------------------------
    def _fetch_live(self, url: str) -> str:
        settings = get_settings()

        # The URL originates from an API caller, so it is validated immediately
        # before the socket opens rather than at the edge, where a later
        # refactor could route around the check.
        try:
            target = ensure_public_url(url)
        except UnsafeUrlError as exc:
            raise ScraperError(f"refusing to fetch {url}: {exc}") from exc

        # Be a polite citizen: throttle before each live request.
        if settings.request_delay_seconds > 0:
            time.sleep(settings.request_delay_seconds)

        # Redirects are followed by hand so that every hop is re-validated.
        # `follow_redirects=True` would let an attacker-controlled 302 carry the
        # request from a public store domain to a private address, which is the
        # standard way an SSRF guard gets bypassed.
        try:
            for _hop in range(_MAX_REDIRECTS + 1):
                resp = httpx.get(
                    target,
                    headers=_DEFAULT_HEADERS,
                    timeout=settings.request_timeout_seconds,
                    follow_redirects=False,
                )
                if resp.status_code not in _REDIRECT_STATUSES:
                    break
                location = resp.headers.get("location")
                if not location:
                    break
                next_url = str(resp.url.join(location))
                try:
                    target = ensure_public_url(next_url)
                except UnsafeUrlError as exc:
                    raise ScraperError(f"refusing to follow redirect to {next_url}: {exc}") from exc
            else:
                raise ScraperError(f"too many redirects fetching {url}")
        except httpx.HTTPError as exc:  # network-level failure
            raise ScraperError(f"network error fetching {url}: {exc}") from exc

        if resp.status_code in (503, 429) or "captcha" in resp.text.lower():
            raise BlockedError(
                f"{self.store_name} returned an anti-bot challenge "
                f"(status={resp.status_code}). Try 'fixture' mode or slow down."
            )
        if resp.status_code >= 400:
            raise ScraperError(f"HTTP {resp.status_code} fetching {url}")
        return resp.text

    def _read_fixture(self, url: str) -> str:
        """Load a saved HTML fixture for ``url``.

        Resolution order (first hit wins):
          1. ``<fixture_dir>/<slug>/<external_id>.html``
          2. ``<fixture_dir>/<slug>/default.html``
        """
        settings = get_settings()
        external_id = self.extract_external_id(url)
        store_dir = settings.fixture_path / self.store_slug
        candidates = [store_dir / f"{external_id}.html", store_dir / "default.html"]
        for path in candidates:
            if path.is_file():
                return path.read_text(encoding="utf-8")
        searched = ", ".join(str(p) for p in candidates)
        raise ScraperError(
            f"no fixture found for {url} (looked in: {searched}). "
            f"Add an HTML file or switch SCRAPER_MODE=live."
        )

    # -- small parsing helpers shared by subclasses ------------------------
    @staticmethod
    def _parse_price(text: str | None) -> float | None:
        """Extract a float price from noisy text like '$1,299.00' / '€ 49,90'."""
        if not text:
            return None
        cleaned = (
            text.replace("\xa0", " ")
            .strip()
            .replace(",", "")  # thousands separators (handles the common US form)
        )
        num = ""
        seen_dot = False
        for ch in cleaned:
            if ch.isdigit():
                num += ch
            elif ch == "." and not seen_dot:
                num += ch
                seen_dot = True
        try:
            return round(float(num), 2) if num not in ("", ".") else None
        except ValueError:
            return None

    @staticmethod
    def _parse_int(text: str | None) -> int | None:
        """Extract an integer from text like '1,234 ratings'."""
        if not text:
            return None
        digits = "".join(ch for ch in text if ch.isdigit())
        return int(digits) if digits else None
