"""Scraper plugins.

Importing this package registers all built-in scrapers with the registry so
that :func:`price_intel.scrapers.registry.get_scraper_for_url` can resolve them.
Add a new store by dropping a module here that subclasses ``BaseScraper`` and
decorating it with ``@register``.
"""

from .base import BaseScraper, ProductData
from .registry import get_scraper_for_url, iter_scrapers, register

# Import concrete scrapers for their registration side-effects.
from . import amazon  # noqa: F401  (side-effect import)

__all__ = [
    "BaseScraper",
    "ProductData",
    "register",
    "get_scraper_for_url",
    "iter_scrapers",
]
