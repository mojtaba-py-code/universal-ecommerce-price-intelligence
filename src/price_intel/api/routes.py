"""API routes for products, tracking, history, and analytics."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import analysis, pipeline
from ..db import get_db
from ..models import Product
from ..scrapers.base import BlockedError, ScraperError
from ..scrapers.registry import get_scraper_for_url, iter_scrapers
from .schemas import (
    PriceChangeOut,
    PricePointOut,
    ProductDetail,
    ProductSummary,
    StatsOut,
    StoreOut,
    TrackRequest,
    TrackResponse,
)

router = APIRouter(prefix="/api", tags=["price-intel"])


def _summary(session: Session, product: Product) -> ProductSummary:
    stats = analysis.compute_stats(session, product)
    return ProductSummary(
        id=product.id,
        external_id=product.external_id,
        title=product.title,
        brand=product.brand,
        image_url=product.image_url,
        url=product.url,
        currency=product.currency,
        store=StoreOut(id=product.store.id, slug=product.store.slug, name=product.store.name),
        current_price=stats.current_price,
        in_stock=stats.in_stock,
        rating=stats.latest_rating,
        review_count=stats.latest_review_count,
        is_lowest_ever=stats.is_lowest_ever,
        snapshots=stats.snapshots,
    )


def _change_out(change) -> PriceChangeOut:
    return PriceChangeOut(
        old_price=change.old_price,
        new_price=change.new_price,
        change=change.change,
        change_percent=change.change_percent,
        direction=change.direction,
        detected_at=change.detected_at,
    )


@router.get("/stores")
def list_stores() -> list[dict]:
    """List every store the system can scrape (the plugin registry)."""
    return [
        {"slug": s.store_slug, "name": s.store_name, "base_url": s.base_url}
        for s in iter_scrapers()
    ]


@router.get("/products", response_model=list[ProductSummary])
def list_products(session: Session = Depends(get_db)) -> list[ProductSummary]:
    products = session.scalars(select(Product).order_by(Product.created_at.desc())).all()
    return [_summary(session, p) for p in products]


@router.post("/track", response_model=TrackResponse)
def track_product(req: TrackRequest, session: Session = Depends(get_db)) -> TrackResponse:
    try:
        get_scraper_for_url(req.url)  # validate early for a clean 400
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        result = pipeline.track(session, req.url)
    except BlockedError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ScraperError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    session.commit()

    msg = "New product tracked." if result.created else "Product re-checked."
    if result.change is not None:
        msg += f" Price {result.change.direction} {result.change.change_percent:+.2f}%."
    return TrackResponse(
        created=result.created,
        product_id=result.product.id,
        detected_change=_change_out(result.change) if result.change else None,
        message=msg,
    )


@router.post("/products/{product_id}/refresh", response_model=TrackResponse)
def refresh_product(product_id: int, session: Session = Depends(get_db)) -> TrackResponse:
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    try:
        result = pipeline.track(session, product.url)
    except (BlockedError, ScraperError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    session.commit()
    msg = "Refreshed."
    if result.change is not None:
        msg += f" Price {result.change.direction} {result.change.change_percent:+.2f}%."
    return TrackResponse(
        created=False,
        product_id=product.id,
        detected_change=_change_out(result.change) if result.change else None,
        message=msg,
    )


@router.get("/products/{product_id}", response_model=ProductDetail)
def get_product(product_id: int, session: Session = Depends(get_db)) -> ProductDetail:
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")

    stats = analysis.compute_stats(session, product)
    changes = analysis.get_changes(session, product_id)
    base = _summary(session, product)

    return ProductDetail(
        **base.model_dump(),
        specs=product.specs or {},
        stats=StatsOut(
            current_price=stats.current_price,
            lowest_price=stats.lowest_price,
            highest_price=stats.highest_price,
            average_price=stats.average_price,
            price_drop_from_peak_pct=stats.price_drop_from_peak_pct,
            is_lowest_ever=stats.is_lowest_ever,
            snapshots=stats.snapshots,
        ),
        history=[PricePointOut(at=p.at, price=p.price, in_stock=p.in_stock) for p in stats.history],
        changes=[_change_out(c) for c in changes],
    )


@router.delete("/products/{product_id}")
def delete_product(product_id: int, session: Session = Depends(get_db)) -> dict:
    product = session.get(Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="product not found")
    session.delete(product)
    session.commit()
    return {"deleted": product_id}
