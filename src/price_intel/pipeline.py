"""Ingestion pipeline: scrape -> normalize -> persist -> detect change.

This is the orchestration layer that ties scrapers, normalization, and the
database together. It is deliberately storage-aware but scraper-agnostic: it
asks the registry for whichever scraper handles a URL, so new stores light up
here with zero changes.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import PriceChange, PriceSnapshot, Product, Store
from .normalizer import normalize, price_to_minor
from .scrapers.base import ProductData
from .scrapers.registry import get_scraper_for_url


@dataclass
class TrackResult:
    """Outcome of tracking a URL once."""

    product: Product
    snapshot: PriceSnapshot
    change: PriceChange | None
    created: bool  # True if the product was seen for the first time


def _get_or_create_store(session: Session, slug: str, name: str, base_url: str) -> Store:
    store = session.scalar(select(Store).where(Store.slug == slug))
    if store is None:
        store = Store(slug=slug, name=name, base_url=base_url)
        session.add(store)
        session.flush()  # assign PK
    return store


def _upsert_product(session: Session, store: Store, data: ProductData, url: str) -> tuple[Product, bool]:
    product = session.scalar(
        select(Product).where(
            Product.store_id == store.id, Product.external_id == data.external_id
        )
    )
    created = product is None
    if product is None:
        product = Product(store_id=store.id, external_id=data.external_id, url=url)
        session.add(product)
    # Refresh descriptive fields on every scrape (they can change over time).
    product.url = url
    product.title = data.title
    product.brand = data.brand
    product.image_url = data.image_url
    product.currency = data.currency
    product.specs = data.specs
    session.flush()
    return product, created


def _detect_change(
    session: Session, product: Product, new_price_minor: int | None
) -> PriceChange | None:
    """Compare against the most recent prior snapshot and record a change."""
    if new_price_minor is None:
        return None
    prev = session.scalar(
        select(PriceSnapshot)
        .where(
            PriceSnapshot.product_id == product.id,
            PriceSnapshot.price_minor.is_not(None),
        )
        .order_by(PriceSnapshot.scraped_at.desc())
        .limit(1)
    )
    if prev is None or prev.price_minor is None or prev.price_minor == new_price_minor:
        return None

    old = prev.price_minor
    delta = new_price_minor - old
    change = PriceChange(
        product_id=product.id,
        old_price_minor=old,
        new_price_minor=new_price_minor,
        change_minor=delta,
        change_percent=round(delta / old * 100, 2) if old else 0.0,
        direction="up" if delta > 0 else "down",
    )
    session.add(change)
    return change


def ingest(session: Session, data: ProductData, url: str) -> TrackResult:
    """Persist an already-scraped :class:`ProductData` and detect changes.

    Split out from :func:`track` so tests can inject data without the network.
    """
    data = normalize(data)
    scraper = _store_meta_for(data.store_slug)
    store = _get_or_create_store(session, data.store_slug, scraper[0], scraper[1])
    product, created = _upsert_product(session, store, data, url)

    new_price_minor = price_to_minor(data.price)
    change = _detect_change(session, product, new_price_minor)

    snapshot = PriceSnapshot(
        product_id=product.id,
        price_minor=new_price_minor,
        currency=data.currency,
        in_stock=data.in_stock,
        discount_percent=data.discount_percent,
        rating=data.rating,
        review_count=data.review_count,
    )
    session.add(snapshot)
    session.flush()
    return TrackResult(product=product, snapshot=snapshot, change=change, created=created)


def track(session: Session, url: str) -> TrackResult:
    """Scrape ``url`` live/fixture, then ingest the result."""
    scraper = get_scraper_for_url(url)
    data = scraper.scrape(url)
    return ingest(session, data, url)


def _store_meta_for(slug: str) -> tuple[str, str]:
    """Resolve (name, base_url) for a store slug via its scraper."""
    from .scrapers.registry import iter_scrapers

    for scraper in iter_scrapers():
        if scraper.store_slug == slug:
            return scraper.store_name, scraper.base_url
    return slug.title(), ""
