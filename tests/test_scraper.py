"""Tests for the scraper layer: registry, URL handling, and Amazon parsing."""

from __future__ import annotations

import pytest

from price_intel.scrapers.amazon import AmazonScraper
from price_intel.scrapers.registry import get_scraper_for_url


def test_registry_resolves_amazon():
    scraper = get_scraper_for_url("https://www.amazon.com/dp/B08N5WRWNW")
    assert isinstance(scraper, AmazonScraper)


def test_registry_rejects_unknown_store():
    with pytest.raises(ValueError):
        get_scraper_for_url("https://example.com/product/123")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.amazon.com/dp/B08N5WRWNW", "B08N5WRWNW"),
        ("https://www.amazon.com/gp/product/B09XS7JWHH/ref=x", "B09XS7JWHH"),
        ("https://www.amazon.co.uk/Some-Title/dp/B000123ABC?th=1", "B000123ABC"),
    ],
)
def test_extract_asin(url, expected):
    assert AmazonScraper().extract_external_id(url) == expected


def test_parse_default_fixture():
    scraper = AmazonScraper()
    data = scraper.scrape("https://www.amazon.com/dp/B09XS7JWHH")  # -> default.html

    assert "Sony" in data.title
    assert data.brand == "Sony"
    assert data.price == 328.00
    assert data.currency == "USD"
    assert data.in_stock is True
    assert data.rating == 4.6
    assert data.review_count == 3254
    assert data.discount_percent == 18.0
    assert data.image_url and data.image_url.startswith("https://")
    assert data.specs.get("Brand") == "Sony"
    assert "highlights" in data.specs


def test_parse_specific_asin_fixture():
    scraper = AmazonScraper()
    data = scraper.scrape("https://www.amazon.com/dp/B08N5WRWNW")  # -> Echo Dot fixture

    assert "Echo Dot" in data.title
    assert data.price == 49.99
    assert data.review_count == 421908
    assert data.brand == "Amazon"


def test_price_and_int_helpers():
    assert AmazonScraper._parse_price("$1,299.00") == 1299.00
    assert AmazonScraper._parse_price("  ") is None
    assert AmazonScraper._parse_int("1,234 ratings") == 1234
    assert AmazonScraper._parse_int(None) is None
