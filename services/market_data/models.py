"""Strict, side-effect-free parsing of BTC 5-minute Gamma event metadata."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import re
from typing import Any

SLOT_SECONDS = 300
SLUG_RE = re.compile(r"^btc-updown-5m-(\d{10,})$")


class MarketParseError(ValueError):
    """Gamma data does not match the expected BTC 5-minute contract."""


def slot_slug(at: datetime) -> str:
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValueError("Slot timestamp must be timezone-aware")
    epoch = int(at.timestamp())
    return f"btc-updown-5m-{epoch - epoch % SLOT_SECONDS}"


def upcoming_slugs(at: datetime, count: int) -> list[str]:
    if not 1 <= count <= 12:
        raise ValueError("slots must be between 1 and 12")
    start = int(slot_slug(at).rsplit("-", 1)[1])
    return [f"btc-updown-5m-{start + n * SLOT_SECONDS}" for n in range(count)]


def _json_array(value: Any, label: str) -> list[Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise MarketParseError(f"{label} is not valid JSON") from exc
    if not isinstance(value, list):
        raise MarketParseError(f"{label} is not an array")
    return value


@dataclass(frozen=True)
class MarketSnapshot:
    slug: str
    market_id: str
    slot_start: datetime
    slot_end: datetime
    fetched_at: datetime
    token_up: str
    token_down: str
    price_up: Decimal | None
    price_down: Decimal | None
    active: bool
    closed: bool
    accepting_orders: bool
    resolution_source: str | None
    data_source: str = "gamma_public"
    fee_rate: Decimal | None = None
    fee_exponent: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "market_id": self.market_id,
            "slot_start": self.slot_start.isoformat(),
            "slot_end": self.slot_end.isoformat(),
            "fetched_at": self.fetched_at.isoformat(),
            "token_up": self.token_up,
            "token_down": self.token_down,
            "price_up": str(self.price_up) if self.price_up is not None else None,
            "price_down": str(self.price_down) if self.price_down is not None else None,
            "active": self.active,
            "closed": self.closed,
            "accepting_orders": self.accepting_orders,
            "resolution_source": self.resolution_source,
            "fee_rate": str(self.fee_rate) if self.fee_rate is not None else None,
            "fee_exponent": self.fee_exponent,
            "price_kind": "gamma_indicative_not_executable",
            "data_source": self.data_source,
        }


def parse_event(event: dict[str, Any], slug: str, fetched_at: datetime | None = None, *, data_source: str = "gamma_public") -> MarketSnapshot:
    match = SLUG_RE.fullmatch(slug)
    if match is None:
        raise MarketParseError("Only exact BTC 5-minute slugs are allowed")
    if not isinstance(event, dict) or event.get("slug") != slug:
        raise MarketParseError("Gamma event slug mismatch")
    start_epoch = int(match.group(1))
    if start_epoch % SLOT_SECONDS:
        raise MarketParseError("Market slug timestamp is not aligned to 300 seconds")

    markets = event.get("markets")
    if not isinstance(markets, list) or not markets:
        raise MarketParseError("Event has no markets")
    candidates = [market for market in markets if isinstance(market, dict) and market.get("slug") == slug]
    if not candidates and len(markets) == 1 and isinstance(markets[0], dict):
        candidates = markets
    if len(candidates) != 1:
        raise MarketParseError("Cannot uniquely determine market")
    market = candidates[0]

    outcomes = _json_array(market.get("outcomes"), "outcomes")
    ids = _json_array(market.get("clobTokenIds"), "clobTokenIds")
    if len(outcomes) != 2 or len(ids) != 2:
        raise MarketParseError("Expected exactly two outcomes and two CLOB tokens")
    by_outcome: dict[str, str] = {}
    for name, token in zip(outcomes, ids):
        if not isinstance(name, str) or not isinstance(token, str) or not token.strip():
            raise MarketParseError("Invalid outcome/token mapping")
        label = name.strip().lower()
        if label in by_outcome:
            raise MarketParseError("Duplicate outcome")
        by_outcome[label] = token
    if set(by_outcome) != {"up", "down"} or len(set(ids)) != 2:
        raise MarketParseError("Unexpected outcome labels or duplicate token IDs")

    prices: dict[str, Decimal] = {}
    raw_prices = market.get("outcomePrices")
    if raw_prices is not None:
        arr = _json_array(raw_prices, "outcomePrices")
        if len(arr) != 2:
            raise MarketParseError("Prices do not match the outcomes")
        for name, value in zip(outcomes, arr):
            try:
                p = Decimal(str(value))
            except (InvalidOperation, ValueError) as exc:
                raise MarketParseError("Invalid outcome price") from exc
            if not p.is_finite() or not 0 <= p <= 1:
                raise MarketParseError("Outcome price outside [0,1]")
            prices[name.strip().lower()] = p

    start = datetime.fromtimestamp(start_epoch, tz=timezone.utc)
    time_read = fetched_at or datetime.now(timezone.utc)
    if time_read.tzinfo is None or time_read.utcoffset() is None:
        raise MarketParseError("fetched_at must be timezone-aware")
    source = market.get("resolutionSource") or event.get("resolutionSource")
    raw_fee = market.get("feeSchedule") or event.get("feeSchedule")
    fee_rate: Decimal | None = None
    fee_exponent: int | None = None
    if raw_fee is not None:
        if not isinstance(raw_fee, dict):
            raise MarketParseError("Invalid official feeSchedule")
        try:
            fee_rate = Decimal(str(raw_fee["rate"]))
            raw_exponent = raw_fee.get("exponent")
            if isinstance(raw_exponent, bool) or str(raw_exponent) != "1":
                raise MarketParseError("Unsupported fee exponent")
            fee_exponent = 1
        except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
            raise MarketParseError("Invalid official fee rate") from exc
        if not fee_rate.is_finite() or not 0 <= fee_rate <= Decimal("0.5"):
            raise MarketParseError("Official fee rate out of range")
    return MarketSnapshot(
        slug=slug,
        market_id=str(market.get("id", "")),
        slot_start=start,
        slot_end=start + timedelta(seconds=SLOT_SECONDS),
        fetched_at=time_read.astimezone(timezone.utc),
        token_up=by_outcome["up"],
        token_down=by_outcome["down"],
        price_up=prices.get("up"),
        price_down=prices.get("down"),
        active=market.get("active") is True,
        closed=market.get("closed") is True,
        accepting_orders=market.get("acceptingOrders") is True,
        resolution_source=str(source) if source is not None else None,
        data_source=data_source,
        fee_rate=fee_rate,
        fee_exponent=fee_exponent,
    )
