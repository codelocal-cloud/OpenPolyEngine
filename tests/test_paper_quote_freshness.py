"""Read-only CLOB paper quotes must never use unreconciled orderbook deltas.

Uses an actual TimescaleDB transaction rolled back after each test, so fake
Gamma/CLOB test events are never persisted as real market observations.
"""
import os
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from services.market_data.config import PostgresConfig
from services.market_data.migrate import migrate
from services.market_data.models import MarketSnapshot, slot_slug
from services.market_data.observation_storage import ObservationStore
from services.market_data.observations import MarketObservation
from services.market_data.storage import PostgresStore
from services.paper_trading.engine import PaperTradeRejected, verified_clob_quote


@unittest.skipUnless(os.getenv("POLYBTC_RUN_DB_TESTS") == "1", "enable database integration tests")
class QuoteFreshnessTest(unittest.TestCase):
    def test_snapshot_rejected_after_newer_delta_until_resynchronized(self):
        import psycopg
        cfg = PostgresConfig.from_env()
        migrate(cfg)
        con = psycopg.connect(**cfg.connect_kwargs())
        class SharedTransaction:
            def __enter__(self):
                return con
            def __exit__(self, exc_type, exc, tb):
                return False
        now = datetime.now(timezone.utc)
        slug = slot_slug(now)
        slot_start = datetime.fromtimestamp(int(slug.rsplit("-",1)[1]), tz=timezone.utc)
        token_up = str(10 ** 50 + uuid4().int)
        token_down = str(11 ** 50 + uuid4().int)
        snapshot = MarketSnapshot(
            slug=slug, market_id="ephemeral-test", slot_start=slot_start,
            slot_end=slot_start+timedelta(seconds=300), fetched_at=now,
            token_up=token_up, token_down=token_down, price_up=Decimal("0.52"),
            price_down=Decimal("0.48"), active=True, closed=False,
            accepting_orders=True, resolution_source=None,
        )
        try:
            PostgresStore(cfg, connector=lambda **kw: SharedTransaction()).write_snapshots([snapshot])
            store = ObservationStore(cfg, connector=lambda **kw: SharedTransaction())

            def event(kind, offset, bid, ask):
                received = now + timedelta(seconds=offset)
                payload = (
                    {"bids":[{"price":bid,"size":"100"}],
                     "asks":[{"price":ask,"size":"100"}],
                     "best_bid":bid,"best_ask":ask}
                    if kind=="book"
                    else {"side":"BUY","price":bid,"size":"3"}
                )
                return MarketObservation(
                    source="polymarket_clob_ws", source_event_id=uuid4().hex,
                    observed_at=received-timedelta(milliseconds=50),
                    received_at=received, slug=slug, outcome="UP",
                    instrument=token_up, event_type=kind, payload=payload,
                )

            book = event("book", -4, "0.40", "0.60")
            store.write_batch([book])
            good = verified_clob_quote(con, now, "UP")
            self.assertEqual(good.ask, Decimal("0.60"))

            delta = event("price_change", -3, "0.45", "0.55")
            store.write_batch([delta])
            with self.assertRaisesRegex(PaperTradeRejected, "Orderbook changed"):
                verified_clob_quote(con, now, "UP")

            fresh_book = event("book", -2, "0.43", "0.57")
            store.write_batch([fresh_book])
            good = verified_clob_quote(con, now, "UP")
            self.assertEqual(good.ask, Decimal("0.57"))

            tied_delta = event("tick_size_change", -2, "0.01", "0.02")
            store.write_batch([tied_delta])
            with self.assertRaisesRegex(PaperTradeRejected, "book|snapshot|update"):
                verified_clob_quote(con, now, "UP")
        finally:
            con.rollback()
            con.close()


if __name__ == "__main__":
    unittest.main()
