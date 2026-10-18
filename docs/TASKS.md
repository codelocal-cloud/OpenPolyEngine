# PolyBTC roadmap

## Phase 1 — infrastructure / market discovery
- [x] Strict BTC 5-minute slot and token parsing
- [x] Public Gamma-only adapter, fail on schema/API errors
- [x] PostgreSQL 17 + TimescaleDB migrations
- [x] Parameterized snapshot upsert, latest-by-market read API
- [x] Redis TTL cache for live observations (never synthetic fixtures)
- [x] Localhost-only Docker infrastructure
- [x] Fail-closed no-LIVE RiskGate
- [x] Unit / API tests
- [ ] Run integration tests against Docker daemon and database
- [ ] Stream executable order-book depth with sequence/reconnect checks
- [ ] Verify per-market resolution rules and oracle provenance

## Phase 2+
- [ ] Timestamped market observations, lossless historical feeds
- [ ] Backtesting with no future leakage and realistic fills/fees
- [ ] Paper mode + quantitative risk limits and loss budgets
- [ ] React dashboard and operator audit log
- [ ] Isolated signer, full live order reconciliation, security audit
