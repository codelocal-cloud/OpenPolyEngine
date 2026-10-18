"""PostgreSQL-only local paper trades: durable, atomic, idempotent, cash backed.

Explicitly labelled synthetic DEMO mode works offline; CLOB mode requires
current/verified, fresh public CLOB order-book depth. Neither submits orders
or uses wallet, CLOB trading REST endpoints, or private keys.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any
from uuid import UUID, uuid4

import psycopg

from services.market_data.config import PostgresConfig
from services.market_data.models import slot_slug

ZERO = Decimal("0")
ONE = Decimal("1")
P = Decimal("0.000001")
FEE_RATE = Decimal("0.005")  # 0.5% *illustrative*, NOT a verified exchange fee.
MAX_TRADE = Decimal("50")
MIN_TRADE = Decimal("1")
MAX_EXPOSURE = Decimal("250")
MAX_OPEN_POSITIONS = 6
MAX_QUOTE_AGE_SECONDS = 10
DEMO_LIQUIDITY = Decimal("1000")  # synthetic shares, enough to close max $250 exposure.


class PaperTradeRejected(ValueError):
    """Expected risk/quote/request validation failure, no balance mutation."""


@dataclass(frozen=True)
class Quote:
    slug: str
    outcome: str
    token: str
    bid: Decimal
    ask: Decimal
    bid_size: Decimal
    ask_size: Decimal
    source: str
    received_at: datetime | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug, "outcome": self.outcome,
            "token_id": self.token, "best_bid": str(self.bid),
            "best_ask": str(self.ask), "bid_size": str(self.bid_size),
            "ask_size": str(self.ask_size), "source": self.source,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "fee_rate_assumed": str(FEE_RATE),
            "mode": "PAPER_ONLY",
        }


def money(value: Decimal) -> Decimal:
    return value.quantize(P, rounding=ROUND_DOWN)


def parse_dollars(raw: Any) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, str):
        raise PaperTradeRejected("Amount must be a decimal string in USD")
    if len(raw) > 20:
        raise PaperTradeRejected("Amount too long")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise PaperTradeRejected("Invalid USD amount") from exc
    if not amount.is_finite() or amount < MIN_TRADE or amount > MAX_TRADE or amount != money(amount):
        raise PaperTradeRejected("Paper spend must be $1–$50, at most 6 decimals")
    return amount


def parse_request_id(raw: Any) -> UUID:
    if not isinstance(raw, str):
        raise PaperTradeRejected("Missing request_id UUID")
    try:
        value = UUID(raw)
        if value.version != 4:
            raise ValueError("UUID must be v4")
        return value
    except (ValueError, AttributeError) as exc:
        raise PaperTradeRejected("request_id must be a UUID v4") from exc


def demo_quote(now: datetime, outcome: str) -> Quote:
    if outcome not in ("UP", "DOWN"):
        raise PaperTradeRejected("Invalid outcome")
    slug = "paper-demo-btc-5m-" + slot_slug(now).rsplit("-", 1)[1]
    return Quote(
        slug=slug, outcome=outcome, token=f"DEMO-{outcome}",
        bid=Decimal("0.48"), ask=Decimal("0.52"),
        bid_size=DEMO_LIQUIDITY, ask_size=DEMO_LIQUIDITY,
        source="synthetic_demo", received_at=None,
    )


def verified_clob_quote(con: psycopg.Connection, now: datetime, outcome: str) -> Quote:
    """Read current contract + genuine raw book with an age/depth guard."""
    slug = slot_slug(now)
    with con.cursor() as cur:
        cur.execute(
            """SELECT token_up, token_down, slot_start, slot_end,
                      active, closed, accepting_orders, fetched_at
               FROM market_snapshots
               WHERE slug = %s AND data_source = 'gamma_public'
               ORDER BY fetched_at DESC LIMIT 1""",
            (slug,),
        )
        market = cur.fetchone()
        if not market:
            raise PaperTradeRejected("Current Gamma verified market unavailable")
        up, down, start, end, active, closed, orders, fetched = market
        if not (start <= now < end and active and not closed and orders):
            raise PaperTradeRejected("Market is not accepting simulated trades")
        if not (0 <= (now - fetched).total_seconds() <= 45):
            raise PaperTradeRejected("Gamma market metadata stale")
        token = up if outcome == "UP" else down
        if not isinstance(token, str) or not token.isdigit():
            raise PaperTradeRejected("No verified token for outcome")
        cur.execute(
            """SELECT payload, observed_at, received_at
               FROM market_observations
               WHERE source = 'polymarket_clob_ws' AND event_type = 'book'
                 AND instrument = %s AND slug = %s
               ORDER BY observed_at DESC, received_at DESC LIMIT 1""",
            (token, slug),
        )
        book = cur.fetchone()
    if not book:
        raise PaperTradeRejected("No archived full CLOB orderbook")
    payload, observed_at, received_at = book
    if not (0 <= (now - received_at).total_seconds() <= MAX_QUOTE_AGE_SECONDS):
        raise PaperTradeRejected("Orderbook expired / clock drift")
    if observed_at > now or observed_at > received_at:
        raise PaperTradeRejected("Invalid exchange timestamp")
    bids = payload.get("bids")
    asks = payload.get("asks")
    if not isinstance(bids, list) or not isinstance(asks, list) or not bids or not asks:
        raise PaperTradeRejected("Both book sides and depth are required")
    try:
        bid_level = max(bids, key=lambda x: Decimal(str(x["price"])))
        ask_level = min(asks, key=lambda x: Decimal(str(x["price"])))
        bid, ask = Decimal(str(bid_level["price"])), Decimal(str(ask_level["price"]))
        bid_size = Decimal(str(bid_level["size"]))
        ask_size = Decimal(str(ask_level["size"]))
    except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
        raise PaperTradeRejected("Malformed book levels") from exc
    if not all(v.is_finite() for v in (bid, ask, bid_size, ask_size)):
        raise PaperTradeRejected("Nonfinite quote")
    if not (ZERO < bid < ask < ONE and bid_size > ZERO and ask_size > ZERO):
        raise PaperTradeRejected("Crossed/missing book depth")
    return Quote(slug, outcome, token, bid, ask, bid_size, ask_size, "polymarket_clob_ws", received_at)


class PaperEngine:
    def __init__(self, config: PostgresConfig | None = None, *, connector=None, clock=None):
        self.config = config or PostgresConfig.from_env()
        self.connector = connector or psycopg.connect
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _connect(self):
        return self.connector(**self.config.connect_kwargs())

    def quote(self, account: str, outcome: str) -> dict:
        if account not in ("demo", "clob") or outcome not in ("UP", "DOWN"):
            raise PaperTradeRejected("Invalid account or outcome")
        with self._connect() as con:
            now = self.clock()
            quote = demo_quote(now, outcome) if account == "demo" else verified_clob_quote(con, now, outcome)
        return quote.to_dict()

    def state(self, account: str) -> dict:
        if account not in ("demo", "clob"):
            raise PaperTradeRejected("Invalid paper account")
        with self._connect() as con:
            with con.cursor() as cur:
                cur.execute("SELECT cash_balance, starting_cash, realized_pnl FROM paper_accounts WHERE account_id=%s",
                            (account,))
                balance = cur.fetchone()
                if balance is None:
                    raise RuntimeError("Paper accounts missing: run migration 004")
                cur.execute(
                    """SELECT slug, outcome, token_id, quantity, cost_basis, source, created_at
                       FROM paper_positions WHERE account_id=%s ORDER BY created_at DESC""", (account,))
                positions = cur.fetchall()
                cur.execute(
                    """SELECT order_id, request_id, side, slug, outcome, quantity, price,
                              notional, fee, cash_delta, realized_pnl, source, executed_at
                       FROM paper_orders WHERE account_id=%s
                       ORDER BY executed_at DESC LIMIT 50""", (account,))
                orders = cur.fetchall()
        return {
            "mode": "PAPER_ONLY", "account": account, "currency": "VIRTUAL_USD",
            "cash_balance": str(balance[0]), "starting_cash": str(balance[1]),
            "realized_pnl": str(balance[2]), "max_trade_usd": str(MAX_TRADE),
            "max_exposure_usd": str(MAX_EXPOSURE), "fee_rate_assumed": str(FEE_RATE),
            "valuation_status": "UNAVAILABLE_NO_SETTLEMENT_OR_MARK_PRICE",
            "positions": [
                {"slug": row[0], "outcome": row[1], "token_id": row[2],
                 "quantity": str(row[3]), "cost_basis": str(row[4]), "source": row[5],
                 "created_at": row[6].isoformat()}
                for row in positions
            ],
            "orders": [
                {"order_id": str(row[0]), "request_id": str(row[1]), "side": row[2],
                 "slug": row[3], "outcome": row[4], "quantity": str(row[5]),
                 "price": str(row[6]), "notional": str(row[7]), "fee": str(row[8]),
                 "cash_delta": str(row[9]),
                 "realized_pnl": str(row[10]) if row[10] is not None else None,
                 "source": row[11], "executed_at": row[12].isoformat()}
                for row in orders
            ],
        }

    def execute(self, account: str, req: dict) -> dict:
        if account not in ("demo", "clob") or not isinstance(req, dict):
            raise PaperTradeRejected("Invalid paper account/request")
        if set(req) - {"request_id", "side", "outcome", "spend_usd", "slug"}:
            raise PaperTradeRejected("Unsupported request fields")
        side, outcome = req.get("side"), req.get("outcome")
        if side not in ("BUY", "SELL") or outcome not in ("UP", "DOWN"):
            raise PaperTradeRejected("Side must be BUY or SELL; outcome UP or DOWN")
        request_id = parse_request_id(req.get("request_id"))
        spend = parse_dollars(req.get("spend_usd")) if side == "BUY" else None
        fingerprint = sha256(json.dumps(
            {"account": account, "side": side, "outcome": outcome,
             "spend_usd": str(spend) if spend is not None else None,
             "slug": req.get("slug")},
            sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        if side == "SELL" and "spend_usd" in req:
            raise PaperTradeRejected("SELL closes full position; do not pass spend_usd")
        slug = req.get("slug")
        if slug is not None and (not isinstance(slug, str) or len(slug) > 120):
            raise PaperTradeRejected("Invalid market slug")
        with self._connect() as con:
            with con.cursor() as cur:
                # Serialize all cash/position writes and idempotency for each account.
                cur.execute(
                    "SELECT cash_balance, realized_pnl FROM paper_accounts WHERE account_id=%s FOR UPDATE",
                    (account,),
                )
                current = cur.fetchone()
                if current is None:
                    raise RuntimeError("Paper account not initialized")
                cash, total_pnl = current
                cur.execute(
                    """SELECT side, outcome, slug, notional, price, quantity, cash_delta, source,
                              request_fingerprint
                       FROM paper_orders WHERE account_id=%s AND request_id=%s""",
                    (account, request_id),
                )
                previous = cur.fetchone()
                if previous:
                    # Strict replay semantics: do not repeat any mutation.
                    if previous[8] != fingerprint:
                        raise PaperTradeRejected("Idempotency key already used for another order")
                    return {"mode": "PAPER_ONLY", "duplicate": True,
                            "account": account, "side": previous[0],
                            "outcome": previous[1], "slug": previous[2],
                            "notional": str(previous[3]), "price": str(previous[4]),
                            "quantity": str(previous[5]), "cash_delta": str(previous[6]),
                            "source": previous[7]}
                now = self.clock()
                quote = demo_quote(now, outcome) if account == "demo" else verified_clob_quote(con, now, outcome)
                # In the explicitly synthetic sandbox, closing historical
                # virtual positions at fixed demo prices is allowed. This is
                # not a claim of an executable or settled prediction market.
                if side == "SELL" and account == "demo" and isinstance(slug, str):
                    if not re.fullmatch(r"paper-demo-btc-5m-[0-9]{10,}", slug):
                        raise PaperTradeRejected("Invalid sandbox market slug")
                    quote = replace(quote, slug=slug)
                if slug is not None and slug != quote.slug:
                    raise PaperTradeRejected("Selected market is not the current executable paper slot")
                cur.execute(
                    """SELECT quantity, cost_basis FROM paper_positions
                       WHERE account_id=%s AND slug=%s AND outcome=%s FOR UPDATE""",
                    (account, quote.slug, outcome),
                )
                position = cur.fetchone()
                if side == "BUY":
                    if cash < spend:
                        raise PaperTradeRejected("Insufficient virtual cash")
                    cur.execute(
                        "SELECT COALESCE(SUM(cost_basis),0), COUNT(*) FROM paper_positions WHERE account_id=%s",
                        (account,),
                    )
                    exposure, position_count = cur.fetchone()
                    if exposure + spend > MAX_EXPOSURE:
                        raise PaperTradeRejected("Open paper exposure would exceed $250")
                    if not position and position_count >= MAX_OPEN_POSITIONS:
                        raise PaperTradeRejected("Too many open paper positions")
                    quantity = money(spend / (quote.ask * (ONE + FEE_RATE)))
                    if quantity <= ZERO or quantity > quote.ask_size:
                        raise PaperTradeRejected("Not enough top-of-book liquidity for full paper fill")
                    price = quote.ask
                    notional = money(quantity * price)
                    fee = money(notional * FEE_RATE)
                    cost = notional + fee
                    if cost > cash:
                        raise PaperTradeRejected("Not enough virtual cash including fee")
                    delta = -cost
                    new_pnl = None
                    if position:
                        cur.execute(
                            """UPDATE paper_positions SET quantity=quantity+%s, cost_basis=cost_basis+%s,
                                   updated_at=NOW() WHERE account_id=%s AND slug=%s AND outcome=%s""",
                            (quantity, cost, account, quote.slug, outcome),
                        )
                    else:
                        cur.execute(
                            """INSERT INTO paper_positions
                               (account_id, slug, outcome, token_id, quantity, cost_basis, source)
                               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                            (account, quote.slug, outcome, quote.token, quantity, cost, quote.source),
                        )
                else:
                    if not position:
                        raise PaperTradeRejected("No open paper position to close")
                    quantity, cost_basis = position
                    if quantity > quote.bid_size:
                        raise PaperTradeRejected("Not enough top-of-book liquidity to close position")
                    price = quote.bid
                    notional = money(quantity * price)
                    fee = money(notional * FEE_RATE)
                    delta = notional - fee
                    new_pnl = delta - cost_basis
                    cur.execute(
                        "DELETE FROM paper_positions WHERE account_id=%s AND slug=%s AND outcome=%s",
                        (account, quote.slug, outcome),
                    )
                new_cash = cash + delta
                if new_cash < ZERO:
                    raise PaperTradeRejected("Negative balance would result")
                cur.execute(
                    """UPDATE paper_accounts SET cash_balance=%s, realized_pnl=%s
                       WHERE account_id=%s""",
                    (new_cash, total_pnl + (new_pnl or ZERO), account),
                )
                order_id = uuid4()
                cur.execute(
                    """INSERT INTO paper_orders
                       (order_id, account_id, request_id, side, slug, outcome, token_id,
                        quantity, price, notional, fee, cash_delta, realized_pnl,
                        source, quote_received_at, request_fingerprint)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) """,
                    (order_id, account, request_id, side, quote.slug, outcome,
                     quote.token, quantity, price, notional, fee, delta, new_pnl,
                     quote.source, quote.received_at, fingerprint),
                )
                cur.execute(
                    """INSERT INTO paper_cash_ledger
                       (entry_id, account_id, order_id, cash_delta, balance_after)
                       VALUES (%s,%s,%s,%s,%s)""",
                    (uuid4(), account, order_id, delta, new_cash),
                )
        return {
            "mode": "PAPER_ONLY", "duplicate": False, "account": account,
            "order_id": str(order_id), "request_id": str(request_id),
            "side": side, "outcome": outcome, "slug": quote.slug,
            "quantity": str(quantity), "price": str(price), "notional": str(notional),
            "fee": str(fee), "cash_delta": str(delta),
            "cash_balance": str(new_cash),
            "realized_pnl": str(new_pnl) if new_pnl is not None else None,
            "source": quote.source,
        }
