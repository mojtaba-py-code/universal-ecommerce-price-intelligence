"""Tests for the ingestion pipeline: persistence, upsert, change detection."""

from __future__ import annotations

from price_intel.models import PriceSnapshot, Product, Store
from price_intel.pipeline import ingest, track
from price_intel.scrapers.base import ProductData


def _make(price: float, **kw) -> ProductData:
    return ProductData(
        external_id="TESTASIN01",
        url="https://www.amazon.com/dp/TESTASIN01",
        store_slug="amazon",
        title="Test Product",
        brand="TestBrand",
        price=price,
        **kw,
    )


def test_track_creates_store_product_snapshot(session):
    result = track(session, "https://www.amazon.com/dp/B08N5WRWNW")
    session.commit()

    assert result.created is True
    assert session.query(Store).count() == 1
    assert session.query(Product).count() == 1
    assert session.query(PriceSnapshot).count() == 1
    assert result.snapshot.price == 49.99


def test_reingest_same_product_does_not_duplicate(session):
    ingest(session, _make(100.0), "https://www.amazon.com/dp/TESTASIN01")
    ingest(session, _make(100.0), "https://www.amazon.com/dp/TESTASIN01")
    session.commit()

    assert session.query(Product).count() == 1
    assert session.query(PriceSnapshot).count() == 2


def test_price_drop_detected(session):
    ingest(session, _make(100.0), "https://www.amazon.com/dp/TESTASIN01")
    r2 = ingest(session, _make(80.0), "https://www.amazon.com/dp/TESTASIN01")
    session.commit()

    assert r2.change is not None
    assert r2.change.direction == "down"
    assert r2.change.change_percent == -20.0
    assert r2.change.old_price == 100.0
    assert r2.change.new_price == 80.0


def test_price_increase_detected(session):
    ingest(session, _make(50.0), "https://www.amazon.com/dp/TESTASIN01")
    r2 = ingest(session, _make(75.0), "https://www.amazon.com/dp/TESTASIN01")
    session.commit()

    assert r2.change is not None
    assert r2.change.direction == "up"
    assert r2.change.change_percent == 50.0


def test_no_change_when_price_stable(session):
    ingest(session, _make(50.0), "https://www.amazon.com/dp/TESTASIN01")
    r2 = ingest(session, _make(50.0), "https://www.amazon.com/dp/TESTASIN01")
    session.commit()
    assert r2.change is None
