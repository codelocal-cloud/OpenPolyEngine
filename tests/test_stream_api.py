"""Read-only HTTP regression checks for orderbook and archived observation endpoints."""
from datetime import datetime, timezone, timedelta
from http.client import HTTPConnection
import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from services.api.server import make_server

SLUG = "btc-updown-5m-1792386000"
AT = datetime.now(timezone.utc) - timedelta(minutes=10)


class FakeMarketStore:
    def verified_market(self, slug):
        if slug != SLUG:
            return None
        return {"token_up": "123456789012345", "token_down": "987654321098765",
                "slot_start": (datetime.now(timezone.utc)-timedelta(minutes=3)).isoformat(),
                "slot_end": (datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat(),
                "closed": False}


class FakeObservationStore:
    def __init__(self):
        self.calls = []

    def latest_book(self, token):
        self.calls.append(("book", token))
        if token == "123456789012345":
            return {"book": {"best_bid": "0.4", "best_ask": "0.6"}, "received_at": AT.isoformat(),
                    "observed_at": AT.isoformat(), "kind": "archived_full_book_snapshot"}
        return None

    def recent(self, slug, limit=50):
        self.calls.append(("recent", slug, limit))
        return [{"slug": slug, "outcome": "UP", "event_type": "book", "instrument": "123456789012345",
                 "observed_at": AT.isoformat(), "received_at": AT.isoformat(), "payload": {}}]


class StreamApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.observations = FakeObservationStore()
        cls.server = make_server(store=FakeMarketStore(), observation_store=cls.observations, port=0)
        cls.worker = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.worker.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(timeout=3)

    def get(self, suffix):
        with urlopen(self.origin + suffix, timeout=3) as response:
            return json.loads(response.read())

    def test_orderbooks_are_read_only_and_marked_stale(self):
        value = self.get(f"/api/orderbooks?slug={SLUG}")
        self.assertEqual(value["mode"], "READ_ONLY")
        self.assertFalse(value["live_trading_enabled"])
        self.assertEqual(value["books"]["UP"]["book"]["best_bid"], "0.4")
        self.assertTrue(value["books"]["UP"]["stale"])
        self.assertIsNone(value["books"]["DOWN"])

    def test_observations_bounded(self):
        out = self.get(f"/api/observations?slug={SLUG}&limit=7")
        self.assertEqual(out["count"], 1)
        self.assertIn(("recent", SLUG, 7), self.observations.calls)

    def test_invalid_request_never_reaches_storage(self):
        for suffix in ("/api/orderbooks?slug=bad", "/api/observations?slug=bad",
                       f"/api/observations?slug={SLUG}&limit=101"):
            with self.subTest(path=suffix), self.assertRaises(HTTPError) as error:
                self.get(suffix)
            self.assertEqual(error.exception.code, 400)

    def test_unknown_market_fails_closed(self):
        with self.assertRaises(HTTPError) as error:
            self.get("/api/orderbooks?slug=btc-updown-5m-1792386300")
        self.assertEqual(error.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
