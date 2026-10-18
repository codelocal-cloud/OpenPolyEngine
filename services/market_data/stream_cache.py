"""Ephemeral derived best bid/ask data, published only from complete book snapshots."""
from __future__ import annotations

from datetime import datetime, timezone
import json

import redis
from .config import RedisConfig
from .observations import MarketObservation, SOURCE

BOOK_TTL_SECONDS = 20


class StreamBookCache:
    def __init__(self, config: RedisConfig | None = None):
        cfg = config or RedisConfig.from_env()
        self.client = redis.Redis(
            host=cfg.host, port=cfg.port, password=cfg.password,
            socket_connect_timeout=3, socket_timeout=3, decode_responses=True,
        )

    def publish_books(self, observations: list[MarketObservation]) -> int:
        count = 0
        now = datetime.now(timezone.utc)
        with self.client.pipeline(transaction=True) as pipe:
            for event in observations:
                # Never treat an archived book as a live quote.
                if event.source != SOURCE or event.event_type != "book":
                    continue
                if (now - event.received_at).total_seconds() > BOOK_TTL_SECONDS:
                    continue
                # Bid/ask are derived from a *full* order book; no partial deltas.
                payload = {
                    "source": event.source, "slug": event.slug,
                    "token_id": event.instrument, "outcome": event.outcome,
                    "observed_at": event.observed_at.isoformat(),
                    "received_at": event.received_at.isoformat(),
                    "best_bid": event.payload.get("best_bid"),
                    "best_ask": event.payload.get("best_ask"),
                    "kind": "full_book_snapshot_bbo",
                }
                data = json.dumps(payload, separators=(",", ":"))
                pipe.set(f"openpoly:book:{event.instrument}", data, ex=BOOK_TTL_SECONDS)
                pipe.publish("openpoly:book:updates", data)
                count += 1
            if count:
                pipe.execute()
        return count
