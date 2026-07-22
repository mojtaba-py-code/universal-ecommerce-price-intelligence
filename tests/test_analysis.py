"""Tests for analytics computations."""

from __future__ import annotations

from price_intel.analysis import compute_stats, get_history
from price_intel.pipeline import ingest
from price_intel.scrapers.base import ProductData


def _ingest_prices(session, prices):
    for p in prices:
        ingest(
            session,
            ProductData(
                external_id="STATS01",
                url="https://www.amazon.com/dp/STATS01",
                store_slug="amazon",
                title="Stats Product",
                price=p,
            ),
            "https://www.amazon.com/dp/STATS01",
        )
    session.commit()
    from price_intel.models import Product

    return session.query(Product).one()


def test_stats_basic(session):
    product = _ingest_prices(session, [100.0, 80.0, 120.0, 90.0])
    stats = compute_stats(session, product)

    assert stats.snapshots == 4
    assert stats.current_price == 90.0
    assert stats.lowest_price == 80.0
    assert stats.highest_price == 120.0
    assert stats.average_price == 97.5
    assert stats.is_lowest_ever is False
    # off-peak: (120 - 90) / 120 * 100 = 25%
    assert stats.price_drop_from_peak_pct == 25.0


def test_stats_lowest_ever(session):
    product = _ingest_prices(session, [100.0, 90.0, 70.0])
    stats = compute_stats(session, product)
    assert stats.is_lowest_ever is True
    assert stats.current_price == 70.0


def test_history_is_ordered(session):
    product = _ingest_prices(session, [10.0, 20.0, 30.0])
    hist = get_history(session, product.id)
    prices = [h.price for h in hist]
    assert prices == [10.0, 20.0, 30.0]
