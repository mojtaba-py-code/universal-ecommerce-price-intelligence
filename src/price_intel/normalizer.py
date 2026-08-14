"""Normalization helpers.

Scrapers already emit a uniform :class:`ProductData`, but values coming off the
web are messy. This module cleans and bounds them so the persistence layer only
ever sees sane data (e.g. ratings clamped to 0-5, prices converted to integer
minor units, whitespace collapsed).
"""

from __future__ import annotations

import re

from .scrapers.base import ProductData


def _clean_text(value: str | None, *, max_len: int | None = None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    if not cleaned:
        return None
    if max_len is not None:
        cleaned = cleaned[:max_len]
    return cleaned


def price_to_minor(price: float | None) -> int | None:
    """Convert major-unit price (dollars) to integer minor units (cents)."""
    if price is None:
        return None
    if price < 0:
        return None
    return int(round(price * 100))


def normalize(data: ProductData) -> ProductData:
    """Return a cleaned copy-in-place of ``data`` with bounded fields."""
    data.title = _clean_text(data.title, max_len=1000) or ""
    data.brand = _clean_text(data.brand, max_len=250)
    data.image_url = _clean_text(data.image_url, max_len=1000)
    data.currency = (data.currency or "USD").upper()[:8]

    if data.rating is not None:
        data.rating = max(0.0, min(5.0, round(float(data.rating), 2)))
    if data.review_count is not None:
        data.review_count = max(0, int(data.review_count))
    if data.discount_percent is not None:
        data.discount_percent = max(0.0, min(100.0, round(float(data.discount_percent), 2)))
    if data.price is not None and data.price < 0:
        data.price = None

    # Collapse whitespace inside spec values and drop empty entries. Cleaning
    # once per pair, rather than three times in a comprehension, is both cheaper
    # and the reason the result is known to hold no ``None``.
    specs: dict[str, str] = {}
    for raw_key, raw_value in (data.specs or {}).items():
        key = _clean_text(raw_key, max_len=120)
        value = _clean_text(raw_value, max_len=500)
        if key and value:
            specs[key] = value
    data.specs = specs
    return data
