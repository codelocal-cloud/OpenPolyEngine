import json
from pathlib import Path
import unittest

from services.market_data.cache import RedisCache
from services.market_data.config import RedisConfig
from services.market_data.models import parse_event

FIXTURE = Path(__file__).parent / "fixtures" / "btc_event.json"
EVENT = json.loads(FIXTURE.read_text())


class FakePipeline:
    def __init__(self):
        self.commands = []
        self.executed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def set(self, *args, **kwargs):
        self.commands.append(("set", args, kwargs))

    def publish(self, *args, **kwargs):
        self.commands.append(("publish", args, kwargs))

    def execute(self):
        self.executed = True


class FakeRedis:
    def __init__(self):
        self.pipe = FakePipeline()

    def pipeline(self, **kwargs):
        return self.pipe


class RedisCacheTest(unittest.TestCase):
    def test_real_gamma_updates_ttl_and_publishes(self):
        cache = RedisCache(RedisConfig("localhost", 6379, "test"))
        cache.client = FakeRedis()
        snap = parse_event(EVENT, EVENT["slug"])
        self.assertEqual(cache.publish([snap]), 1)
        self.assertTrue(cache.client.pipe.executed)
        self.assertEqual(cache.client.pipe.commands[0][2]["ex"], 30)
        self.assertEqual(cache.client.pipe.commands[1][0], "publish")

    def test_fixture_never_enters_realtime_cache(self):
        cache = RedisCache(RedisConfig("localhost", 6379, "test"))
        cache.client = FakeRedis()
        snap = parse_event(EVENT, EVENT["slug"], data_source="offline_fixture")
        self.assertEqual(cache.publish([snap]), 0)
        self.assertFalse(cache.client.pipe.executed)


if __name__ == "__main__":
    unittest.main()
