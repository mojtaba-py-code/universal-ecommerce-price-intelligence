"""Application configuration, loaded from environment variables / .env.

The design goal is *zero-setup by default*: with no configuration at all the
app runs against a local SQLite file and the offline `fixture` scraper, so the
whole project (including the test-suite) works without Docker or network
access. Point ``DATABASE_URL`` at PostgreSQL and set ``SCRAPER_MODE=live`` to
switch into the "real" configuration without touching any code.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = two levels up from this file (src/price_intel/config.py).
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ScraperMode(str, Enum):
    """Where scrapers get their HTML from."""

    FIXTURE = "fixture"  # parse saved HTML - offline, deterministic, test-safe
    LIVE = "live"        # fetch real pages over the network


class Settings(BaseSettings):
    """Typed settings resolved from environment variables and an optional .env."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database ----------------------------------------------------------
    # Empty -> fall back to a local SQLite file (see `database_url` property).
    database_url: str = Field(default="")

    # --- Scraper -----------------------------------------------------------
    scraper_mode: ScraperMode = Field(default=ScraperMode.FIXTURE)
    fixture_dir: str = Field(default="data/fixtures")
    request_delay_seconds: float = Field(default=2.0)
    request_timeout_seconds: float = Field(default=20.0)

    # --- App ---------------------------------------------------------------
    app_host: str = Field(default="127.0.0.1")
    app_port: int = Field(default=8000)

    @property
    def resolved_database_url(self) -> str:
        """Return the effective DB URL, defaulting to a local SQLite file."""
        if self.database_url.strip():
            return self.database_url.strip()
        return f"sqlite:///{(PROJECT_ROOT / 'price_intel.db').as_posix()}"

    @property
    def fixture_path(self) -> Path:
        """Absolute path to the fixtures directory."""
        p = Path(self.fixture_dir)
        return p if p.is_absolute() else PROJECT_ROOT / p


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a cached Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
