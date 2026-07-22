"""FastAPI application factory and entrypoint.

Run with:
    uvicorn price_intel.api.main:app --reload
or via the CLI:
    price-intel serve
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import get_settings
from ..db import init_db
from .routes import router

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    init_db()  # ensure tables exist on startup
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Universal E-commerce Price Intelligence",
        version="1.0.0",
        description=(
            "Scrape product data from multiple stores, track price history in a "
            "database, detect price changes, and visualize trends."
        ),
        lifespan=lifespan,
    )

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        s = get_settings()
        return {"status": "ok", "scraper_mode": s.scraper_mode.value}

    app.include_router(router)

    # Serve the dashboard. The SPA lives in ./static/index.html.
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
