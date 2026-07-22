"""Command-line interface for the price intelligence system.

Examples
--------
    price-intel init                       # create database tables
    price-intel track <url>                # scrape & store one product
    price-intel list                       # show tracked products
    price-intel stats <product_id>         # print analytics for a product
    price-intel serve                      # run the web dashboard/API
"""

from __future__ import annotations

import argparse
import sys

from . import analysis
from .config import get_settings
from .db import init_db, session_scope
from .models import Product
from .pipeline import track as track_url
from .scrapers.registry import iter_scrapers


def _cmd_init(_: argparse.Namespace) -> int:
    init_db()
    print("Database initialized at:", get_settings().resolved_database_url)
    return 0


def _cmd_stores(_: argparse.Namespace) -> int:
    print("Registered store scrapers:")
    for s in iter_scrapers():
        print(f"  - {s.store_slug:10s} {s.store_name} ({s.base_url})")
    return 0


def _cmd_track(args: argparse.Namespace) -> int:
    init_db()
    with session_scope() as session:
        result = track_url(session, args.url)
        p = result.product
        state = "NEW" if result.created else "updated"
        price = result.snapshot.price
        print(f"[{state}] #{p.id} {p.title[:60]!r} -> {price} {p.currency}")
        if result.change:
            c = result.change
            print(f"  price change: {c.old_price} -> {c.new_price} ({c.change_percent:+.2f}%)")
    return 0


def _cmd_list(_: argparse.Namespace) -> int:
    with session_scope() as session:
        products = session.query(Product).order_by(Product.created_at.desc()).all()
        if not products:
            print("(no products tracked yet)")
            return 0
        for p in products:
            stats = analysis.compute_stats(session, p)
            print(f"#{p.id:<3} {p.currency} {str(stats.current_price):>10}  {p.title[:55]}")
    return 0


def _cmd_stats(args: argparse.Namespace) -> int:
    with session_scope() as session:
        product = session.get(Product, args.product_id)
        if product is None:
            print(f"product {args.product_id} not found", file=sys.stderr)
            return 1
        s = analysis.compute_stats(session, product)
        print(f"{product.title}")
        print(f"  current : {s.current_price} {s.currency}")
        print(f"  lowest  : {s.lowest_price}")
        print(f"  highest : {s.highest_price}")
        print(f"  average : {s.average_price}")
        print(f"  off peak: {s.price_drop_from_peak_pct}%")
        print(f"  snapshots: {s.snapshots}  lowest_ever={s.is_lowest_ever}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "price_intel.api.main:app",
        host=args.host or settings.app_host,
        port=args.port or settings.app_port,
        reload=args.reload,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="price-intel", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create database tables").set_defaults(func=_cmd_init)
    sub.add_parser("stores", help="list registered store scrapers").set_defaults(func=_cmd_stores)

    p_track = sub.add_parser("track", help="scrape & store a product URL")
    p_track.add_argument("url")
    p_track.set_defaults(func=_cmd_track)

    sub.add_parser("list", help="list tracked products").set_defaults(func=_cmd_list)

    p_stats = sub.add_parser("stats", help="show analytics for a product")
    p_stats.add_argument("product_id", type=int)
    p_stats.set_defaults(func=_cmd_stats)

    p_serve = sub.add_parser("serve", help="run the web dashboard/API")
    p_serve.add_argument("--host", default=None)
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.add_argument("--reload", action="store_true")
    p_serve.set_defaults(func=_cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
