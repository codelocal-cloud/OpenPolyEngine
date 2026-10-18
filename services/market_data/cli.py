"""One-shot read-only BTC 5-minute scanner; PostgreSQL is the only database.

Examples:
    python3 -m services.market_data.cli --slots 3 --json
    python3 -m services.market_data.cli --slots 3 --persist --cache
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import psycopg
import redis

from .cache import RedisCache
from .gamma import GammaClient, GammaError
from .models import MarketParseError, parse_event, upcoming_slugs
from .storage import PostgresStore, append_jsonl


def _datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected ISO8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("--at must include a UTC offset")
    return parsed


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Read-only Polymarket BTC 5m market discovery")
    p.add_argument("--slots", type=int, default=3, help="Current plus future slots (1..12)")
    p.add_argument("--at", type=_datetime, help="Reference timestamp (ISO8601 with UTC offset)")
    p.add_argument("--offline-fixture", type=Path, help="Fixture event JSON; only with --slots 1")
    p.add_argument("--json", action="store_true", help="Print JSON instead of concise human output")
    p.add_argument("--jsonl", type=Path, help="Optional research export in newline JSON format")
    p.add_argument("--persist", action="store_true", help="Write observations to PostgreSQL/TimescaleDB")
    p.add_argument("--cache", action="store_true", help="Publish real observations to Redis with 30s TTL")
    return p


def main(argv: list[str] | None = None) -> int:
    p = make_parser()
    args = p.parse_args(argv)
    if not 1 <= args.slots <= 12:
        p.error("--slots must be between 1 and 12")
    if args.offline_fixture and args.slots != 1:
        p.error("Offline fixture requires --slots 1")
    if args.offline_fixture and args.cache:
        p.error("Cannot publish offline fixture to real-time Redis cache")

    at = args.at or datetime.now(timezone.utc)
    client = GammaClient() if not args.offline_fixture else None
    results = []
    saved = []
    had_error = False
    for slug in upcoming_slugs(at, args.slots):
        try:
            if args.offline_fixture:
                event = json.loads(args.offline_fixture.read_text(encoding="utf-8"))
                snapshot = parse_event(event, slug, fetched_at=at, data_source="offline_fixture")
            else:
                snapshot = client.fetch_snapshot(slug)  # type: ignore[union-attr]
            if snapshot is None:
                results.append({"slug": slug, "status": "not_found"})
                continue
            saved.append(snapshot)
            results.append({"slug": slug, "status": "ok", "market": snapshot.to_dict()})
        except (OSError, GammaError, MarketParseError, ValueError) as exc:
            had_error = True
            results.append({"slug": slug, "status": "error", "detail": str(exc)})

    try:
        if args.jsonl:
            append_jsonl(args.jsonl, saved)
        if args.persist:
            PostgresStore().write_snapshots(saved)
        if args.cache:
            RedisCache().publish(saved)
    except (OSError, ValueError, psycopg.Error, redis.RedisError) as exc:
        print(f"Unable to persist or cache market data: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"mode": "READ_ONLY", "results": results}, indent=2))
    else:
        print("PolyBTC BTC 5M | READ_ONLY | No wallet / No live orders")
        for item in results:
            if item["status"] == "ok":
                m = item["market"]
                print(f'{item["slug"]}: UP={m["price_up"]} DOWN={m["price_down"]} '
                      f'active={m["active"]} accepting={m["accepting_orders"]} '
                      f'(indicative only)')
            else:
                print(f'{item["slug"]}: {item["status"]} {item.get("detail", "")}')
    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
