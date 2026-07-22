# Universal E-commerce Price Intelligence

[![CI](https://github.com/mojtaba-py-code/Universal-E-commerce-Price-Intelligence/actions/workflows/ci.yml/badge.svg)](https://github.com/mojtaba-py-code/Universal-E-commerce-Price-Intelligence/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A plugin-based system that scrapes product data from e-commerce stores, stores a
full **price history** in a relational database, **detects price changes**, and
serves **analytics + charts** through a FastAPI web dashboard.

> Built around a clean plugin architecture: adding a new store is a single new
> file, no changes to the pipeline, API, or database layer.

---

## What it collects

For every tracked product: **price, availability, discount, brand, user rating,
review count, images, and specifications** — captured as an append-only history
so trends can be charted and the lowest-ever price can be found.

## Architecture

```
        ┌──────────────┐   scrape    ┌──────────────┐  normalize  ┌───────────┐
 URL ─► │  Scrapers    │ ──────────► │  ProductData │ ──────────► │ Normalizer│
        │ (plugins)    │             └──────────────┘             └─────┬─────┘
        └──────────────┘                                                │
             ▲  BaseScraper + registry                                  ▼
             │                                             ┌────────────────────────┐
   fixture ──┤ (offline, deterministic, test-safe)         │  Pipeline: upsert +    │
   live   ───┘ (real network, may be blocked)              │  change detection      │
                                                           └───────────┬────────────┘
                                                                       ▼
   ┌──────────────┐    analytics     ┌──────────────────────────────────────────┐
   │  FastAPI +   │ ◄─────────────── │ PostgreSQL / SQLite                       │
   │  dashboard   │                  │ stores · products · price_snapshots ·     │
   │  (Chart.js)  │                  │ price_changes                             │
   └──────────────┘                  └──────────────────────────────────────────┘
```

| Layer | File |
|-------|------|
| Config (env-driven) | `src/price_intel/config.py` |
| Database engine/session | `src/price_intel/db.py` |
| ORM models | `src/price_intel/models.py` |
| Scraper interface + registry | `src/price_intel/scrapers/base.py`, `registry.py` |
| Amazon scraper (real selectors) | `src/price_intel/scrapers/amazon.py` |
| Normalization | `src/price_intel/normalizer.py` |
| Pipeline + change detection | `src/price_intel/pipeline.py` |
| Analytics | `src/price_intel/analysis.py` |
| API + dashboard | `src/price_intel/api/` |
| CLI | `src/price_intel/cli.py` |

---

## Quick start (zero setup)

By default the app runs against a local **SQLite** file and the offline
**fixture** scraper — no Docker, no Postgres, no network required.

```bash
python -m pip install -e .        # install the package + dependencies
python seed_demo.py               # create demo products with 30 days of history
python -m price_intel.cli serve   # start the dashboard at http://127.0.0.1:8000
```

Open <http://127.0.0.1:8000> → browse products, click one to see its price
chart, stats, recent changes, and specs.

### CLI

```bash
price-intel stores                 # list registered store scrapers
price-intel track <amazon-url>     # scrape & store one product
price-intel list                   # list tracked products
price-intel stats <product_id>     # analytics for one product
price-intel serve --reload         # run the web dashboard
```

---

## Using PostgreSQL (Docker Compose)

The production configuration uses PostgreSQL. Bring it up and point the app at it:

```bash
docker compose up -d               # starts postgres:16 on localhost:5432
```

Then in `.env` (copy from `.env.example`):

```dotenv
DATABASE_URL=postgresql+psycopg2://priceintel:priceintel@localhost:5432/priceintel
```

No code changes are needed — the storage layer is database-agnostic.

---

## Scraper modes: `fixture` vs `live`

Set in `.env` via `SCRAPER_MODE`:

- **`fixture`** (default) — parses saved HTML in `data/fixtures/<store>/`. Fully
  offline and deterministic; this is what the test-suite uses.
- **`live`** — fetches real pages over the network with a browser-like client
  and polite rate-limiting.

> **About live Amazon scraping.** Amazon actively fights automated access
> (rotating markup, CAPTCHA / anti-bot challenges). The Amazon scraper uses the
> real DOM selectors and degrades gracefully, but a live request can still be
> served a challenge — in which case the API returns a clear `502` and the rest
> of the system keeps working. This is why `fixture` mode exists and why the
> architecture never depends on any single live source. Scrape responsibly and
> respect each store's Terms of Service and `robots.txt`.

---

## Adding a new store (the plugin pattern)

Create `src/price_intel/scrapers/<store>.py`:

```python
from .base import BaseScraper, ProductData
from .registry import register

@register
class MyStoreScraper(BaseScraper):
    store_slug = "mystore"
    store_name = "My Store"
    base_url = "https://mystore.com"

    def can_handle(self, url): return "mystore.com" in url
    def extract_external_id(self, url): ...       # pull product id from URL
    def parse(self, html, url) -> ProductData: ...  # parse saved/live HTML
```

Import it in `scrapers/__init__.py`. That's it — the pipeline, API, and
dashboard pick it up automatically.

---

## Tests

```bash
python -m pytest
```

23 tests cover scraping/parsing, the pipeline & change detection, analytics, and
the full HTTP API — all offline against fixtures and a temporary SQLite database.

---

## Tech stack

Python 3.11+ · FastAPI · SQLAlchemy 2.0 · PostgreSQL / SQLite · httpx ·
BeautifulSoup · Chart.js · pytest · Docker Compose
