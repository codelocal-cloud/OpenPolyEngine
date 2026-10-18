"""Opt-in PostgreSQL/TimescaleDB integration tests using the Docker container."""
import os
import unittest
from datetime import datetime, timezone
import json
from pathlib import Path

from services.market_data.config import PostgresConfig, RedisConfig
from services.market_data.migrate import migrate
from services.market_data.models import parse_event
from services.market_data.storage import PostgresStore
from services.market_data.cache import RedisCache


FIXTURE = Path(__file__).parent / "fixtures" / "btc_event.json"
EVENT = json.loads(FIXTURE.read_text())


@unittest.skipUnless(os.getenv("POLYBTC_RUN_DB_TESTS") == "1", "set POLYBTC_RUN_DB_TESTS=1")
class PostgresIntegrationTest(unittest.TestCase):
    def test_migrate_and_snapshot_roundtrip(self):
        import psycopg
        config = PostgresConfig.from_env()
        migrate(config)
        store = PostgresStore(config)
        at = datetime(2026, 10, 19, 0, 0, 23, tzinfo=timezone.utc)
        synthetic = parse_event(EVENT, EVENT["slug"], fetched_at=at, data_source="offline_fixture")
        self.assertEqual(store.write_snapshots([synthetic]), 1)
        self.assertEqual(store.write_snapshots([synthetic]), 1)
        latest = store.recent_snapshots(50)
        self.assertIn(synthetic.slug, [r["slug"] for r in latest])
        with psycopg.connect(**config.connect_kwargs()) as con:
            hypertable = con.execute(
                "SELECT COUNT(*) FROM timescaledb_information.hypertables WHERE hypertable_name='market_snapshots'"
            ).fetchone()[0]
            self.assertEqual(hypertable, 1)
            count = con.execute(
                "SELECT COUNT(*) FROM market_snapshots WHERE slug=%s AND fetched_at=%s",
                (synthetic.slug, synthetic.fetched_at),
            ).fetchone()[0]
            self.assertEqual(count, 1)


@unittest.skipUnless(os.getenv("POLYBTC_RUN_REDIS_TESTS") == "1", "set POLYBTC_RUN_REDIS_TESTS=1")
class RedisIntegrationTest(unittest.TestCase):
    def test_cache_roundtrip(self):
        cache = RedisCache(RedisConfig.from_env())
        key = "polybtc:test:connection"
        cache.client.set(key, "read-only-check", ex=30)
        self.assertEqual(cache.client.get(key), "read-only-check")
        ttl = cache.client.ttl(key)
        self.assertTrue(0 < ttl <= 30)
        cache.client.delete(key)


if __name__ == "__main__":
    unittest.main()
