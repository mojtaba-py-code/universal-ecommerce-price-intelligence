"""Seed the database with demo products and a realistic price history.

This is purely for demonstration: it scrapes the bundled fixtures once to create
the products, then backfills ~30 days of synthetic price snapshots so the
dashboard charts and analytics have something to show immediately.

    python seed_demo.py

Safe to re-run: it clears existing demo products first.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from price_intel.db import init_db, session_scope
from price_intel.models import PriceChange, PriceSnapshot, Product
from price_intel.pipeline import track
from price_intel.scrapers import get_scraper_for_url

# Fixture-backed demo URLs (resolved via the bundled HTML in data/fixtures).
DEMO_URLS = [
    "https://www.amazon.com/dp/B09XS7JWHH",   # -> default.html (Sony headphones)
    "https://www.amazon.com/dp/B08N5WRWNW",   # -> Echo Dot fixture
    # Books to Scrape is a public sandbox store, so these two can also be
    # tracked live (SCRAPER_MODE=live) without fighting an anti-bot layer.
    "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html",
    "https://books.toscrape.com/catalogue/sapiens-a-brief-history-of-humankind_996/index.html",
]

# A believable 30-day price path per product (in the product's currency),
# ending at "today", i.e. at the price on the bundled page.
PRICE_PATHS = {
    "B09XS7JWHH": [399.99, 399.99, 379.99, 379.99, 359.00, 359.00, 348.00,
                   348.00, 348.00, 329.99, 329.99, 329.99, 318.00, 318.00,
                   309.99, 309.99, 328.00, 328.00, 348.00, 348.00, 339.00,
                   339.00, 329.00, 329.00, 319.99, 319.99, 309.00, 299.99,
                   299.99, 328.00],
    "B08N5WRWNW": [59.99, 59.99, 54.99, 54.99, 49.99, 49.99, 49.99, 44.99,
                   39.99, 39.99, 44.99, 49.99, 49.99, 49.99, 34.99, 29.99,
                   29.99, 34.99, 39.99, 44.99, 49.99, 49.99, 49.99, 49.99,
                   54.99, 54.99, 52.99, 49.99, 49.99, 49.99],
    "a-light-in-the-attic_1000": [
        59.99, 59.99, 57.50, 57.50, 54.99, 54.99, 54.99, 52.49, 52.49, 49.99,
        49.99, 47.99, 47.99, 49.99, 49.99, 52.49, 52.49, 54.99, 54.99, 53.25,
        53.25, 51.77, 51.77, 49.50, 49.50, 49.50, 51.77, 51.77, 51.77, 51.77],
    "sapiens-a-brief-history-of-humankind_996": [
        49.99, 49.99, 49.99, 52.50, 52.50, 54.23, 54.23, 56.99, 56.99, 58.40,
        58.40, 58.40, 55.75, 55.75, 52.99, 52.99, 49.99, 49.99, 47.50, 47.50,
        49.99, 49.99, 52.10, 52.10, 54.23, 54.23, 54.23, 53.00, 54.23, 54.23],
}


def _clear_demo(session) -> None:
    for url in DEMO_URLS:
        external_id = get_scraper_for_url(url).extract_external_id(url)
        prod = session.scalar(select(Product).where(Product.external_id == external_id))
        if prod:
            session.delete(prod)
    session.flush()


def _backfill(session, product: Product, path: list[float], scraped: PriceSnapshot) -> None:
    """Replace snapshots with a synthetic daily history and record changes."""
    # Amazon pages get a small deterministic rating/review drift for realism;
    # other stores keep the rating and review count their page actually shows.
    drift = product.store.slug == "amazon"
    # Read these before the bulk delete below removes the scraped row.
    base_rating, base_reviews, in_stock = scraped.rating, scraped.review_count, scraped.in_stock
    session.query(PriceSnapshot).filter(PriceSnapshot.product_id == product.id).delete()
    session.query(PriceChange).filter(PriceChange.product_id == product.id).delete()
    session.flush()

    start = datetime.now(timezone.utc) - timedelta(days=len(path) - 1)
    prev_minor: int | None = None
    for i, price in enumerate(path):
        minor = int(round(price * 100))
        when = start + timedelta(days=i)
        rating = round(4.4 + 0.2 * math.sin(i / 4), 2) if drift else base_rating
        review_count = 3000 + i * 7 if drift else base_reviews
        session.add(PriceSnapshot(
            product_id=product.id, price_minor=minor, currency=product.currency,
            in_stock=in_stock, rating=rating, review_count=review_count,
            scraped_at=when,
        ))
        if prev_minor is not None and prev_minor != minor:
            delta = minor - prev_minor
            session.add(PriceChange(
                product_id=product.id, old_price_minor=prev_minor, new_price_minor=minor,
                change_minor=delta, change_percent=round(delta / prev_minor * 100, 2),
                direction="up" if delta > 0 else "down", detected_at=when,
            ))
        prev_minor = minor


def main() -> None:
    init_db()
    with session_scope() as session:
        _clear_demo(session)
        for url in DEMO_URLS:
            result = track(session, url)
            external_id = result.product.external_id
            if external_id in PRICE_PATHS:
                path = PRICE_PATHS[external_id]
                _backfill(session, result.product, path, result.snapshot)
                print(f"seeded #{result.product.id} {result.product.title[:50]!r} "
                      f"with {len(path)} days of history")
    print("Done. Run:  python -m price_intel.cli serve   (or: uvicorn price_intel.api.main:app)")


if __name__ == "__main__":
    main()
