"""Tests: production Paper Trading uses CLOB only; test rows roll back."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import unittest
from uuid import uuid4

from services.market_data.config import PostgresConfig
from services.market_data.models import MarketSnapshot, slot_slug
from services.market_data.storage import PostgresStore
from services.market_data.observation_storage import ObservationStore
from services.market_data.observations import MarketObservation
from services.paper_trading.engine import PaperEngine, PaperTradeRejected, parse_dollars, parse_request_id, MAX_TRADE


class PaperUnitTest(unittest.TestCase):
    def test_real_data_only_account_gate(self):
        paper = PaperEngine()
        for method, args in ((paper.state, ("demo",)), (paper.quote, ("demo", "UP")),
                             (paper.request_status, ("demo", str(uuid4()))),
                             (paper.execute, ("demo", {}))):
            with self.subTest(method=method.__name__), self.assertRaises(PaperTradeRejected):
                method(*args)

    def test_stake_guard(self):
        for raw in ("0.99", "51", "-1", "NaN", "Infinity", "abc", 10, True, "1000000000000000"):
            with self.subTest(raw=raw), self.assertRaises(PaperTradeRejected):
                parse_dollars(raw)
        self.assertEqual(parse_dollars("50"), MAX_TRADE)

    def test_request_id_uuid4_required(self):
        with self.assertRaises(PaperTradeRejected):
            parse_request_id("not-uuid")
        self.assertEqual(parse_request_id(str(uuid4())).version, 4)


@unittest.skipUnless(os.getenv("POLYBTC_RUN_DB_TESTS") == "1", "enable database tests")
class PaperIntegrationTest(unittest.TestCase):
    def test_real_clob_quote_buy_idempotency_sell_atomic(self):
        """Inject test-only verified-shaped events inside an uncommitted transaction."""
        import psycopg
        cfg = PostgresConfig.from_env()
        raw = psycopg.connect(**cfg.connect_kwargs())
        class Shared:
            def __enter__(self):
                return raw
            def __exit__(self, *args):
                return False

        paper = PaperEngine(config=cfg, connector=lambda **kw: Shared())
        now = datetime.now(timezone.utc)
        slug = slot_slug(now)
        epoch = int(slug.rsplit("-", 1)[1])
        up = str(10**49 + uuid4().int)
        down = str(11**49 + uuid4().int)
        snap = MarketSnapshot(
            slug=slug, market_id="test-only", slot_start=datetime.fromtimestamp(epoch,timezone.utc),
            slot_end=datetime.fromtimestamp(epoch+300,timezone.utc),
            fetched_at=now, token_up=up, token_down=down,
            price_up=None, price_down=None, active=True, closed=False,
            accepting_orders=True, resolution_source=None,
            fee_rate=Decimal("0.07"), fee_exponent=1,
        )
        book = MarketObservation(
            source="polymarket_clob_ws",source_event_id=uuid4().hex,
            observed_at=now-timedelta(seconds=2),
            received_at=now-timedelta(seconds=1), slug=slug, outcome="UP",
            instrument=up,event_type="book",
            payload={"bids":[{"price":"0.4","size":"100"}],
                     "asks":[{"price":"0.6","size":"100"}]},
        )
        try:
            PostgresStore(cfg,connector=lambda **kw: Shared()).write_snapshots([snap])
            ObservationStore(cfg,connector=lambda **kw: Shared()).write_batch([book])
            before = paper.state("clob")
            request = {"request_id":str(uuid4()),"side":"BUY","outcome":"UP","spend_usd":"10","slug":slug}
            buy = paper.execute("clob",request)
            self.assertFalse(buy["duplicate"])
            self.assertEqual(buy["source"],"polymarket_clob_ws")
            self.assertEqual(buy["mode"],"PAPER_ONLY")
            self.assertGreater(Decimal(buy["fee"]), Decimal("0"))
            self.assertLessEqual(-Decimal(buy["cash_delta"]), Decimal("10"))
            # 2026 market metadata test fee: C * 0.07 * 0.60 * 0.40,
            # unlike the old hardcoded 0.5% notional shortcut.
            self.assertEqual(Decimal(buy["fee"]), Decimal("0.27237"))
            self.assertEqual(paper.execute("clob",request)["duplicate"],True)
            self.assertTrue(paper.request_status("clob",request["request_id"])["found"])
            self.assertFalse(paper.request_status("clob",str(uuid4()))["found"])
            with self.assertRaises(PaperTradeRejected):
                paper.execute("clob",{**request,"spend_usd":"20"})
            self.assertEqual(len(paper.state("clob")["orders"]),len(before["orders"])+1)
            sell = paper.execute("clob",{
                "request_id":str(uuid4()),"side":"SELL","outcome":"UP","slug":slug,
            })
            self.assertLess(Decimal(sell["realized_pnl"]),0)
            self.assertEqual(len(paper.state("clob")["orders"]),len(before["orders"])+2)
        finally:
            raw.rollback()  # Entire integration fixture + trades were never committed.
            raw.close()


if __name__ == "__main__":
    unittest.main()
