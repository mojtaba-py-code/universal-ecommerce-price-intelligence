"""Tests for the scraper layer: registry, URL handling, and store parsing."""

from __future__ import annotations

import pytest

from price_intel.scrapers.amazon import AmazonScraper
from price_intel.scrapers.books_toscrape import BooksToScrapeScraper
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


# -- Books to Scrape (public scraping sandbox) --------------------------------

BOOK_URL = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"


def test_registry_resolves_books_to_scrape():
    assert isinstance(get_scraper_for_url(BOOK_URL), BooksToScrapeScraper)


@pytest.mark.parametrize(
    "url",
    [
        "https://books.toscrape.com.attacker.example/catalogue/x_1/index.html",
        "https://toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
        "http://169.254.169.254/?books.toscrape.com",
    ],
)
def test_books_lookalike_hosts_are_not_claimed(url):
    with pytest.raises(ValueError):
        get_scraper_for_url(url)


@pytest.mark.parametrize(
    "url,expected",
    [
        (BOOK_URL, "a-light-in-the-attic_1000"),
        ("http://books.toscrape.com/catalogue/Sapiens_996/", "sapiens_996"),
    ],
)
def test_extract_book_id(url, expected):
    assert BooksToScrapeScraper().extract_external_id(url) == expected


def test_category_pages_are_not_read_as_products():
    url = "https://books.toscrape.com/catalogue/category/books/poetry_23/index.html"
    assert BooksToScrapeScraper().extract_external_id(url) != "poetry_23"


def test_parse_book_fixture():
    data = BooksToScrapeScraper().scrape(BOOK_URL)

    assert data.title == "A Light in the Attic"
    assert data.price == 51.77
    assert data.currency == "GBP"
    assert data.in_stock is True
    assert data.rating == 3.0
    assert data.review_count == 0
    assert data.image_url == (
        "https://books.toscrape.com/media/cache/fe/72/fe72f0532301ec28892ae79a629a293c.jpg"
    )
    assert data.specs["UPC"] == "a897fe39b1053632"
    assert data.specs["Category"] == "Poetry"
    assert data.specs["Units available"] == "22"


@pytest.mark.parametrize(
    "availability,in_stock",
    [("In stock (3 available)", True), ("In stock (0 available)", False), ("Out of stock", False)],
)
def test_book_availability(availability, in_stock):
    html = (
        '<div class="product_main"><h1>T</h1><p class="price_color">£9.99</p>'
        f'<p class="availability">{availability}</p><p class="star-rating Five"></p></div>'
    )
    data = BooksToScrapeScraper().parse(html, BOOK_URL)
    assert data.in_stock is in_stock
    assert (data.price, data.rating) == (9.99, 5.0)
    assert data.image_url is None and "Category" not in data.specs
