"""PostgreSQL/TimescaleDB is the sole operational persistence backend.

JSONL is an optional portable export for reproducible research, not a database.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import psycopg
from psycopg.types.json import Jsonb

from .config import PostgresConfig
from .models import MarketSnapshot


UPSERT_SNAPSHOT_SQL = """
INSERT INTO market_snapshots (
    slug, fetched_at, market_id, slot_start, slot_end,
    token_up, token_down, price_up, price_down,
    active, closed, accepting_orders, data_source, resolution_source, payload_json
) VALUES (
    %(slug)s, %(fetched_at)s, %(market_id)s, %(slot_start)s, %(slot_end)s,
    %(token_up)s, %(token_down)s, %(price_up)s, %(price_down)s,
    %(active)s, %(closed)s, %(accepting_orders)s, %(data_source)s,
    %(resolution_source)s, %(payload_json)s
)
ON CONFLICT (slug, fetched_at) DO UPDATE SET
    market_id=EXCLUDED.market_id,
    active=EXCLUDED.active,
    closed=EXCLUDED.closed,
    accepting_orders=EXCLUDED.accepting_orders,
    price_up=EXCLUDED.price_up,
    price_down=EXCLUDED.price_down,
    data_source=EXCLUDED.data_source,
    resolution_source=EXCLUDED.resolution_source,
    payload_json=EXCLUDED.payload_json
"""

LATEST_SNAPSHOTS_SQL = """
SELECT payload_json FROM (
  SELECT DISTINCT ON (slug)
    slug, slot_start, fetched_at, payload_json
  FROM market_snapshots
  ORDER BY slug, fetched_at DESC
) AS latest
ORDER BY slot_start DESC
LIMIT %s
"""


class PostgresStore:
    """Uses short-lived PostgreSQL connections; concurrent writers are atomic."""

    def __init__(self, config: PostgresConfig | None = None, *, connector: Callable | None = None):
        self.config = config or PostgresConfig.from_env()
        self._connector = connector or psycopg.connect

    def write_snapshots(self, snapshots: list[MarketSnapshot]) -> int:
        if not snapshots:
            return 0
        with self._connector(**self.config.connect_kwargs()) as con:
            with con.cursor() as cur:
                for snap in snapshots:
                    record = {
                        "slug": snap.slug,
                        "fetched_at": snap.fetched_at,
                        "market_id": snap.market_id,
                        "slot_start": snap.slot_start,
                        "slot_end": snap.slot_end,
                        "token_up": snap.token_up,
                        "token_down": snap.token_down,
                        "price_up": snap.price_up,
                        "price_down": snap.price_down,
                        "active": snap.active,
                        "closed": snap.closed,
                        "accepting_orders": snap.accepting_orders,
                        "data_source": snap.data_source,
                        "resolution_source": snap.resolution_source,
                        "payload_json": Jsonb(snap.to_dict()),
                    }
                    cur.execute(UPSERT_SNAPSHOT_SQL, record)
        return len(snapshots)

    def recent_snapshots(self, limit: int = 20) -> list[dict]:
        if not 1 <= limit <= 50:
            raise ValueError("limit must be in 1..50")
        with self._connector(**self.config.connect_kwargs()) as con:
            with con.cursor() as cur:
                cur.execute(LATEST_SNAPSHOTS_SQL, (limit,))
                rows = cur.fetchall()
        return [row[0] if isinstance(row[0], dict) else json.loads(row[0]) for row in rows]


def append_jsonl(path: str | Path, snapshots: list[MarketSnapshot]) -> int:
    location = Path(path)
    location.parent.mkdir(parents=True, exist_ok=True)
    with location.open("a", encoding="utf-8") as output:
        for item in snapshots:
            output.write(json.dumps(item.to_dict(), sort_keys=True) + "\n")
    return len(snapshots)
