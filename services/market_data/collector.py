"""Public read-only WebSocket collector for BTC Up/Down 5m CLOB order books.

No private keys, no user channel, no signed orders. We write raw normalized
market observations durably *before* publishing any short-lived Redis values.
On disconnect, all in-memory order-book confidence is discarded.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
import time
from typing import Callable

from websockets.asyncio.client import connect

from .gamma import GammaClient
from .models import MarketParseError, MarketSnapshot, slot_slug
from .observation_storage import ObservationStore
from .storage import PostgresStore
from .observations import StreamParseError, MarketObservation, parse_market_message
from .stream_cache import StreamBookCache

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
LOG = logging.getLogger("openpoly.collector")


def validate_market(snapshot: MarketSnapshot, now: datetime) -> dict[str, tuple[str, str]]:
    """Subscribe to a verified, active, current 300-second Gamma contract only."""
    if snapshot.data_source != "gamma_public":
        raise ValueError("Refusing to use unverified fixture for live WebSocket")
    if snapshot.slug != slot_slug(now) or snapshot.closed or not snapshot.active or not snapshot.accepting_orders:
        raise ValueError("Market is not the active BTC 5-minute slot")
    if not snapshot.slot_start <= now < snapshot.slot_end:
        raise ValueError("Market window invalid or expired")
    for token in (snapshot.token_up, snapshot.token_down):
        if not token.isdigit() or len(token) > 90 or len(token) < 12:
            raise ValueError("Invalid Polymarket token ID")
    if snapshot.token_up == snapshot.token_down:
        raise ValueError("Both outcomes have the same token")
    return {
        snapshot.token_up: (snapshot.slug, "UP"),
        snapshot.token_down: (snapshot.slug, "DOWN"),
    }


async def heartbeat(ws, *, interval: float = 10.0) -> None:
    while True:
        await asyncio.sleep(interval)
        await ws.send("PING")


class RealtimeCollector:
    def __init__(
        self,
        *,
        gamma: GammaClient | None = None,
        store: ObservationStore | None = None,
        snapshot_store: PostgresStore | None = None,
        cache: StreamBookCache | None = None,
        connector: Callable | None = None,
    ) -> None:
        self.gamma = gamma or GammaClient(timeout_seconds=5, retries=1)
        self.store = store or ObservationStore()
        self.snapshot_store = snapshot_store or PostgresStore()
        self.cache = cache
        self.connector = connector or connect
        self.stored = 0
        self.discarded = 0
        self.connections = 0
        self.last_market: str | None = None

    async def discover(self) -> MarketSnapshot:
        now = datetime.now(timezone.utc)
        slug = slot_slug(now)
        market = await asyncio.to_thread(self.gamma.fetch_snapshot, slug)
        if market is None:
            raise ValueError("Gamma has not published the current BTC 5m market")
        validate_market(market, datetime.now(timezone.utc))
        # Persist token-to-slug provenance before subscribing. This also
        # enables the API/dashboard to find books for newly discovered slots.
        await asyncio.to_thread(self.snapshot_store.write_snapshots, [market])
        return market

    async def persist(self, batch: list[MarketObservation]) -> None:
        if not batch:
            return
        # Never silently lose a batch; stop on DB error so the operator can investigate.
        await asyncio.to_thread(self.store.write_batch, batch)
        self.stored += len(batch)
        if self.cache is not None:
            try:
                await asyncio.to_thread(self.cache.publish_books, batch)
            except Exception as exc:
                LOG.warning("Redis cache unavailable; data is safely in PostgreSQL (%s)", type(exc).__name__)
        LOG.info("Persisted %s events (total=%s)", len(batch), self.stored)

    async def collect_market(
        self, market: MarketSnapshot, *, deadline: float | None = None
    ) -> int:
        tokens = validate_market(market, datetime.now(timezone.utc))
        # Independent connection per 5-minute contract; resets on reconnect or rollover.
        until = min(market.slot_end.timestamp(), deadline if deadline is not None else float("inf"))
        if until <= time.time():
            return 0
        params = dict(
            open_timeout=8, close_timeout=3, ping_interval=20,
            ping_timeout=15, max_size=2_000_000,
        )
        session_count = 0
        async with self.connector(WS_URL, **params) as ws:
            self.connections += 1
            self.last_market = market.slug
            await ws.send(json.dumps({
                "type": "market", "assets_ids": list(tokens),
                "custom_feature_enabled": True,
            }))
            LOG.info("Subscribed %s to 2 public CLOB tokens; no wallet", market.slug)
            heartbeat_task = asyncio.create_task(heartbeat(ws))
            batch: list[MarketObservation] = []
            last_flush = time.monotonic()
            last_message = time.monotonic()
            bad_messages = 0
            try:
                while time.time() < until:
                    wait = min(1.0, max(0.01, until - time.time()))
                    try:
                        frame = await asyncio.wait_for(ws.recv(), timeout=wait)
                    except asyncio.TimeoutError:
                        frame = None
                    if frame is not None:
                        last_message = time.monotonic()
                        try:
                            parsed = parse_market_message(frame, tokens)
                        except (StreamParseError, UnicodeDecodeError) as exc:
                            self.discarded += 1
                            bad_messages += 1
                            LOG.warning("Ignored malformed/out-of-contract feed event: %s", exc)
                            if bad_messages >= 10:
                                raise RuntimeError("Too many invalid frames; forcing clean reconnect")
                            continue
                        batch.extend(parsed)
                        session_count += len(parsed)
                    if len(batch) >= 32 or (batch and time.monotonic() - last_flush >= 1.0):
                        await self.persist(batch)
                        batch = []
                        last_flush = time.monotonic()
                    # With an application heartbeat every 10s, prolonged total
                    # silence is evidence of a broken subscription/session.
                    if time.monotonic() - last_message >= 35:
                        raise RuntimeError("WebSocket idle for 35 seconds; reconnect to fresh book")
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
                if batch:
                    # Preserve buffered events even on socket timeout/disconnection.
                    await asyncio.shield(self.persist(batch))
        return session_count

    async def run(self, *, duration_seconds: int = 0) -> None:
        if not 0 <= duration_seconds <= 86_400:
            raise ValueError("duration must be between 0 and 86400 seconds")
        deadline = time.time() + duration_seconds if duration_seconds else None
        failures = 0
        while deadline is None or time.time() < deadline:
            try:
                market = await self.discover()
                failures = 0
                await self.collect_market(market, deadline=deadline)
            except (asyncio.CancelledError, KeyboardInterrupt):
                raise
            except Exception as exc:
                # Never mask PostgreSQL write failure: it can cause an invisible
                # hole in the historic book; stop and alert rather than discard.
                import psycopg
                if isinstance(exc, psycopg.Error):
                    raise
                failures += 1
                LOG.warning("Read-only stream unavailable (%s: %s); retrying", type(exc).__name__, exc)
            delay = min(30.0, 2.0 * (2 ** min(failures, 4))) if failures else 0.5
            if deadline is not None:
                delay = min(delay, max(0.0, deadline - time.time()))
            if delay > 0:
                await asyncio.sleep(delay)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Polymarket BTC 5-minute market collector")
    parser.add_argument("--duration-seconds", type=int, default=0, help="0 runs until Ctrl-C; max 86400")
    parser.add_argument("--no-redis", action="store_true", help="Only write durable PostgreSQL observations")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)
    if not 0 <= args.duration_seconds <= 86_400:
        parser.error("--duration-seconds must be 0..86400")
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        engine = RealtimeCollector(cache=None if args.no_redis else StreamBookCache())
        asyncio.run(engine.run(duration_seconds=args.duration_seconds))
        print(f"Collector stopped: stored={engine.stored} discarded={engine.discarded} sessions={engine.connections}")
        return 0
    except KeyboardInterrupt:
        print("Collector stopped by operator")
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        LOG.error("Collector failed closed: %s: %s", type(exc).__name__, exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
