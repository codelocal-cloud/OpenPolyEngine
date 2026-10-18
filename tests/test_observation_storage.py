from datetime import datetime, timezone
from unittest.mock import Mock
import unittest

from services.market_data.config import PostgresConfig
from services.market_data.observation_storage import ObservationStore

CONFIG = PostgresConfig("localhost", 55432, "test", "test", "test")


class Cursor:
    def __init__(self, result=None):
        self.statements=[]
        self.result=result
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def execute(self, sql, params):
        self.statements.append((sql, params))
    def fetchone(self):
        return self.result
    def fetchall(self):
        return self.result or []


class Connection:
    def __init__(self, row=None):
        self.cur=Cursor(row)
    def __enter__(self):
        return self
    def __exit__(self,*args):
        pass
    def cursor(self):
        return self.cur


class ObservationStorageTest(unittest.TestCase):
    def test_inserts_are_parameterized_and_idempotent(self):
        from services.market_data.observations import MarketObservation
        at = datetime(2026, 10, 19, 5, 0, tzinfo=timezone.utc)
        ev = MarketObservation("polymarket_clob_ws", "ab"*32, at, at,
                               "btc-updown-5m-1792386000", "UP", "123456789012345", "book",
                               {"best_bid": "0.3", "best_ask": "0.7"})
        con=Connection()
        repo=ObservationStore(CONFIG, connector=lambda **kw: con)
        self.assertEqual(repo.write_batch([ev]),1)
        query, arguments=con.cur.statements[0]
        self.assertIn("ON CONFLICT", query)
        self.assertNotIn(ev.instrument, query)
        self.assertEqual(arguments["outcome"], "UP")
        self.assertEqual(arguments["payload"].obj["best_bid"], "0.3")

    def test_latest_book_uses_bounded_select(self):
        at = datetime(2026, 10, 19, 5, 0, tzinfo=timezone.utc)
        con=Connection(({"best_bid":"0.3"}, at, at))
        repo=ObservationStore(CONFIG, connector=lambda **kw: con)
        book=repo.latest_book("123456789012345")
        self.assertEqual(book["book"]["best_bid"], "0.3")
        self.assertIn("LIMIT 1", con.cur.statements[0][0])
        with self.assertRaises(ValueError):
            repo.latest_book("not_a_token")

if __name__ == "__main__":
    unittest.main()
