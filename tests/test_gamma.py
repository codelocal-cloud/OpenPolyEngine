from datetime import datetime, timezone
import io
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
import unittest

from services.market_data.gamma import GammaClient, GammaError
from services.market_data.models import MarketParseError

FIXTURE = Path(__file__).parent / "fixtures" / "btc_event.json"
EVENT = json.loads(FIXTURE.read_text())


class GammaClientTest(unittest.TestCase):
    def test_fetch_uses_only_public_get_endpoint(self):
        requests = []
        def fake_open(req, timeout):
            requests.append((req.get_method(), req.full_url, timeout))
            return io.BytesIO(json.dumps(EVENT).encode())
        client = GammaClient(opener=fake_open)
        market = client.fetch_snapshot(EVENT["slug"], fetched_at=datetime.now(timezone.utc))
        self.assertEqual(market.token_up, "111111111111")
        self.assertEqual(requests, [
            ("GET", f"https://gamma-api.polymarket.com/events/slug/{EVENT['slug']}", 7.0)
        ])

    def test_404_is_not_found(self):
        def missing(req, timeout):
            raise HTTPError(req.full_url, 404, "Not Found", {}, None)
        self.assertIsNone(GammaClient(opener=missing).fetch_event(EVENT["slug"]))

    def test_500_is_error_not_missing(self):
        def broken(req, timeout):
            raise HTTPError(req.full_url, 500, "Error", {}, None)
        with self.assertRaises(GammaError):
            GammaClient(opener=broken, retries=0).fetch_event(EVENT["slug"])

    def test_rejects_oversized_payload(self):
        from services.market_data.gamma import MAX_BODY_BYTES
        def huge(req, timeout):
            return io.BytesIO(b"a" * (MAX_BODY_BYTES + 1))
        with self.assertRaises(GammaError):
            GammaClient(opener=huge).fetch_event(EVENT["slug"])

    def test_rejects_wrong_slug_before_any_network_call(self):
        def unexpected(req, timeout):
            self.fail("Network must not be accessed")
        with self.assertRaises(MarketParseError):
            GammaClient(opener=unexpected).fetch_event("https://evil.example/key")

    def test_transient_error_retries_then_succeeds(self):
        calls = []
        def flaky(req, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise URLError("temporary disconnect")
            return io.BytesIO(json.dumps(EVENT).encode())
        result = GammaClient(opener=flaky, retries=1, sleep=lambda _: None).fetch_event(EVENT["slug"])
        self.assertEqual(result["slug"], EVENT["slug"])
        self.assertEqual(len(calls), 2)

    def test_invalid_json_not_silently_ignored(self):
        with self.assertRaises(GammaError):
            GammaClient(opener=lambda req, timeout: io.BytesIO(b"not-json")).fetch_event(EVENT["slug"])


if __name__ == "__main__":
    unittest.main()
