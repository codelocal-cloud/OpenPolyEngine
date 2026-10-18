from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services.market_data.cli import main
from services.market_data.config import PostgresConfig
from services.market_data.models import parse_event
from services.market_data.storage import PostgresStore, append_jsonl

FIXTURE = Path(__file__).parent / "fixtures" / "btc_event.json"
EVENT = json.loads(FIXTURE.read_text())
AT = datetime(2026, 10, 19, 0, 0, 30, tzinfo=timezone.utc)
CONFIG = PostgresConfig("localhost", 55432, "test", "test", "test-only")


class FakeCursor:
    def __init__(self, returned=None):
        self.statements = []
        self.returned = returned or []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def execute(self, sql, args=None):
        self.statements.append((sql, args))
        return self

    def fetchall(self):
        return self.returned


class FakeConnection:
    def __init__(self, returned=None):
        self.cur = FakeCursor(returned=returned)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def cursor(self):
        return self.cur


class StorageCliTest(unittest.TestCase):
    def test_postgres_writes_parameterized_upsert(self):
        connection = FakeConnection()
        store = PostgresStore(CONFIG, connector=lambda **kw: connection)
        market = parse_event(EVENT, EVENT["slug"], fetched_at=AT)
        self.assertEqual(store.write_snapshots([market]), 1)
        self.assertEqual(len(connection.cur.statements), 1)
        sql, params = connection.cur.statements[0]
        self.assertIn("ON CONFLICT (slug, fetched_at)", sql)
        self.assertEqual(params["token_up"], market.token_up)
        self.assertNotIn(market.token_up, sql)

    def test_postgres_empty_batch_does_not_connect(self):
        def unexpected(**kwargs):
            self.fail("No empty-batch connection allowed")
        store = PostgresStore(CONFIG, connector=unexpected)
        self.assertEqual(store.write_snapshots([]), 0)

    def test_latest_snapshots_query_is_bounded(self):
        expected = {"slug": EVENT["slug"], "data_source": "gamma_public"}
        connection = FakeConnection(returned=[(expected,)])
        store = PostgresStore(CONFIG, connector=lambda **kw: connection)
        self.assertEqual(store.recent_snapshots(2), [expected])
        self.assertEqual(connection.cur.statements[0][1], (2,))
        for limit in (0, 51):
            with self.assertRaises(ValueError):
                store.recent_snapshots(limit)

    def test_jsonl_is_optional_research_export(self):
        market = parse_event(EVENT, EVENT["slug"], fetched_at=AT)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "observations.jsonl"
            append_jsonl(path, [market])
            self.assertEqual(json.loads(path.read_text().strip())["slug"], EVENT["slug"])

    def test_offline_cli_without_database(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--slots", "1", "--at", AT.isoformat(),
                         "--offline-fixture", str(FIXTURE), "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["mode"], "READ_ONLY")
        self.assertEqual(payload["results"][0]["market"]["data_source"], "offline_fixture")

    def test_offline_cli_persists_only_when_requested(self):
        with patch("services.market_data.cli.PostgresStore") as postgres:
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(["--slots", "1", "--at", AT.isoformat(),
                                       "--offline-fixture", str(FIXTURE), "--persist"]), 0)
            postgres.return_value.write_snapshots.assert_called_once()
            self.assertEqual(postgres.return_value.write_snapshots.call_args.args[0][0].data_source, "offline_fixture")

    def test_cli_rejects_naive_timestamp(self):
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(["--at", "2026-10-19T00:00:00"])
        self.assertEqual(error.exception.code, 2)

    def test_cli_forbids_fixture_redis_publish(self):
        with redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as error:
            main(["--offline-fixture", str(FIXTURE), "--slots", "1", "--cache"])
        self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
