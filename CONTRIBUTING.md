# Contributing

Thanks for taking a look. This is how the project is developed locally and what
CI expects before a change lands.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"          # add ".[dev,postgres]" for PostgreSQL
cp .env.example .env
```

Load the demo dataset and start the dashboard:

```bash
python seed_demo.py
price-intel serve
```

## Before you push

This is what CI runs, on Python 3.11 and 3.12:

```bash
python -m pytest
```

## Conventions

- **Scrapers are plugins.** A new store is a new scraper module registered with
  the existing registry — the tracker, storage layer, API and dashboard must not
  need to know it exists.
- **Scrape politely and legally.** Respect each site's `robots.txt` and Terms of
  Service, keep the request rate low, and never commit credentials or cookies.
  A demo scraper that hammers a live store will not be merged.
- **Schema changes** go through SQLAlchemy models in `src/price_intel`, with a
  note in the PR about how existing databases migrate.
- **Prices are stored as they were observed** — never overwrite a historical
  point; append a new one.
- **Tests** — add tests with the change; scraper tests parse saved HTML
  fixtures, never the live network.
- **Commits** — short imperative subject, a body explaining the *why*.

## Reporting a security problem

Do not open a public issue — see [SECURITY.md](SECURITY.md).
