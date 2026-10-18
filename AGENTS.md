# PolyBTC engineering rules

- PostgreSQL 17 + TimescaleDB are the **only operational SQL datastore**. Never introduce embedded database fallbacks, local financial ledgers or temporary alternative production storage.
- Redis handles ephemeral messages/latest observations only; PostgreSQL remains the durable source of truth.
- All schema changes MUST go through ordered, transactional `database/migrations/*.sql`, with integration tests against the real Docker instance.
- Write timestamped, provenance-tagged market observations. Never treat indicative Gamma prices as executable quotes.
- Never store private keys, seed phrases, credentials or wallet permissions in repository files or logs.
- Live trading MUST remain physically unavailable in Phase 1; only a separately reviewed and authorized feature can introduce it.
- Default to failing closed on stale market data, incompatible schemas, unknown market outcomes or provider errors.
- Keep unit tests independent of Docker while integration tests can use the Docker-managed instances.
- Avoid destructive Docker volume operations. Never erase or overwrite trading research data implicitly.
- Before pushing, run Python tests, database integration tests (when engine available), and check staged files for secrets.
