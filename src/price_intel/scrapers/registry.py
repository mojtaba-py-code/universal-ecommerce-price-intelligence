"""Scraper registry.

Concrete scrapers register themselves with :func:`register` (used as a class
decorator). Callers resolve the right scraper for a URL with
:func:`get_scraper_for_url`. This is the plugin seam: adding a store never
requires editing the pipeline, API, or this file.
"""

from __future__ import annotations

from collections.abc import Iterator

from .base import BaseScraper

_REGISTRY: list[type[BaseScraper]] = []


def register(cls: type[BaseScraper]) -> type[BaseScraper]:
    """Class decorator that adds a scraper to the registry."""
    if cls not in _REGISTRY:
        _REGISTRY.append(cls)
    return cls


def iter_scrapers() -> Iterator[BaseScraper]:
    """Yield a fresh instance of every registered scraper."""
    for cls in _REGISTRY:
        yield cls()


def get_scraper_for_url(url: str) -> BaseScraper:
    """Return an instance of the first scraper that can handle ``url``.

    Raises ``ValueError`` if no registered scraper matches.
    """
    for scraper in iter_scrapers():
        if scraper.can_handle(url):
            return scraper
    raise ValueError(f"no registered scraper can handle URL: {url}")


def get_scraper_by_slug(slug: str) -> BaseScraper:
    """Return an instance of the scraper for a store ``slug``."""
    for scraper in iter_scrapers():
        if scraper.store_slug == slug:
            return scraper
    raise ValueError(f"no registered scraper for store slug: {slug}")
