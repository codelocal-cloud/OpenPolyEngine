# PolyBTC engineering rules

- PostgreSQL 17 + TimescaleDB are the **only operational SQL datastore**. Never introduce embedded database fallbacks, local financial ledgers or temporary alternative production storage.
- Redis handles ephemeral messages/latest observations only; PostgreSQL remains the durable source of truth.
- All schema changes MUST go through ordered, transactional `database/migrations/*.sql`, with integration tests against the real Docker instance.
- Write timestamped, provenance-tagged market observations. Never treat indicative Gamma prices as executable quotes.
- Never store private keys, seed phrases, credentials or wallet permissions in repository files or logs.
- Live trading MUST remain physically unavailable in Phase 1; only a separately reviewed and authorized feature can introduce it.
- Production is REAL DATA ONLY: no demo accounts, fixture ingestion, sample prices, synthetic market quotes, or fallback fake values exposed by API or dashboard. Historical legacy demo rows may remain for audit but cannot be traded. Only verified Gamma token mapping + feeSchedule and fresh public CLOB full-book snapshots can justify simulated paper fills.
- Paper orders must stay PostgreSQL-only, atomic and idempotent. Never substitute static fee assumptions for official per-market metadata; missing fees, stale quotes or book gaps must fail closed.
- Default to failing closed on stale market data, incompatible schemas, unknown market outcomes or provider errors.
- Keep unit tests independent of Docker while integration tests can use the Docker-managed instances.
- Avoid destructive Docker volume operations. Never erase or overwrite trading research data implicitly.
- Before pushing, run Python tests, database integration tests (when engine available), and check staged files for secrets.

<!-- CODELOCAL-SKILLS:BEGIN -->
## CodeLocal Skills — coding agent instructions

Before a coding task, inspect the repository, existing instructions, project stack,
Git state, affected workflows and contracts. Read the applicable skill(s), not all
nine indiscriminately:

- Server/API/DB/auth/security/migrations: .agents/skills/backend-engineering/SKILL.md and relevant references.
- React/Vite/Next.js frontend behavior, state/forms/API/routing/feature parity:
  .agents/skills/react-frontend-engineering/SKILL.md and relevant references.
- Design system, iOS-inspired UI, responsive, visual quality:
  .agents/skills/ios-inspired-ui-design/SKILL.md and relevant references.
- Any code creation/fix/refactor: additionally read .agents/skills/ponytail/SKILL.md.
  Apply Ponytail **Ultra** as a simplicity *decision policy*, not a plugin mode.
  Challenge unneeded complexity; reuse existing code/platform/dependencies first.
- On explicit review/audit/debt/benchmark/help requests, use
  .agents/skills/ponytail-review/SKILL.md, .agents/skills/ponytail-audit/SKILL.md,
  .agents/skills/ponytail-debt/SKILL.md, .agents/skills/ponytail-gain/SKILL.md, or
  .agents/skills/ponytail-help/SKILL.md as appropriate.

Precedence: project/user-approved scope, correctness, backend authorization, data
and API compatibility, feature parity, accessibility, tests and release safety
always beat code brevity (P0/P1 quality gates). Ponytail Ultra must NOT silently remove requirements,
validation, security checks, error handling or tests. Follow project branch/CI
policies. Report PASS/FAIL/NOT RUN/BLOCKED from evidence; do not invent success,
commit, push, merge, deployment or live testing.

This block was installed by CodeLocal Skills. Existing project instructions remain
in effect. Ponytail is third-party MIT-licensed; provenance is under
`.codelocal-skills/ponytail/`. No marketplace plugin or hooks are installed.
<!-- CODELOCAL-SKILLS:END -->
