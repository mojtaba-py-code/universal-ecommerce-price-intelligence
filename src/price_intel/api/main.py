"""FastAPI application factory and entrypoint.

Run with:
    uvicorn price_intel.api.main:app --reload
or via the CLI:
    price-intel serve
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ..config import get_settings
from ..db import init_db
from .routes import router

STATIC_DIR = Path(__file__).resolve().parent / "static"

# The dashboard is a single self-contained page: no third-party scripts, no
# remote fonts, no embedding by anyone else. The policy says exactly that, so a
# stored-XSS attempt through a scraped product title has nowhere to send data.
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' https: data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


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

    @app.middleware("http")
    async def add_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response

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
