import asyncio
from datetime import datetime, timezone, timedelta
import json
import unittest

from services.market_data.collector import RealtimeCollector, heartbeat, validate_market
from services.market_data.models import MarketSnapshot, slot_slug
from services.market_data.observations import parse_market_message
from services.market_data.stream_cache import StreamBookCache, BOOK_TTL_SECONDS


def current_market():
    now = datetime.now(timezone.utc)
    slug = slot_slug(now)
    start = datetime.fromtimestamp(int(slug.rsplit("-", 1)[1]), timezone.utc)
    return MarketSnapshot(
        slug=slug, market_id="1", slot_start=start, slot_end=start + timedelta(minutes=5),
        fetched_at=now, token_up="123456789012345", token_down="987654321098765",
        price_up=None, price_down=None, active=True, closed=False,
        accepting_orders=True, resolution_source=None,
    )


class FakeStore:
    def __init__(self):
        self.batches = []

    def write_batch(self, items):
        self.batches.append(items.copy())
        return len(items)


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.counter = 0
    async def send(self, value):
        self.sent.append(value)
    async def recv(self):
        self.counter += 1
        if self.counter == 1:
            return json.dumps({"event_type": "book", "asset_id": "123456789012345",
                               "timestamp": str(int(datetime.now(timezone.utc).timestamp() * 1000)),
                               "bids": [{"price": "0.4", "size": "3"}],
                               "asks": [{"price": "0.6", "size": "8"}]})
        await asyncio.sleep(0.2)
        return "PONG"


class FakeConnection:
    def __init__(self, sock):
        self.sock = sock
    async def __aenter__(self):
        return self.sock
    async def __aexit__(self, *args):
        pass


class FakePipeline:
    def __init__(self):
        self.commands = []
    def __enter__(self):
        return self
    def __exit__(self,*args):
        pass
    def set(self, key, value, ex):
        self.commands.append(("set", key, value, ex))
    def publish(self, *args):
        self.commands.append(("publish", *args))
    def execute(self):
        self.commands.append(("execute",))


class FakeRedis:
    def __init__(self):
        self.pipe=FakePipeline()
    def pipeline(self, transaction):
        return self.pipe


class CollectorTest(unittest.IsolatedAsyncioTestCase):
    async def test_discover_persists_verified_market_before_subscribe(self):
        class FakeGamma:
            def fetch_snapshot(self, slug):
                market = current_market()
                return market if market.slug == slug else None
        class FakeSnapshotStore:
            def __init__(self):
                self.saved = []
            def write_snapshots(self, snapshots):
                self.saved.extend(snapshots)
                return len(snapshots)
        snapshot_store = FakeSnapshotStore()
        engine = RealtimeCollector(
            gamma=FakeGamma(), store=FakeStore(), snapshot_store=snapshot_store,
        )
        result = await engine.discover()
        self.assertEqual(len(snapshot_store.saved), 1)
        self.assertEqual(snapshot_store.saved[0].slug, result.slug)
        self.assertEqual(snapshot_store.saved[0].data_source, "gamma_public")


    async def test_full_book_persisted_and_subscription_is_public_only(self):
        store = FakeStore()
        sock = FakeSocket()
        engine = RealtimeCollector(store=store, connector=lambda *a, **kw: FakeConnection(sock))
        count = await engine.collect_market(current_market(), deadline=__import__("time").time() + 0.12)
        self.assertEqual(count, 1)
        self.assertEqual(engine.stored, 1)
        self.assertEqual(len(store.batches), 1)
        subscription = json.loads(sock.sent[0])
        self.assertEqual(subscription["type"], "market")
        self.assertEqual(len(subscription["assets_ids"]), 2)
        self.assertNotIn("auth", subscription)

    async def test_fixture_must_not_be_live_streamed(self):
        market = current_market()
        from dataclasses import replace
        with self.assertRaises(ValueError):
            validate_market(replace(market, data_source="offline_fixture"), datetime.now(timezone.utc))

    async def test_market_must_match_current_slot(self):
        from dataclasses import replace
        current = current_market()
        with self.assertRaises(ValueError):
            validate_market(replace(current, slug="btc-updown-5m-1792300000"), datetime.now(timezone.utc))

    async def test_heartbeat_sends_ping(self):
        sock = FakeSocket()
        task = asyncio.create_task(heartbeat(sock, interval=0.01))
        await asyncio.sleep(.025)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertIn("PING", sock.sent)

    async def test_cache_only_takes_fresh_full_book(self):
        cache = object.__new__(StreamBookCache)
        cache.client = FakeRedis()
        market = current_market()
        raw = json.dumps({"event_type": "book", "asset_id": market.token_up,
                          "bids": [{"price": "0.1", "size": "2"}],
                          "asks": [{"price": "0.2", "size": "3"}]})
        from services.market_data.observations import SOURCE
        ev = parse_market_message(raw, {market.token_up: (market.slug,"UP")})[0]
        self.assertEqual(cache.publish_books([ev]), 1)
        self.assertEqual(cache.client.pipe.commands[0][-1], BOOK_TTL_SECONDS)
        from dataclasses import replace
        old = replace(ev, received_at=ev.received_at - timedelta(seconds=30))
        self.assertEqual(cache.publish_books([old]), 0)

if __name__ == "__main__":
    unittest.main()
