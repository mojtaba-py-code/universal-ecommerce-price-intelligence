"""Amazon product scraper.

Uses the *real* Amazon DOM selectors (product title, price blocks, byline,
rating widget, availability, feature bullets, detail tables). Runs identically
against a live page or a saved fixture - only :meth:`BaseScraper.fetch` differs.

Note on live scraping: Amazon actively fights automated access with rotating
markup and anti-bot challenges. This parser is defensive (it tries several
selector variants and degrades gracefully), but no scraper can guarantee a live
page will not be served as a CAPTCHA. That is exactly why `fixture` mode exists.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .base import BaseScraper, ProductData
from .registry import register

# Matches ASINs in the common Amazon URL shapes: /dp/ASIN, /gp/product/ASIN, ...
_ASIN_RE = re.compile(r"/(?:dp|gp/product|gp/aw/d|product)/([A-Z0-9]{10})", re.IGNORECASE)
_ASIN_QUERY_RE = re.compile(r"[?&]asin=([A-Z0-9]{10})", re.IGNORECASE)


@register
class AmazonScraper(BaseScraper):
    store_slug = "amazon"
    store_name = "Amazon"
    base_url = "https://www.amazon.com"

    # -- identity ----------------------------------------------------------
    def can_handle(self, url: str) -> bool:
        return "amazon." in url.lower()

    def extract_external_id(self, url: str) -> str:
        for pattern in (_ASIN_RE, _ASIN_QUERY_RE):
            m = pattern.search(url)
            if m:
                return m.group(1).upper()
        # Fall back to a stable slug so fixture lookups still work in demos.
        cleaned = re.sub(r"[^A-Za-z0-9]+", "-", url).strip("-")
        return cleaned[-32:] or "unknown"

    # -- parsing -----------------------------------------------------------
    def parse(self, html: str, url: str) -> ProductData:
        soup = BeautifulSoup(html, "html.parser")

        data = ProductData(
            external_id=self.extract_external_id(url),
            url=url,
            store_slug=self.store_slug,
        )
        data.title = self._text(soup.select_one("#productTitle")) or ""
        data.brand = self._parse_brand(soup)
        data.price = self._parse_price(self._price_text(soup))
        data.currency = self._parse_currency(soup)
        data.in_stock = self._parse_in_stock(soup)
        data.rating = self._parse_rating(soup)
        data.review_count = self._parse_int(
            self._text(soup.select_one("#acrCustomerReviewText"))
        )
        data.image_url = self._parse_image(soup)
        data.specs = self._parse_specs(soup)
        data.discount_percent = self._parse_discount(soup)
        return data

    # -- field extractors --------------------------------------------------
    def _price_text(self, soup: BeautifulSoup) -> str | None:
        # Amazon exposes the price in a hidden ".a-offscreen" span inside the
        # buy box. Several ids/containers exist depending on the page variant.
        selectors = [
            "#corePrice_feature_div .a-price .a-offscreen",
            "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
            "#priceblock_ourprice",
            "#priceblock_dealprice",
            "span.a-price span.a-offscreen",
        ]
        for sel in selectors:
            el = soup.select_one(sel)
            if el and el.get_text(strip=True):
                return el.get_text(strip=True)
        return None

    def _parse_currency(self, soup: BeautifulSoup) -> str:
        symbol = self._text(soup.select_one("span.a-price-symbol"))
        return {"$": "USD", "£": "GBP", "€": "EUR", "₹": "INR"}.get(symbol or "$", "USD")

    def _parse_brand(self, soup: BeautifulSoup) -> str | None:
        byline = self._text(soup.select_one("#bylineInfo"))
        if byline:
            # "Visit the Sony Store" / "Brand: Sony"
            byline = re.sub(r"^(Visit the|Brand:)\s*", "", byline, flags=re.IGNORECASE)
            byline = re.sub(r"\s*Store$", "", byline, flags=re.IGNORECASE)
            if byline.strip():
                return byline.strip()
        # Product-details table sometimes carries an explicit "Brand" row.
        for row in soup.select("#productDetails_techSpec_section_1 tr, tr"):
            header = self._text(row.select_one("th"))
            if header and header.strip().lower() == "brand":
                return self._text(row.select_one("td"))
        return None

    def _parse_in_stock(self, soup: BeautifulSoup) -> bool:
        availability = self._text(soup.select_one("#availability"))
        if not availability:
            # If there is an add-to-cart button, assume it is buyable.
            return soup.select_one("#add-to-cart-button") is not None
        text = availability.lower()
        out_markers = ("unavailable", "out of stock", "currently unavailable")
        return not any(marker in text for marker in out_markers)

    def _parse_rating(self, soup: BeautifulSoup) -> float | None:
        # e.g. "4.6 out of 5 stars"
        el = soup.select_one("#acrPopover span.a-icon-alt") or soup.select_one(
            "span[data-hook='rating-out-of-text']"
        )
        text = self._text(el)
        if not text:
            title = soup.select_one("#acrPopover")
            text = title.get("title") if title and title.has_attr("title") else None
        if text:
            m = re.search(r"([0-9]+(?:\.[0-9]+)?)", text)
            if m:
                return float(m.group(1))
        return None

    def _parse_image(self, soup: BeautifulSoup) -> str | None:
        el = soup.select_one("#landingImage") or soup.select_one("#imgTagWrapperId img")
        if el is None:
            return None
        return el.get("src") or el.get("data-old-hires") or None

    def _parse_discount(self, soup: BeautifulSoup) -> float | None:
        text = self._text(soup.select_one(".savingsPercentage")) or self._text(
            soup.select_one("span.a-color-price")
        )
        if text and "%" in text:
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
            if m:
                return abs(float(m.group(1)))
        return None

    def _parse_specs(self, soup: BeautifulSoup) -> dict[str, str]:
        specs: dict[str, str] = {}
        # Feature bullets.
        bullets = [
            self._text(li)
            for li in soup.select("#feature-bullets ul li span.a-list-item")
        ]
        bullets = [b for b in bullets if b]
        if bullets:
            specs["highlights"] = " | ".join(bullets[:8])
        # Detail tables (technical + additional info).
        for row in soup.select(
            "#productDetails_techSpec_section_1 tr, "
            "#productDetails_detailBullets_sections1 tr"
        ):
            key = self._text(row.select_one("th"))
            val = self._text(row.select_one("td"))
            if key and val:
                specs[key.strip()] = re.sub(r"\s+", " ", val).strip()
        return specs

    # -- utils -------------------------------------------------------------
    @staticmethod
    def _text(node) -> str | None:
        if node is None:
            return None
        text = node.get_text(" ", strip=True)
        return text or None
