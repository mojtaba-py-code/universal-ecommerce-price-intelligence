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

# Fixture-backed demo URLs (resolved via the bundled HTML in data/fixtures).
DEMO_URLS = [
    "https://www.amazon.com/dp/B09XS7JWHH",   # -> default.html (Sony headphones)
    "https://www.amazon.com/dp/B08N5WRWNW",   # -> Echo Dot fixture
]

# A believable 30-day price path (in dollars) per product, ending at "today".
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
}


def _clear_demo(session) -> None:
    for url in DEMO_URLS:
        asin = url.rsplit("/", 1)[-1]
        prod = session.scalar(select(Product).where(Product.external_id == asin))
        if prod:
            session.delete(prod)
    session.flush()


def _backfill(session, product: Product, path: list[float]) -> None:
    """Replace snapshots with a synthetic daily history and record changes."""
    session.query(PriceSnapshot).filter(PriceSnapshot.product_id == product.id).delete()
    session.query(PriceChange).filter(PriceChange.product_id == product.id).delete()
    session.flush()

    start = datetime.now(timezone.utc) - timedelta(days=len(path) - 1)
    prev_minor: int | None = None
    for i, price in enumerate(path):
        minor = int(round(price * 100))
        when = start + timedelta(days=i)
        # small deterministic rating drift for realism
        rating = round(4.4 + 0.2 * math.sin(i / 4), 2)
        session.add(PriceSnapshot(
            product_id=product.id, price_minor=minor, currency=product.currency,
            in_stock=True, rating=rating, review_count=3000 + i * 7,
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
            asin = result.product.external_id
            if asin in PRICE_PATHS:
                _backfill(session, result.product, PRICE_PATHS[asin])
                print(f"seeded #{result.product.id} {result.product.title[:50]!r} "
                      f"with {len(PRICE_PATHS[asin])} days of history")
    print("Done. Run:  python -m price_intel.cli serve   (or: uvicorn price_intel.api.main:app)")


if __name__ == "__main__":
    main()
