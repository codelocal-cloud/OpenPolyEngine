from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from services.api.server import make_server, recent_snapshots

FIXTURE = Path(__file__).parent / "fixtures" / "btc_event.json"
EVENT = json.loads(FIXTURE.read_text())


class FakeStore:
    def __init__(self):
        self.calls = []

    def recent_snapshots(self, limit):
        self.calls.append(limit)
        return [{"slug": EVENT["slug"], "data_source": "gamma_public"}]


class ApiTest(unittest.TestCase):
    def test_recent_snapshots_calls_postgres_store(self):
        store = FakeStore()
        self.assertEqual(recent_snapshots(3, store=store)[0]["slug"], EVENT["slug"])
        self.assertEqual(store.calls, [3])

    def test_http_get_and_post_blocked(self):
        store = FakeStore()
        server = make_server(store=store, port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            origin = f"http://127.0.0.1:{server.server_port}"
            with urlopen(origin + "/api/markets?limit=2", timeout=2) as response:
                payload = json.loads(response.read())
                self.assertEqual(payload["mode"], "READ_ONLY")
                self.assertEqual(payload["count"], 1)
            self.assertEqual(store.calls, [2])
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(origin + "/api/markets", data=b"{}", method="POST"), timeout=2)
            self.assertEqual(error.exception.code, 405)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def test_bad_limit_returns_400(self):
        server = make_server(store=FakeStore(), port=0)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with self.assertRaises(HTTPError) as error:
                urlopen(f"http://127.0.0.1:{server.server_port}/api/markets?limit=100", timeout=2)
            self.assertEqual(error.exception.code, 400)
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
