"""Books to Scrape product scraper.

`books.toscrape.com <https://books.toscrape.com>`_ is a public sandbox
bookstore built for scraping practice: real product-page markup (price, stock
count, star rating, UPC table, category breadcrumb) with no anti-bot layer and
no terms that forbid automated access. That makes it the store to point
``live`` mode at when a demo has to fetch real pages over the network.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup, NavigableString, Tag

from .base import BaseScraper, ProductData
from .registry import register

# Product pages live at /catalogue/<slug>_<id>/index.html. The "<slug>_<id>"
# segment is unique per book, so it doubles as the external id. Category pages
# (/catalogue/category/...) deliberately do not match.
_PRODUCT_RE = re.compile(r"/catalogue/([a-z0-9-]+_\d+)/", re.I)
_AVAILABLE_RE = re.compile(r"\((\d+)\s+available\)", re.I)

# The star rating is a CSS class ("star-rating Three"), not text.
_STARS = {"one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0}
_CURRENCIES = {"£": "GBP", "$": "USD", "€": "EUR"}


@register
class BooksToScrapeScraper(BaseScraper):
    store_slug = "bookstoscrape"
    store_name = "Books to Scrape"
    base_url = "https://books.toscrape.com"
    domains = ("books.toscrape.com",)

    def extract_external_id(self, url: str) -> str:
        m = _PRODUCT_RE.search(url)
        if m:
            return m.group(1).lower()
        # Fall back to a stable slug so fixture lookups still work in demos.
        cleaned = re.sub(r"[^A-Za-z0-9]+", "-", url).strip("-")
        return cleaned[-32:] or "unknown"

    # -- parsing -----------------------------------------------------------
    def parse(self, html: str, url: str) -> ProductData:
        soup = BeautifulSoup(html, "html.parser")
        main = soup.select_one(".product_main")

        data = ProductData(
            external_id=self.extract_external_id(url),
            url=url,
            store_slug=self.store_slug,
        )
        data.title = self._text(main.select_one("h1") if main else None) or ""
        price_text = self._text(main.select_one(".price_color") if main else None)
        data.price = self._parse_price(price_text)
        data.currency = self._parse_currency(price_text)
        table = self._product_table(soup)
        data.in_stock, available = self._parse_availability(
            self._text(main.select_one(".availability") if main else None)
            or table.get("Availability")
        )
        data.rating = self._parse_rating(main)
        data.review_count = self._parse_int(table.get("Number of reviews"))
        data.image_url = self._parse_image(soup, url)

        specs = dict(table)
        category = self._parse_category(soup)
        if category:
            specs["Category"] = category
        if available is not None:
            specs["Units available"] = str(available)
        data.specs = specs
        return data

    # -- field extractors --------------------------------------------------
    def _product_table(self, soup: BeautifulSoup) -> dict[str, str]:
        table: dict[str, str] = {}
        for row in soup.select("table.table tr"):
            key = self._text(row.select_one("th"))
            val = self._text(row.select_one("td"))
            if key and val:
                table[key] = val
        return table

    @staticmethod
    def _parse_currency(price_text: str | None) -> str:
        for symbol, code in _CURRENCIES.items():
            if price_text and symbol in price_text:
                return code
        return "GBP"  # the store prices everything in pounds

    @staticmethod
    def _parse_availability(text: str | None) -> tuple[bool, int | None]:
        if not text:
            return False, None
        m = _AVAILABLE_RE.search(text)
        available = int(m.group(1)) if m else None
        in_stock = "in stock" in text.lower() and available != 0
        return in_stock, available

    @staticmethod
    def _parse_rating(main: Tag | None) -> float | None:
        el = main.select_one(".star-rating") if main else None
        if el is None:
            return None
        classes = el.get("class") or []
        for cls in classes if isinstance(classes, list) else [classes]:
            if cls.lower() in _STARS:
                return _STARS[cls.lower()]
        return None

    def _parse_image(self, soup: BeautifulSoup, url: str) -> str | None:
        el = soup.select_one("#product_gallery img")
        src = el.get("src") if isinstance(el, Tag) else None
        # Image paths are relative ("../../media/..."), so resolve them
        # against the page URL to get something a browser can load.
        return urljoin(url, src) if isinstance(src, str) and src else None

    def _parse_category(self, soup: BeautifulSoup) -> str | None:
        # Home > Books > <Category> > <Title>: the category is the last link.
        links = [t for a in soup.select("ul.breadcrumb li a") if (t := self._text(a))]
        return links[-1] if len(links) >= 3 else None

    # -- utils -------------------------------------------------------------
    @staticmethod
    def _text(node: Tag | NavigableString | None) -> str | None:
        if node is None:
            return None
        text = node.get_text(" ", strip=True)
        return text or None
