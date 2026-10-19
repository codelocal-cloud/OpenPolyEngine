"""Public read-only BTC 5m Gamma discovery. No synthetic/fixture input path."""
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
from .models import MarketParseError, upcoming_slugs
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
    p = argparse.ArgumentParser(description="Official Gamma API BTC 5m discovery (real-data-only)")
    p.add_argument("--slots", type=int, default=1, help="Current plus future slots (1..12)")
    p.add_argument("--at", type=_datetime, help="Reference timestamp (ISO8601 with UTC offset)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--jsonl", type=Path, help="Optional export of real market snapshots")
    p.add_argument("--persist", action="store_true", help="Write verified metadata to TimescaleDB")
    p.add_argument("--cache", action="store_true", help="Publish verified snapshots to Redis")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = make_parser()
    args = parser.parse_args(argv)
    if not 1 <= args.slots <= 12:
        parser.error("--slots must be between 1 and 12")
    at = args.at or datetime.now(timezone.utc)
    client = GammaClient()
    results = []
    verified = []
    had_error = False
    for slug in upcoming_slugs(at, args.slots):
        try:
            snapshot = client.fetch_snapshot(slug)
            if snapshot is None:
                results.append({"slug": slug, "status": "not_found"})
                continue
            if snapshot.data_source != "gamma_public":
                raise MarketParseError("Unverified upstream data")
            verified.append(snapshot)
            results.append({"slug": slug, "status": "ok", "market": snapshot.to_dict()})
        except (OSError, GammaError, MarketParseError, ValueError) as exc:
            had_error = True
            results.append({"slug": slug, "status": "error", "detail": str(exc)})
    try:
        if args.jsonl:
            append_jsonl(args.jsonl, verified)
        if args.persist:
            PostgresStore().write_snapshots(verified)
        if args.cache:
            RedisCache().publish(verified)
    except (OSError, ValueError, psycopg.Error, redis.RedisError) as exc:
        print(f"Unable to persist or cache market data: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps({"mode":"READ_ONLY","source":"gamma_public","results":results}, indent=2))
    else:
        print("OpenPolyEngine | Real Gamma only | No live order execution")
        for item in results:
            if item["status"] == "ok":
                print(f'{item["slug"]}: metadata verified; indicative prices only')
            else:
                print(f'{item["slug"]}: {item["status"]} {item.get("detail", "")}')
    return 1 if had_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
