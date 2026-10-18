from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ArchitectureGuardTest(unittest.TestCase):
    def test_no_embedded_database_in_runtime(self):
        for f in (ROOT / "services").rglob("*.py"):
            content = f.read_text()
            self.assertNotIn("import sqlite3", content, str(f))
            self.assertNotIn("import aiosqlite", content, str(f))
            self.assertNotIn("save_sqlite", content, str(f))
        self.assertTrue((ROOT / "database" / "migrations" / "001_market_snapshots.sql").exists())

    def test_compose_ports_bound_to_loopback(self):
        content = (ROOT / "compose.yaml").read_text()
        self.assertIn("127.0.0.1:", content)
        self.assertIn("timescale/timescaledb:2.30.2-pg17", content)
        self.assertIn("redis:7.4-alpine", content)

    def test_trading_engine_not_implemented(self):
        gate = (ROOT / "services" / "risk_engine" / "gate.py").read_text()
        self.assertIn("No live execution code is installed in Phase 1", gate)


if __name__ == "__main__":
    unittest.main()
