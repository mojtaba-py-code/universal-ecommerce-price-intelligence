"""SQLAlchemy ORM models.

Schema overview
---------------
* ``Store``          - an e-commerce site (Amazon, ...).
* ``Product``        - a tracked product, unique per (store, external_id).
* ``PriceSnapshot``  - one observation of a product at a point in time. This is
                       the append-only history that powers charts & analytics.
* ``PriceChange``    - a detected transition between two consecutive snapshots.

Prices are stored as integer *minor units* (e.g. cents) to avoid floating point
rounding problems; helpers convert to/from decimals at the edges.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class Store(Base):
    __tablename__ = "stores"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    base_url: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    products: Mapped[list["Product"]] = relationship(
        back_populates="store", cascade="all, delete-orphan"
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("store_id", "external_id", name="uq_store_external_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)

    external_id: Mapped[str] = mapped_column(String(128), index=True)  # e.g. Amazon ASIN
    url: Mapped[str] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(1024), default="")
    brand: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    specs: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    store: Mapped["Store"] = relationship(back_populates="products")
    snapshots: Mapped[list["PriceSnapshot"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="PriceSnapshot.scraped_at",
    )
    changes: Mapped[list["PriceChange"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )

    price_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)  # cents; None if unknown
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    discount_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    rating: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    scraped_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    product: Mapped["Product"] = relationship(back_populates="snapshots")

    @property
    def price(self) -> float | None:
        """Price in major units (e.g. dollars), or None when unknown."""
        return None if self.price_minor is None else self.price_minor / 100.0


class PriceChange(Base):
    __tablename__ = "price_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )

    old_price_minor: Mapped[int] = mapped_column(Integer)
    new_price_minor: Mapped[int] = mapped_column(Integer)
    change_minor: Mapped[int] = mapped_column(Integer)       # new - old (signed)
    change_percent: Mapped[float] = mapped_column(Float)     # relative to old price
    direction: Mapped[str] = mapped_column(String(8))        # "up" | "down"
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    product: Mapped["Product"] = relationship(back_populates="changes")

    @property
    def old_price(self) -> float:
        return self.old_price_minor / 100.0

    @property
    def new_price(self) -> float:
        return self.new_price_minor / 100.0

    @property
    def change(self) -> float:
        return self.change_minor / 100.0
