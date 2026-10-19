# OpenPolyEngine — Real Polymarket data only

Open-source BTC Up/Down 5-minute research and **paper-only** execution with PostgreSQL 17 + TimescaleDB and Redis.

**No demo market data, no fabricated prices, no private keys, and no live orders.**
The dashboard never displays historical fixtures as current prices. Its BUY/SELL
buttons remain disabled until both verified current BTC 5-minute market metadata
and a fresh, complete public Polymarket CLOB orderbook are available. The engine
also requires an **official feeSchedule from Gamma**: when fee metadata is absent
or a price-changing delta overtakes the snapshot, it refuses to simulate a fill.

## Run on macOS

```bash
cd ~/Documents/OpenPolyBtcEngine
docker compose up -d
.venv/bin/python -m pip install -e .
.venv/bin/python -m services.market_data.migrate

# Terminal 1: public CLOB collector (NO real trading)
.venv/bin/python -m services.market_data.collector

# Terminal 2: local-only read-only/paper API
.venv/bin/python -m services.api.server

# Terminal 3: dashboard
cd apps/dashboard
npm ci
npm run dev
```

Open [http://127.0.0.1:5173/](http://127.0.0.1:5173/) on that computer.

The dashboard refreshes every 5 seconds. It always shows the UTC current slot,
the actual public CLOB best bid/ask *only when sufficiently fresh*, the
simulation-only CLOB cash ledger, positions and last orders. In the absence of
verified live data the screen displays **offline / unavailable** and locks trades.

## Market data

- **Gamma API** is the authoritative source of slug/token mapping, market
  schedule, closed/active state and market-specific `feeSchedule`. Snapshot
  prices (`outcomePrices`) are indicative **not** executable order prices.
- **Public CLOB WebSocket** delivers full `book` snapshots, `price_change`,
  `last_trade_price`, `best_bid_ask` and `tick_size_change` events.
  TimescaleDB stores normalized observations and provenance; Redis caches
  fresh full-book quotes for 20 seconds.
- **Paper Trading** uses the *real* CLOB full-book bid and ask, with strict
  freshness, no subsequent unreconciled book deltas, Gamma feeSchedule validation,
  USD-virtual balance and bounded risk checks. A simulated full fill is NOT
  proof that a real market order would execute at that exact price.
- All public UI/API `/api/markets` rows are filtered to `gamma_public`.
  Historical synthetic research rows remain in the database for audit, but no
  production CLI/endpoint accepts fixtures or generates sample prices.
- Existing `demo` paper records are preserved for audit but the `demo` account
  is **disabled at the backend**, not merely hidden in the UI.

**Important network limitation:** On the Mac previously tested, TLS connections
to `gamma-api.polymarket.com`, `clob.polymarket.com` and
`data-api.polymarket.com` were reset by peer. Until you have legitimate direct
access to Polymarket public APIs, no tool can honestly deliver live quotes.
We never create substitute quotes, relabel archived prices, or bypass
Polymarket geographic restrictions.

## Safety

- Local API binds to `127.0.0.1:8787` and never signs or sends live orders.
- The virtual `clob` account starts with $1,000 *simulated USD*, has $1–$50
  BUY orders and a $250 maximum cost exposure. No automatic market settlement.
- Paper taker fee uses the per-market Gamma schedule and the publicly documented
  formula `fee = shares * feeRate * price * (1 - price)`; if missing, no fill.
  Simulation still estimates fill/fees, not matched venue execution.
- Transactional ledger, account locks and UUID v4 idempotency prevent double
  bookkeeping on retries.
- **No SQLite**, no destructive Docker volume operations, no credentials committed.

See [Paper Trading](docs/PAPER_TRADING.md) and
[Public CLOB collector](docs/STREAM_COLLECTOR.md) for detailed limitations.

## Tests

```bash
POLYBTC_RUN_DB_TESTS=1 POLYBTC_RUN_REDIS_TESTS=1 \
  .venv/bin/python -m unittest discover -s tests -q
cd apps/dashboard && npm run build
```

Automated parser and database tests use bounded, rollback-only fixture records;
**they are never inserted as live data or rendered in the product**.

## Development guidance

Codex and Claude Code skills are installed in `.agents/skills` and
`.claude/skills`, including `ios-inspired-ui-design`. Project-specific safety
rules in `AGENTS.md` take precedence. Upstream kit:
[0xmarkhydra/master-skill](https://github.com/0xmarkhydra/master-skill).
