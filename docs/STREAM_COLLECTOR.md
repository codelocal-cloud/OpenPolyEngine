# Public CLOB market WebSocket collector

## Scope and safety

- Endpoint: `wss://ws-subscriptions-clob.polymarket.com/ws/market` (public market channel).
- Subscribes to the UP and DOWN *CLOB token IDs* for the **current** verified BTC 5-minute event obtained from Gamma. No wallet, secret, user channel or execution API.
- Archives validated **full book snapshots**, `price_change`, `last_trade_price`, `tick_size_change`, and `best_bid_ask` observations in TimescaleDB hypertable `market_observations`.
- Includes provider observation time, local receive time, source, event type, token and SHA-256 event fingerprint. Duplicate source events are ignored by PostgreSQL.
- Reconnect discards in-memory state. **An incremental event by itself is never considered a complete order book.** The derived Redis BBO cache only accepts full `book` events, with a 20-second TTL.
- Scanner and collector can be stopped at any time. Failed upstream connections never trigger mock market prices.
- If database writes fail, collector stops rather than losing events silently. Redis is optional.

## Run

After setting up Docker and applying versioned migrations:

```bash
cd ~/Documents/OpenPolyBtcEngine
.venv/bin/python -m pip install -e .
.venv/bin/python -m services.market_data.migrate
# Run for a bounded smoke test (no order placement):
.venv/bin/python -m services.market_data.collector --duration-seconds 45
# Or run continuously in a dedicated terminal:
.venv/bin/python -m services.market_data.collector
```

Keep Gamma metadata separate from CLOB order-book prices. If the network blocks Gamma, discovery fails; no unverified contract IDs will be subscribed.

## Inspect read-only HTTP API

The local API serves:
- `GET /api/markets` — Gamma-verified market snapshots already stored.
- `GET /api/orderbooks?slug=btc-updown-5m-{epoch}` — archived **full book** per outcome, age/stale flag.
- `GET /api/observations?slug=btc-updown-5m-{epoch}&limit=25` — most recent raw normalized observations.

The dashboard at `http://127.0.0.1:5173` shows UP/DOWN BBO and marks absent or old snapshots as **STALE**.

## Known limitations

The system is a **market-data collector**, not a fully synchronized, executable trading book. It stores incremental events for audit/backtesting, but does not reconstruct an order book after each price change. WebSocket ordering, frame gaps, cross-network recovery, exchange reorgs, historical completeness and timestamp drift still need dedicated measurement and reconciliation before any trading code is allowed.

The initial observation hypertable retains data until the operator defines a retention/compression and backup policy. Raw traffic/throughput and Redis buffers need production load testing.

See [Polymarket WebSocket market-channel notes](https://github.com/Polymarket/agent-skills/blob/main/websocket.md) for event shapes and heartbeat behavior.
