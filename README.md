# OpenPolyEngine — Research & Paper Trading

Security-first research foundation for Polymarket BTC Up/Down **5-minute** markets.

> **NO LIVE TRADING.** No private key, trading SDK, wallets, signed transactions,
> live order routes, or authorization to place any order.
>
> **PAPER TRADING** supports manual BUY/SELL with simulated USD only.
> `demo` is explicitly synthetic; `clob` refuses stale or absent real order books.

## Agent skills (Codex + Claude Code)

This repository includes the [CodeLocal Skills / master-skill](https://github.com/0xmarkhydra/master-skill) kit
at source revision `a0d9aa0`: nine skills under each of `.agents/skills/` (Codex)
and `.claude/skills/` (Claude Code). The install preserves project-specific
safety instructions in `AGENTS.md`; `CLAUDE.md` also directs agents to read
`AGENTS.md`. Third-party Ponytail MIT attribution lives under
`.codelocal-skills/ponytail/`. Skill files are instructions for coding
agents, **not executable plugins** or background automation.

To inspect installed skills, open `.agents/skills/backend-engineering/SKILL.md`,
`.agents/skills/react-frontend-engineering/SKILL.md`,
`.agents/skills/ios-inspired-ui-design/SKILL.md`, or
`.agents/skills/ponytail/SKILL.md`. For updates, review a newer upstream revision
before re-running the conflict-safe installer; do not blindly overwrite local policies.

## Core infrastructure

- **PostgreSQL 17 + TimescaleDB 2.30.2**: sole operational persistent database, hypertables for snapshots and future market observations.
- **Redis 7.4**: latest non-synthetic market snapshot cache and read-only update channel; TTL of 30 seconds.
- No local embedded operational database. JSONL is available only as an optional portable research export.
- Both ports are bound to **127.0.0.1**; database and Redis passwords required.
- Uses Psycopg 3, versioned idempotent SQL migrations, and parameterized queries.

## Local setup

Docker Desktop needs to be running; Python 3.11+ is required:

```bash
cd ~/Documents/OpenPolyBtcEngine
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

The local React/Vite market and paper-trading dashboard is available at **http://127.0.0.1:5173** when Vite is running.

Use two terminal windows from the project root:

```bash
# Terminal 1: run the local API, backed by PostgreSQL
.venv/bin/python -m services.api.server

# Terminal 2: run the read-only web dashboard
cd apps/dashboard
npm ci
npm run dev
```

The UI refreshes **persisted** snapshots every 12 seconds; it does NOT collect fresh Polymarket data by itself. Gamma snapshots and synthetic fixtures are labeled separately, with stale Gamma observations clearly flagged. API binds to 127.0.0.1:8787.

To scan separately, run `.venv/bin/python -m services.market_data.cli --slots 1 --persist --cache` from the project root. If the Gamma API is unreachable (for example, blocked/reset upstream), the scanner fails closed rather than inventing quotes.

## Phase 1B: Real-time public CLOB collector (read-only)

The collector is an **optional separate process**, not part of the web dashboard.
Install the updated Python dependencies and migrate PostgreSQL before running:

```bash
cd ~/Documents/OpenPolyBtcEngine
.venv/bin/python -m pip install -e .
.venv/bin/python -m services.market_data.migrate
.venv/bin/python -m services.market_data.collector --duration-seconds 45
```

It uses Gamma to discover verified current BTC 5m UP/DOWN token IDs, then subscribes to the public Polymarket CLOB **market WebSocket**; a socket reconnects after failure. It stores timestamped `book`, `price_change`, `last_trade_price`, `tick_size_change`, and `best_bid_ask` events in a TimescaleDB hypertable, using Redis TTL=20s for *complete-book* best bids/asks. No private keys or live trading support.

Read-only API adds `/api/orderbooks?slug=<market-slug>` and `/api/observations?slug=<market-slug>&limit=25`. The dashboard shows archived BBO and distinctly flags missing / stale data. **No claim of guaranteed, continuous, gap-free feed or executable quote.** Network access to Gamma may be unavailable on the local machine; if so the collector reports the failure and does not create synthetic data.

See [stream collector architecture and limitations](docs/STREAM_COLLECTOR.md).

## Phase 2A: Paper Trading with virtual dollars

The localhost dashboard now has a **Paper Trading** panel for both manual BUY UP / BUY DOWN and SELL ALL. Starting virtual balance is $1,000 per isolated account (`demo` vs `clob`), with a per-buy limit of $50, total open cost cap $250, simulated 0.5% fees, persistent position and cash ledger, and request idempotency. **No exchange orders are ever submitted.**

The offline demo uses explicitly **synthetic**, constant bid/ask 48¢/52¢ even if Gamma/CLOB is down. This supports testing UI/accounting only, not a predictive signal. CLOB Paper demands a fresh, verified real full-book event and will reject otherwise. There is **no automatic settlement, confirmed winning outcome, unrealized P&L, or verified exchange fees** yet. See [Paper Trading documentation](docs/PAPER_TRADING.md).

## Phase 1 scope

- UTC-aligned 300-second slots and strict UP/DOWN token mapping.
- Public Gamma API adapter that **only** makes bounded, timed GET requests with capped transient-error retry.
- PostgreSQL snapshot upserts and a read-only localhost API.
- Optional Redis cache; synthetic fixture snapshots can never be pushed to Redis.
- Fail-closed RiskGate that unconditionally rejects LIVE mode.
- No automatic database deletion or credential logging.

See `docs/ARCHITECTURE.md`, `docs/TASKS.md`, `docs/SECURITY.md`.
