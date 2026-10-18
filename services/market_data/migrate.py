"""Apply idempotent versioned migrations to the PostgreSQL/TimescaleDB service."""
from __future__ import annotations

from pathlib import Path
import sys

import psycopg
from .config import PostgresConfig, REPO_ROOT


MIGRATIONS = REPO_ROOT / "database" / "migrations"


def migrate(config: PostgresConfig | None = None, root: Path = MIGRATIONS) -> list[str]:
    cfg = config or PostgresConfig.from_env()
    applied: list[str] = []
    with psycopg.connect(**cfg.connect_kwargs(), autocommit=True) as connection:
        connection.execute("""
          CREATE TABLE IF NOT EXISTS schema_migrations (
            name TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
          )
        """)
        for file in sorted(root.glob("*.sql")):
            if not file.name[:3].isdigit():
                raise ValueError(f"Migration filename must start with digits: {file.name}")
            exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE name = %s", (file.name,)
            ).fetchone()
            if exists:
                continue
            # Each file is transactionally applied with its migration marker.
            # Failures roll back entirely and stop the process.
            with connection.transaction():
                connection.execute(file.read_text(encoding="utf-8"))
                connection.execute(
                    "INSERT INTO schema_migrations(name) VALUES (%s)", (file.name,)
                )
            applied.append(file.name)
    return applied


def main() -> int:
    try:
        done = migrate()
    except (psycopg.Error, OSError, ValueError) as exc:
        print(f"Migration failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("PostgreSQL migrations: " + (", ".join(done) if done else "already current"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
