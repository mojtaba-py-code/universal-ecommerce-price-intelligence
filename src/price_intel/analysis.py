"""Analytics over stored price history.

Pure read-side helpers that turn the append-only ``PriceSnapshot`` history into
the numbers a dashboard cares about: current vs. lowest/highest ever, average,
total drop from peak, and a time series ready for charting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import PriceChange, PriceSnapshot, Product


@dataclass
class PricePoint:
    at: datetime
    price: float | None
    in_stock: bool


@dataclass
class ProductStats:
    product_id: int
    currency: str
    current_price: float | None = None
    lowest_price: float | None = None
    highest_price: float | None = None
    average_price: float | None = None
    snapshots: int = 0
    price_drop_from_peak_pct: float | None = None
    is_lowest_ever: bool = False
    latest_rating: float | None = None
    latest_review_count: int | None = None
    in_stock: bool = True
    history: list[PricePoint] = field(default_factory=list)


def get_history(session: Session, product_id: int) -> list[PriceSnapshot]:
    """Return all snapshots for a product, oldest first."""
    return list(
        session.scalars(
            select(PriceSnapshot)
            .where(PriceSnapshot.product_id == product_id)
            .order_by(PriceSnapshot.scraped_at.asc())
        )
    )


def get_changes(session: Session, product_id: int, limit: int = 50) -> list[PriceChange]:
    """Return recent detected price changes, newest first."""
    return list(
        session.scalars(
            select(PriceChange)
            .where(PriceChange.product_id == product_id)
            .order_by(PriceChange.detected_at.desc())
            .limit(limit)
        )
    )


def compute_stats(session: Session, product: Product) -> ProductStats:
    """Compute summary statistics for a single product."""
    snaps = get_history(session, product.id)
    stats = ProductStats(product_id=product.id, currency=product.currency)
    stats.snapshots = len(snaps)

    priced = [s for s in snaps if s.price_minor is not None]
    if snaps:
        latest = snaps[-1]
        stats.in_stock = latest.in_stock
        stats.latest_rating = latest.rating
        stats.latest_review_count = latest.review_count

    if priced:
        prices_minor = [s.price_minor for s in priced]
        current = priced[-1].price_minor
        lowest = min(prices_minor)
        highest = max(prices_minor)

        stats.current_price = current / 100.0
        stats.lowest_price = lowest / 100.0
        stats.highest_price = highest / 100.0
        stats.average_price = round(sum(prices_minor) / len(prices_minor) / 100.0, 2)
        stats.is_lowest_ever = current <= lowest
        if highest > 0:
            stats.price_drop_from_peak_pct = round((highest - current) / highest * 100, 2)

    stats.history = [
        PricePoint(at=s.scraped_at, price=s.price, in_stock=s.in_stock) for s in snaps
    ]
    return stats
