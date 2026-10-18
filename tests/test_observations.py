"""Contract tests for Polymarket WebSocket raw and unified payloads."""
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
import unittest

from services.market_data.observations import (
    MarketObservation, StreamParseError, parse_market_message
)

NOW = datetime(2026, 10, 19, 5, 0, 15, tzinfo=timezone.utc)
MS = str(int(NOW.timestamp() * 1000))
SLUG = "btc-updown-5m-1792386000"
TOKENS = {"123456789012345": (SLUG, "UP"), "987654321098765": (SLUG, "DOWN")}


def frame(event: dict) -> str:
    return json.dumps(event)


class MarketWebSocketParserTest(unittest.TestCase):
    def test_full_book_sorted_independently_of_wire_order(self):
        f = frame({"event_type": "book", "asset_id": "123456789012345", "timestamp": MS,
                   "hash": "0x1", "bids": [{"price": "0.20", "size": "4"}, {"price": "0.40", "size": "2"}],
                   "asks": [{"price": "0.70", "size": "3"}, {"price": "0.60", "size": "1"}]})
        e = parse_market_message(f, TOKENS, received_at=NOW)[0]
        self.assertEqual(e.payload["best_bid"], "0.40")
        self.assertEqual(e.payload["best_ask"], "0.60")
        self.assertEqual(e.outcome, "UP")
        self.assertEqual(e.observed_at, NOW)
        self.assertEqual(e.source_event_id, parse_market_message(f, TOKENS, received_at=NOW)[0].source_event_id)

    def test_price_changes_split_per_asset(self):
        raw = frame({"event_type": "price_change", "timestamp": MS,
                    "price_changes": [
                        {"asset_id": "123456789012345", "side": "BUY", "price": "0.31", "size": "8", "best_bid": "0.31"},
                        {"asset_id": "987654321098765", "side": "SELL", "price": "0.67", "size": "0"},
                    ]})
        changes = parse_market_message(raw, TOKENS, received_at=NOW)
        self.assertEqual(len(changes), 2)
        self.assertEqual({e.outcome for e in changes}, {"UP", "DOWN"})
        self.assertNotEqual(changes[0].source_event_id, changes[1].source_event_id)

    def test_reject_unknown_token(self):
        raw = frame({"event_type": "book", "asset_id": "999999999999999", "timestamp": MS,
                    "bids": [], "asks": []})
        self.assertEqual(parse_market_message(raw, TOKENS, received_at=NOW), [])

    def test_pong_and_unsupported_event_ignored(self):
        self.assertEqual(parse_market_message("PONG", TOKENS, received_at=NOW), [])
        self.assertEqual(parse_market_message(frame({"event_type": "unknown"}), TOKENS, received_at=NOW), [])

    def test_reject_incomplete_book_no_fake_bbo(self):
        with self.assertRaises(StreamParseError):
            parse_market_message(frame({"event_type": "book", "asset_id": "123456789012345",
                                        "bids": [{"price": "0.3", "size": "2"}]}), TOKENS, received_at=NOW)

    def test_equivalent_price_notation_is_duplicate_level(self):
        with self.assertRaises(StreamParseError):
            parse_market_message(frame({
                "event_type": "book", "asset_id": "123456789012345",
                "bids": [{"price": "0.20", "size": "2"}, {"price": "0.2", "size": "3"}],
                "asks": [{"price": "0.8", "size": "1"}]
            }), TOKENS, received_at=NOW)

    def test_reject_crossed_book(self):
        with self.assertRaises(StreamParseError):
            parse_market_message(frame({"event_type": "book", "asset_id": "123456789012345",
                                        "bids": [{"price": "0.7", "size": "2"}],
                                        "asks": [{"price": "0.6", "size": "2"}]}), TOKENS, received_at=NOW)

    def test_reject_nonfinite_prices_sizes_and_duplicate_levels(self):
        base = {"event_type": "book", "asset_id": "123456789012345", "asks": []}
        for invalid in ("NaN", "-1", "Infinity", "1.1"):
            with self.subTest(value=invalid), self.assertRaises(StreamParseError):
                parse_market_message(frame({**base, "bids": [{"price": invalid, "size": "1"}]}),
                                     TOKENS, received_at=NOW)
        with self.assertRaises(StreamParseError):
            parse_market_message(frame({**base, "bids": [{"price": "0.2", "size": "-5"}]}),
                                 TOKENS, received_at=NOW)

    def test_reject_stale_future_invalid_time(self):
        template = {"event_type": "book", "asset_id": "123456789012345", "bids": [], "asks": []}
        for ts in (str(int((NOW - timedelta(days=3)).timestamp() * 1000)),
                   str(int((NOW + timedelta(hours=1)).timestamp() * 1000)), "200"):
            with self.subTest(timestamp=ts), self.assertRaises(StreamParseError):
                parse_market_message(frame({**template, "timestamp": ts}), TOKENS, received_at=NOW)

    def test_unified_book_envelope(self):
        raw = frame({"topic": "market", "type": "book", "payload": {
            "assetId": "123456789012345", "timestamp": NOW.isoformat(),
            "bids": [{"price": "0.35", "size": "9"}],
            "asks": [{"price": "0.45", "size": "8"}],
        }})
        item = parse_market_message(raw, TOKENS, received_at=NOW)[0]
        self.assertEqual(item.event_type, "book")
        self.assertEqual(item.payload["best_ask"], "0.45")

    def test_book_list_and_bounded_frame(self):
        row = {"event_type": "book", "asset_id": "123456789012345", "bids": [], "asks": []}
        self.assertEqual(len(parse_market_message(frame([row,row]), TOKENS, received_at=NOW)), 2)
        with self.assertRaises(StreamParseError):
            parse_market_message("x" * 2_000_002, TOKENS, received_at=NOW)

    def test_book_without_timestamp_tracks_received_time_provenance(self):
        raw = frame({"event_type": "book", "asset_id": "123456789012345", "bids": [], "asks": []})
        item = parse_market_message(raw, TOKENS, received_at=NOW)[0]
        self.assertEqual(item.observed_at, NOW)
        self.assertEqual(item.payload["timestamp_provenance"], "received_at")

if __name__ == "__main__":
    unittest.main()
