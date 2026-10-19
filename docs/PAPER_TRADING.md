# Paper Trading — Real Data Only

Only the `clob` virtual account can be used. Historic `demo` data is retained
in PostgreSQL but inaccessible through Paper API routes. No client can place
live exchange orders.

## Authoritative inputs
- Current exact slug `btc-updown-5m-<UTC epoch>` in Gamma, verified UP/DOWN token IDs.
- Gamma `feeSchedule.rate` and `feeSchedule.exponent == 1`, recorded with the
  market snapshot. **No guessed fees**. Missing schedule blocks execution.
- A complete public CLOB orderbook from Polymarket, received within the last
  10 seconds, without subsequent unreconciled price/tick/BBO changes. Missing
  or stale snapshots block orders.
- Signed/filled positions are **simulated only** and written transactionally to
  PostgreSQL 17. No wallet connections.

## Execution approximation

Paper BUY spends a specified $1–$50 in virtual cash (including modeled taker
fee) at the best ask. SELL ALL closes at best bid when the current market is
still active and liquidity suffices. No market-order routing, slippage across
levels, maker queue, real fills or automated settlement.

Fee estimation follows Polymarket's publicly documented crypto taker formula:
`fee = shares × feeRate × price × (1 − price)` (5 decimals). The feeRate is
read from the **current market's actual Gamma metadata**, never hardcoded.
Actual exchange BUY fees may be collected in shares, so this paper ledger
still approximates rather than reproduces the exact CLOB fill cashflow.

Limits: $1–$50 per BUY, max $250 open cost basis, 6 open positions, no leverage
or short positions. UUID v4 idempotency and a locked PostgreSQL account row
avoid duplicate cash mutations from retries.

## API
- `GET /api/paper/state?account=clob`
- `GET /api/paper/quote?account=clob&outcome=UP|DOWN` (HTTP 422 if quote stale/unverified)
- `GET /api/paper/request?account=clob&request_id=<UUID-v4>`
- `POST /api/paper/orders?account=clob` with JSON
  `{"request_id":"<UUID-v4>","side":"BUY","outcome":"UP","spend_usd":"10","slug":"btc-updown-5m-..."}`
  and `X-OpenPoly-Paper: 1`; localhost origin/host required.
  SELL ALL omits spend_usd and includes the current slug.

`account=demo` is intentionally rejected with HTTP 422 for state/quote/order
lookups and POSTs. Other private/live order routes remain disabled.

## Source availability

The Mac's direct TLS connection to official Gamma/CLOB endpoints was reset.
This is an **upstream connectivity blocker**, not permission to synthesize
live market data or route through unofficial mirrors. If not connected,
dashboard says "unavailable", and order controls remain disabled. Verify network,
device clock and supported jurisdiction before trying again.

Use `docs/STREAM_COLLECTOR.md` for collector operation. Data fixtures are
confined to isolated automated tests and do not enter user-facing queries.
