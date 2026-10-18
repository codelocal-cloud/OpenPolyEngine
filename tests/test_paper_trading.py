"""USD-only paper ledger tests, including rollback-isolated real PostgreSQL tests."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import unittest
from uuid import uuid4

from services.market_data.config import PostgresConfig
from services.paper_trading.engine import (
    PaperEngine, PaperTradeRejected, demo_quote, parse_dollars, parse_request_id,
    verified_clob_quote, MAX_TRADE, FEE_RATE,
)


class PaperUnitTest(unittest.TestCase):
    def test_demo_quotes_are_honestly_tagged_synthetic(self):
        now = datetime(2026,10,19,6,0,tzinfo=timezone.utc)
        q = demo_quote(now, "UP")
        self.assertEqual(q.source, "synthetic_demo")
        self.assertEqual(q.bid, Decimal("0.48"))
        self.assertEqual(q.ask, Decimal("0.52"))
        self.assertTrue(q.slug.startswith("paper-demo-btc-5m-"))
        self.assertIsNone(q.received_at)

    def test_stake_guard(self):
        for raw in ("0.99", "51", "-1", "NaN", "Infinity", "abc", 10, True, "1000000000000000"):
            with self.subTest(raw=raw), self.assertRaises(PaperTradeRejected):
                parse_dollars(raw)
        self.assertEqual(parse_dollars("50"), MAX_TRADE)

    def test_idempotency_requires_uuid4(self):
        with self.assertRaises(PaperTradeRejected):
            parse_request_id("not-uuid")
        self.assertEqual(parse_request_id(str(uuid4())).version, 4)


@unittest.skipUnless(os.getenv("POLYBTC_RUN_DB_TESTS") == "1", "enable Docker DB tests")
class PaperIntegrationTest(unittest.TestCase):
    def test_buy_duplicate_sell_is_atomic_and_rollback_isolated(self):
        """One real database transaction shared by the engine, always rolled back."""
        import psycopg
        cfg = PostgresConfig.from_env()
        raw = psycopg.connect(**cfg.connect_kwargs())
        class ReusedTransaction:
            def __enter__(self):
                return raw
            def __exit__(self, exc_type, exc, tb):
                return False
        paper = PaperEngine(config=cfg, connector=lambda **kw: ReusedTransaction())
        try:
            before = paper.state("demo")
            request = {"request_id": str(uuid4()), "side":"BUY", "outcome":"UP", "spend_usd":"10"}
            buy = paper.execute("demo", request)
            self.assertFalse(buy["duplicate"])
            self.assertEqual(buy["source"], "synthetic_demo")
            self.assertEqual(buy["mode"], "PAPER_ONLY")
            self.assertTrue(Decimal(buy["cash_delta"]) < 0)
            self.assertEqual(paper.execute("demo", request)["duplicate"], True)
            found = paper.request_status("demo", request["request_id"])
            self.assertTrue(found["found"])
            self.assertEqual(found["order"]["outcome"], "UP")
            self.assertEqual(found["order"]["side"], "BUY")
            self.assertFalse(paper.request_status("demo", str(uuid4()))["found"])
            self.assertFalse(paper.request_status("clob", request["request_id"])["found"])
            with self.assertRaises(PaperTradeRejected):
                paper.execute("demo", {**request, "spend_usd":"20"})
            after_buy = paper.state("demo")
            self.assertEqual(len(after_buy["orders"]), len(before["orders"]) + 1)
            self.assertTrue(len(after_buy["positions"]) >= 1)
            sale = paper.execute("demo", {
                "request_id":str(uuid4()), "side":"SELL", "outcome":"UP", "slug":buy["slug"],
            })
            self.assertEqual(sale["side"], "SELL")
            self.assertLess(Decimal(sale["realized_pnl"]), 0)
            after_sale = paper.state("demo")
            self.assertEqual(len(after_sale["orders"]), len(before["orders"]) + 2)
            self.assertLess(Decimal(after_sale["cash_balance"]), Decimal(before["cash_balance"]))
            with self.assertRaises(PaperTradeRejected):
                paper.execute("demo", {
                    "request_id": str(uuid4()), "side":"SELL", "outcome":"UP", "slug":buy["slug"],
                })
            with self.assertRaises(PaperTradeRejected):
                paper.execute("demo", {
                    "request_id": str(uuid4()), "side":"BUY", "outcome":"UP",
                    "spend_usd":"51"
                })
        finally:
            raw.rollback()  # No user demo balance/order/position can persist from this test.
            raw.close()


if __name__ == "__main__":
    unittest.main()
