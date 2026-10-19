"""Atomic, idempotent TimescaleDB writes for public, time-stamped market events."""
from __future__ import annotations

from typing import Callable
import psycopg
from psycopg.types.json import Jsonb

from .config import PostgresConfig
from .observations import MarketObservation

INSERT_EVENT = """
INSERT INTO market_observations
  (observed_at, received_at, source, instrument, event_type,
   source_event_id, slug, outcome, payload)
VALUES (%(observed_at)s, %(received_at)s, %(source)s, %(instrument)s,
        %(event_type)s, %(source_event_id)s, %(slug)s, %(outcome)s, %(payload)s)
ON CONFLICT (source, source_event_id, observed_at) DO NOTHING
"""

LATEST_BOOK_SQL = """
SELECT payload, observed_at, received_at
FROM market_observations
WHERE source = 'polymarket_clob_ws'
  AND event_type = 'book'
  AND instrument = %s
ORDER BY observed_at DESC, received_at DESC
LIMIT 1
"""

RECENT_OBSERVATIONS_SQL = """
SELECT slug, outcome, instrument, event_type, observed_at,
       received_at, payload
FROM market_observations
WHERE slug = %s AND source = 'polymarket_clob_ws'
ORDER BY observed_at DESC, received_at DESC
LIMIT %s
"""


class ObservationStore:
    def __init__(self, config: PostgresConfig | None = None, *, connector: Callable | None = None):
        self.config = config or PostgresConfig.from_env()
        self.connector = connector or psycopg.connect

    def write_batch(self, observations: list[MarketObservation]) -> int:
        if not observations:
            return 0
        with self.connector(**self.config.connect_kwargs()) as con:
            with con.cursor() as cur:
                for e in observations:
                    cur.execute(INSERT_EVENT, {
                        "observed_at": e.observed_at,
                        "received_at": e.received_at,
                        "source": e.source,
                        "instrument": e.instrument,
                        "event_type": e.event_type,
                        "source_event_id": e.source_event_id,
                        "slug": e.slug,
                        "outcome": e.outcome,
                        "payload": Jsonb(e.payload),
                    })
        return len(observations)

    def latest_book(self, token_id: str) -> dict | None:
        if not token_id or not token_id.isdigit() or len(token_id) > 90:
            raise ValueError("Invalid token ID")
        with self.connector(**self.config.connect_kwargs()) as con:
            with con.cursor() as cur:
                cur.execute(LATEST_BOOK_SQL, (token_id,))
                row = cur.fetchone()
        if row is None:
            return None
        return {
            "book": row[0],
            "observed_at": row[1].isoformat(),
            "received_at": row[2].isoformat(),
            "data_source": "polymarket_clob_ws",
            "kind": "archived_full_book_snapshot",
        }

    def recent(self, slug: str, limit: int = 50) -> list[dict]:
        from .models import SLUG_RE
        if not SLUG_RE.fullmatch(slug) or not 1 <= limit <= 100:
            raise ValueError("Invalid slug or limit")
        with self.connector(**self.config.connect_kwargs()) as con:
            with con.cursor() as cur:
                cur.execute(RECENT_OBSERVATIONS_SQL, (slug, limit))
                rows = cur.fetchall()
        return [
            {
                "slug": row[0], "outcome": row[1], "instrument": row[2],
                "event_type": row[3], "observed_at": row[4].isoformat(),
                "received_at": row[5].isoformat(), "payload": row[6],
            }
            for row in rows
        ]
