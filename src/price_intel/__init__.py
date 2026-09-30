"""Universal E-commerce Price Intelligence.

A plugin-based system that scrapes product data from multiple e-commerce
stores, stores price history in a relational database, detects price changes,
and exposes analytics through a FastAPI web dashboard.
"""

from importlib.metadata import PackageNotFoundError, version

# pyproject.toml is the single source of the version; reading it from the
# installed metadata keeps the API, the CLI and the package from disagreeing.
try:
    __version__ = version("price-intel")
except PackageNotFoundError:  # a source tree that was never installed
    __version__ = "0+unknown"
