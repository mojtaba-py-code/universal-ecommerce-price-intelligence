"""Shared pytest fixtures.

Every test runs against an isolated temporary SQLite database and the offline
`fixture` scraper, so the suite is fully deterministic and needs no network,
Docker, or Postgres.
"""

from __future__ import annotations

import os

import pytest

# Force offline, isolated configuration BEFORE any app module imports settings.
os.environ.setdefault("SCRAPER_MODE", "fixture")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Bind the app to a fresh temp SQLite DB and yield a session factory."""
    from price_intel import config, db as db_module

    db_file = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.as_posix()}")

    # Reset cached settings + engine so the new URL takes effect.
    config._settings = None
    db_module.reset_state()
    db_module.init_db()

    yield db_module

    db_module.reset_state()
    config._settings = None


@pytest.fixture()
def session(db):
    factory = db.get_session_factory()
    s = factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture()
def client(db):
    """A FastAPI TestClient bound to the temp DB."""
    from fastapi.testclient import TestClient

    from price_intel.api.main import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c
