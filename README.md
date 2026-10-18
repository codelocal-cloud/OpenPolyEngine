# OpenPolyEngine — Phase 1 (read-only)

Security-first research foundation for Polymarket BTC Up/Down **5-minute** markets.

> **NO LIVE TRADING.** No private key, trading SDK, wallets, signed transactions,
> live order routes, or authorization to place any order.

## Core infrastructure

- **PostgreSQL 17 + TimescaleDB 2.30.2**: sole operational persistent database, hypertables for snapshots and future market observations.
- **Redis 7.4**: latest non-synthetic market snapshot cache and read-only update channel; TTL of 30 seconds.
- No local embedded operational database. JSONL is available only as an optional portable research export.
- Both ports are bound to **127.0.0.1**; database and Redis passwords required.
- Uses Psycopg 3, versioned idempotent SQL migrations, and parameterized queries.

## Local setup

Docker Desktop needs to be running; Python 3.11+ is required:

```bash
cd ~/Documents/polybtc-engine
python3 scripts/init_local_env.py
# Generates .env with independent random credentials and mode 0600.
docker compose up -d
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m services.market_data.migrate
.venv/bin/python -m unittest discover -s tests -v
```

### Fetch and persist current BTC 5-minute market snapshots

```bash
.venv/bin/python -m services.market_data.cli --slots 3 --persist --cache --json
.venv/bin/python -m services.api.server
# In a second terminal:
curl http://127.0.0.1:8787/api/markets
```

CLI without `--persist` or `--cache` works as GET-only discovery.
Snapshots from Gamma show **indicative prices** rather than executable bid/ask.
Do not rely on Gamma metadata for live trading, probability calibration, or settlement decisions.

For offline fixture unit tests, a running database isn't required:

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m services.market_data.cli --offline-fixture tests/fixtures/btc_event.json --slots 1 --at 2026-10-19T00:00:30+00:00
```

Integration tests use the local Docker database when `POLYBTC_RUN_DB_TESTS=1` and
`POLYBTC_RUN_REDIS_TESTS=1` are set.

## Open the dashboard locally

The read-only React/Vite dashboard is available at **http://127.0.0.1:5173** when Vite is running.

Use two terminal windows from the project root:

\`\`\`bash
# Terminal 1: run the local API, backed by PostgreSQL
.venv/bin/python -m services.api.server

# Terminal 2: run the read-only web dashboard
cd apps/dashboard
npm ci
npm run dev
\`\`\`

The UI refreshes **persisted** snapshots every 12 seconds; it does NOT collect fresh Polymarket data by itself. Gamma snapshots and synthetic fixtures are labeled separately, with stale Gamma observations clearly flagged. API binds to 127.0.0.1:8787.

To scan separately, run \`.venv/bin/python -m services.market_data.cli --slots 1 --persist --cache\` from the project root. If the Gamma API is unreachable (for example, blocked/reset upstream), the scanner fails closed rather than inventing quotes.

## Phase 1 scope

- UTC-aligned 300-second slots and strict UP/DOWN token mapping.
- Public Gamma API adapter that **only** makes bounded, timed GET requests with capped transient-error retry.
- PostgreSQL snapshot upserts and a read-only localhost API.
- Optional Redis cache; synthetic fixture snapshots can never be pushed to Redis.
- Fail-closed RiskGate that unconditionally rejects LIVE mode.
- No automatic database deletion or credential logging.

See `docs/ARCHITECTURE.md`, `docs/TASKS.md`, `docs/SECURITY.md`.
