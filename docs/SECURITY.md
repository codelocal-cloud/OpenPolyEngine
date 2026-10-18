# Security invariants

1. Phase 1 has zero signed orders, wallet access, private keys, or live trading route.
2. Data ingestion is public HTTPS GET only with whitelistable market slug, 7s timeout and 2 MB max JSON.
3. Database and Redis are local-only ports and use unique required credentials.
4. The read-only API binds to 127.0.0.1 and rejects all mutating HTTP methods.
5. Redis TTL = 30s; no credentials or personal data are cached.
6. Synthetic fixture observations are labeled and cannot enter the real-time cache.
7. Raw market metadata prices are not executable CLOB quotes; never treated as assured fills.
8. Backtesting and signing must be isolated from the trading executor in a later audited phase.
9. Do not invoke `docker compose down -v` on a populated environment: this deletes database volumes.
10. Backups/restores, least-privilege application roles, alerting and credential rotation are necessary before production.

Both local infrastructure ports are for development, not public Internet access.
