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
from pathlib import Path

import httpx

from ..config import ScraperMode, get_settings

# A realistic desktop browser fingerprint. Live scraping without this is
# rejected almost immediately by most stores.
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
        "image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


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

    # -- identity ----------------------------------------------------------
    @abstractmethod
    def can_handle(self, url: str) -> bool:
        """Return True if this scraper knows how to handle ``url``."""

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
        # Be a polite citizen: throttle before each live request.
        if settings.request_delay_seconds > 0:
            time.sleep(settings.request_delay_seconds)
        try:
            resp = httpx.get(
                url,
                headers=_DEFAULT_HEADERS,
                timeout=settings.request_timeout_seconds,
                follow_redirects=True,
            )
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
