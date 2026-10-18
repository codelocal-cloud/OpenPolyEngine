import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import unittest

from services.market_data.models import MarketParseError, parse_event, slot_slug, upcoming_slugs

FIXTURE = Path(__file__).parent / "fixtures" / "btc_event.json"
AT = datetime(2026, 10, 19, 0, 0, 30, tzinfo=timezone.utc)


class MarketModelsTest(unittest.TestCase):
    def setUp(self):
        self.event = json.loads(FIXTURE.read_text())

    def test_slot_rounds_down_and_next_slots(self):
        late = AT + timedelta(minutes=4, seconds=29)
        self.assertEqual(slot_slug(late), self.event["slug"])
        result = upcoming_slugs(late, 2)
        self.assertEqual(result[0], self.event["slug"])
        self.assertEqual(int(result[1].rsplit("-", 1)[1]) - int(result[0].rsplit("-", 1)[1]), 300)

    def test_timezone_offset_yields_same_slot(self):
        self.assertEqual(slot_slug(AT), slot_slug(AT.astimezone(timezone(timedelta(hours=7)))))

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            slot_slug(datetime(2026, 10, 19))

    def test_range_is_bounded(self):
        for invalid in (0, 13, -1):
            with self.assertRaises(ValueError):
                upcoming_slugs(AT, invalid)

    def test_mapping_and_price_are_stable(self):
        result = parse_event(self.event, self.event["slug"], fetched_at=AT)
        self.assertEqual(result.token_up, "111111111111")
        self.assertEqual(result.token_down, "222222222222")
        self.assertEqual(result.price_up, Decimal("0.48"))
        self.assertEqual(result.price_down, Decimal("0.52"))
        self.assertEqual(result.slot_end - result.slot_start, timedelta(minutes=5))
        self.assertEqual(result.to_dict()["price_kind"], "gamma_indicative_not_executable")

    def test_reversed_outcome_order_preserves_token_pairing(self):
        market = self.event["markets"][0]
        market["outcomes"] = json.dumps(["Down", "Up"])
        market["clobTokenIds"] = json.dumps(["222", "111"])
        market["outcomePrices"] = json.dumps(["0.4", "0.6"])
        s = parse_event(self.event, self.event["slug"], fetched_at=AT)
        self.assertEqual((s.token_up, s.token_down), ("111", "222"))
        self.assertEqual(s.price_up, Decimal("0.6"))

    def test_missing_or_duplicate_tokens_are_rejected(self):
        for ids in (["111", "111"], ["111"], []):
            bad = copy.deepcopy(self.event)
            bad["markets"][0]["clobTokenIds"] = json.dumps(ids)
            with self.assertRaises(MarketParseError):
                parse_event(bad, bad["slug"])

    def test_unknown_outcome_rejected(self):
        self.event["markets"][0]["outcomes"] = '["YES","NO"]'
        with self.assertRaises(MarketParseError):
            parse_event(self.event, self.event["slug"])

    def test_stale_or_invalid_prices_not_accepted(self):
        for values in (["NaN", "0.5"], ["1.1", "-0.1"], ["invalid", "0.5"]):
            bad = copy.deepcopy(self.event)
            bad["markets"][0]["outcomePrices"] = json.dumps(values)
            with self.assertRaises(MarketParseError):
                parse_event(bad, bad["slug"])

    def test_event_slug_mismatch_fails_closed(self):
        with self.assertRaises(MarketParseError):
            parse_event(self.event, "btc-updown-5m-1800000000")

    def test_not_accepting_orders_is_reported(self):
        self.event["markets"][0]["acceptingOrders"] = False
        result = parse_event(self.event, self.event["slug"])
        self.assertFalse(result.accepting_orders)


if __name__ == "__main__":
    unittest.main()
