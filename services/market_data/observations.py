"""Strict, loss-aware parsing of public Polymarket market-channel events.

We archive *observations*, not claimed executable prices. A full book snapshot
can supply BBO; incremental changes must not be presented as a fresh full book.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Any

EVENT_TYPES = {"book", "price_change", "last_trade_price", "tick_size_change", "best_bid_ask"}
MAX_WIRE_BYTES = 2_000_000
MAX_LEVELS = 5000
SOURCE = "polymarket_clob_ws"


class StreamParseError(ValueError):
    """Unexpected, oversized or unsafe WebSocket market data."""


@dataclass(frozen=True)
class MarketObservation:
    source: str
    source_event_id: str
    observed_at: datetime
    received_at: datetime
    slug: str
    outcome: str
    instrument: str
    event_type: str
    payload: dict[str, Any]


def _decimal(value: Any, name: str, *, allow_zero: bool = False, size: bool = False) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise StreamParseError(f"{name}: expected finite decimal string")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise StreamParseError(f"{name}: invalid decimal") from exc
    if not number.is_finite():
        raise StreamParseError(f"{name}: nonfinite number")
    if size:
        if number < 0:
            raise StreamParseError(f"{name}: negative size")
    elif number < 0 or number > 1 or (number == 0 and not allow_zero):
        raise StreamParseError(f"{name}: price outside allowed range")
    return str(number)


def _levels(value: Any, side: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > MAX_LEVELS:
        raise StreamParseError(f"{side}: invalid level array")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise StreamParseError(f"{side}: level is not object")
        price = _decimal(item.get("price"), f"{side}.price")
        size = _decimal(item.get("size"), f"{side}.size", size=True)
        canonical_price = str(Decimal(price).normalize())
        if canonical_price in seen:
            raise StreamParseError(f"{side}: duplicate price level")
        seen.add(canonical_price)
        if Decimal(size) > 0:
            result.append({"price": price, "size": size})
    return result


def _timestamp(raw: Any, received_at: datetime) -> tuple[datetime, bool]:
    if raw is None or raw == "":
        return received_at, False
    try:
        if isinstance(raw, str) and ("T" in raw or "-" in raw):
            result = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        else:
            # Raw Polymarket CLOB sends Unix *milliseconds*, not seconds.
            stamp = str(raw)
            if not stamp.isdigit() or len(stamp) < 13 or len(stamp) > 16:
                raise StreamParseError("timestamp: expected Unix milliseconds")
            result = datetime.fromtimestamp(int(stamp) / 1000, timezone.utc)
    except (OverflowError, ValueError, OSError) as exc:
        raise StreamParseError("timestamp: invalid") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise StreamParseError("timestamp: missing UTC offset")
    result = result.astimezone(timezone.utc)
    if result > received_at + timedelta(minutes=2):
        raise StreamParseError("timestamp: too far in future")
    if result < received_at - timedelta(hours=24):
        raise StreamParseError("timestamp: stale event")
    return result, True


def _normalize_bbo(message: dict[str, Any]) -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for in_key, out_key in (("best_bid", "best_bid"), ("bestBid", "best_bid"),
                            ("best_ask", "best_ask"), ("bestAsk", "best_ask")):
        if in_key in message and message[in_key] not in (None, ""):
            out[out_key] = _decimal(message[in_key], in_key)
    return out


def parse_market_message(
    wire: str | bytes,
    allowed_tokens: dict[str, tuple[str, str]],
    *,
    received_at: datetime | None = None,
) -> list[MarketObservation]:
    """Return 0+ normalized events for a single WebSocket data frame.

    allowed_tokens maps actual Gamma-verified token ID -> (slug, UP/DOWN).
    An event from any other token is never stored.
    """
    if isinstance(wire, bytes):
        if len(wire) > MAX_WIRE_BYTES:
            raise StreamParseError("WebSocket frame too large")
        wire = wire.decode("utf-8", errors="strict")
    if len(wire.encode("utf-8")) > MAX_WIRE_BYTES:
        raise StreamParseError("WebSocket frame too large")
    if wire.strip() in ("PING", "PONG", ""):
        return []
    try:
        packet = json.loads(wire)
    except (json.JSONDecodeError, ValueError) as exc:
        raise StreamParseError("WebSocket: invalid JSON") from exc
    messages = packet if isinstance(packet, list) else [packet]
    if not isinstance(messages, list) or len(messages) > 300:
        raise StreamParseError("WebSocket: oversized event list")
    now = received_at or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise StreamParseError("received_at must contain timezone")
    now = now.astimezone(timezone.utc)
    results: list[MarketObservation] = []
    for message in messages:
        if not isinstance(message, dict):
            raise StreamParseError("WebSocket event not an object")
        event_type = message.get("event_type") or message.get("type")
        if event_type not in EVENT_TYPES:
            continue
        payload = message.get("payload", message)
        if not isinstance(payload, dict):
            raise StreamParseError("WebSocket event payload not an object")
        observed, has_source_time = _timestamp(payload.get("timestamp"), now)
        if event_type == "price_change":
            changes = payload.get("price_changes", payload.get("priceChanges"))
            if not isinstance(changes, list) or len(changes) > 1000:
                raise StreamParseError("price_change: invalid change list")
            subevents = changes
        else:
            subevents = [payload]
        for entry in subevents:
            if not isinstance(entry, dict):
                raise StreamParseError("WebSocket subevent not an object")
            token = entry.get("asset_id") or entry.get("assetId")
            if not isinstance(token, str) or token not in allowed_tokens:
                continue
            slug, outcome = allowed_tokens[token]
            normalized: dict[str, Any] = {
                "asset_id": token,
                "slug": slug,
                "outcome": outcome,
                "event_type": event_type,
                "timestamp_provenance": "exchange" if has_source_time else "received_at",
                "market": payload.get("market") or payload.get("conditionId") or payload.get("condition_id"),
            }
            if event_type == "book":
                # Missing either side is NOT a complete book; reject, never fake BBO.
                bids = payload.get("bids", payload.get("buys"))
                asks = payload.get("asks", payload.get("sells"))
                normalized["bids"] = _levels(bids, "bids")
                normalized["asks"] = _levels(asks, "asks")
                best_bid = max((Decimal(v["price"]) for v in normalized["bids"]), default=None)
                best_ask = min((Decimal(v["price"]) for v in normalized["asks"]), default=None)
                if best_bid is not None and best_ask is not None and best_bid >= best_ask:
                    raise StreamParseError("book: crossed or locked order book")
                normalized["best_bid"] = str(best_bid) if best_bid is not None else None
                normalized["best_ask"] = str(best_ask) if best_ask is not None else None
                normalized["hash"] = payload.get("hash")
            elif event_type == "price_change":
                normalized["price"] = _decimal(entry.get("price"), "change.price")
                normalized["size"] = _decimal(entry.get("size"), "change.size", size=True)
                side = entry.get("side")
                if side not in ("BUY", "SELL"):
                    raise StreamParseError("price_change: expected BUY/SELL")
                normalized["side"] = side
                normalized.update(_normalize_bbo(entry))
                normalized["hash"] = entry.get("hash")
            elif event_type == "last_trade_price":
                normalized["price"] = _decimal(payload.get("price"), "trade.price")
                if payload.get("size") is not None:
                    normalized["size"] = _decimal(payload["size"], "trade.size", size=True)
                normalized["side"] = payload.get("side")
            elif event_type == "tick_size_change":
                tick = payload.get("new_tick_size", payload.get("newTickSize"))
                normalized["new_tick_size"] = _decimal(tick, "tick_size")
            elif event_type == "best_bid_ask":
                normalized.update(_normalize_bbo(payload))
                if not normalized.get("best_bid") and not normalized.get("best_ask"):
                    raise StreamParseError("best_bid_ask without bid or ask")
            canonical = json.dumps(normalized, separators=(",", ":"), sort_keys=True)
            digest = sha256((observed.isoformat() + "|" + canonical).encode()).hexdigest()
            results.append(MarketObservation(
                source=SOURCE, source_event_id=digest, observed_at=observed,
                received_at=now, slug=slug, outcome=outcome, instrument=token,
                event_type=event_type, payload=normalized,
            ))
    return results
