"""Pydantic response/request models for the API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl


class TrackRequest(BaseModel):
    #: Validated as a URL rather than a bare string. A plain ``str`` let a caller
    #: store a value carrying an HTML attribute break-out (``..." onmouseover="``)
    #: that the dashboard then rendered into an ``href``. ``HttpUrl`` percent-encodes
    #: those characters, so the payload cannot survive storage even if a future
    #: template forgets to escape.
    url: HttpUrl = Field(..., description="Product URL to track (e.g. an Amazon /dp/ link)")


class StoreOut(BaseModel):
    id: int
    slug: str
    name: str


class ProductSummary(BaseModel):
    id: int
    external_id: str
    title: str
    brand: str | None
    image_url: str | None
    url: str
    currency: str
    store: StoreOut
    current_price: float | None
    in_stock: bool
    rating: float | None
    review_count: int | None
    is_lowest_ever: bool
    snapshots: int


class PricePointOut(BaseModel):
    at: datetime
    price: float | None
    in_stock: bool


class PriceChangeOut(BaseModel):
    old_price: float
    new_price: float
    change: float
    change_percent: float
    direction: str
    detected_at: datetime


class StatsOut(BaseModel):
    current_price: float | None
    lowest_price: float | None
    highest_price: float | None
    average_price: float | None
    price_drop_from_peak_pct: float | None
    is_lowest_ever: bool
    snapshots: int


class ProductDetail(ProductSummary):
    specs: dict[str, str]
    stats: StatsOut
    history: list[PricePointOut]
    changes: list[PriceChangeOut]


class TrackResponse(BaseModel):
    created: bool
    product_id: int
    detected_change: PriceChangeOut | None
    message: str
