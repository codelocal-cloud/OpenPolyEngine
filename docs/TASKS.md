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
- [x] Run PostgreSQL/TimescaleDB and Redis integration tests against local Docker
- [x] Implement fail-closed public market WebSocket event collector, verified token subscription, PING/reconnect and slot rollover
- [x] Persist timestamped event observations; dedupe by event digest; Redis full-book-only BBO with TTL
- [x] Add read-only observation/orderbook APIs and dashboard book panel
- [ ] Verify sustained, continuous 24/7 ingestion against live Gamma/CLOB from an allowed network
- [ ] Implement complete order-book reconstruction with sequence/gap reconciliation; current version archives snapshots/deltas only
- [ ] Verify per-market resolution rules and oracle provenance

## Phase 2+
- [x] Versioned schema for timestamped market observations; initial ingestion code (not verified lossless)
- [ ] Audit and prove lossless ingestion / historical completeness under sustained real traffic
- [ ] Backtesting with no future leakage and realistic fills/fees
- [x] Paper Trading now operates on verified CLOB quotes only; legacy demo records retained solely for audit, demo API disabled, synthetic CLI ingestion removed
- [x] Reject unreconciled CLOB order-book deltas and clock ties; recover ambiguous paper POSTs using idempotent request lookup
- [ ] Verified market resolution, automated settlement and long-run quantitative risk controls
- [x] React read-only dashboard, historical snapshots and stale order-book indicator
- [ ] Operator audit log and production monitoring
- [ ] Isolated signer, full live order reconciliation, security audit
