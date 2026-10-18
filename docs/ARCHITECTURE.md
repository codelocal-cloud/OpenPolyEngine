# Architecture v0.2

Gamma public GET -> strict UTC 5m market parser -> Python scanner
-> durable PostgreSQL/TimescaleDB `market_snapshots` hypertable
-> optional short-lived Redis cache/update channel
-> localhost read-only API.

- PostgreSQL is the source of truth. No alternate database backend.
- TimescaleDB hypertables for `market_snapshots` and `market_observations`.
- Redis stores ephemeral, non-synthetic feed data; it is never a financial ledger.
- All timestamps stored as `TIMESTAMPTZ` in UTC. Original event resolutions are recorded as metadata.
- Tokens are strings to preserve their full decimal precision.
- Decimal values remain Decimal/NUMERIC, never binary float in persistence.
- Migrations run explicitly and are version tracked in `schema_migrations`.
- Public CLOB WebSocket subscriber collects book snapshots and timestamped delta events for current verified tokens, writes to `market_observations`, and optionally caches full-book BBO in Redis.
- Reconnect and 5-minute rollover reset socket state. Stored deltas are **not yet** reconstructable into a sequence-verified executable order book.
- Production secrets must come from a secret manager, not checked-in files.
- Backtest, risk, trading execution and dashboard are subsequent components.
