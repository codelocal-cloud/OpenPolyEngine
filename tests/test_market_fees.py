"""Official Gamma feeSchedule parser regression tests."""
from copy import deepcopy
from decimal import Decimal
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from services.market_data.models import MarketParseError, parse_event

EVENT=json.loads((Path(__file__).parent / "fixtures" / "btc_event.json").read_text())
SLUG=EVENT["slug"]
AT=datetime(2026,10,19,0,0,20,tzinfo=timezone.utc)


class GammaFeeScheduleTest(unittest.TestCase):
    def test_market_fee_schedule_in_snapshot(self):
        event=deepcopy(EVENT)
        event["markets"][0]["feeSchedule"]={"rate":0.07,"exponent":1}
        item=parse_event(event,SLUG,fetched_at=AT)
        self.assertEqual(item.fee_rate,Decimal("0.07"))
        self.assertEqual(item.fee_exponent,1)
        self.assertEqual(item.to_dict()["fee_rate"],"0.07")

    def test_event_fee_schedule_when_market_field_absent(self):
        event=deepcopy(EVENT)
        event["feeSchedule"]={"rate":"0.07","exponent":1}
        item=parse_event(event,SLUG,fetched_at=AT)
        self.assertEqual(item.fee_rate,Decimal("0.07"))

    def test_missing_fee_is_explicit_null_not_default(self):
        event=deepcopy(EVENT)
        event["feeSchedule"]=None
        event["markets"][0].pop("feeSchedule",None)
        item=parse_event(event,SLUG,fetched_at=AT)
        self.assertIsNone(item.fee_rate)

    def test_invalid_fee_never_defaults_to_simulation(self):
        for fee in ({"rate":-1,"exponent":1}, {"rate":"NaN","exponent":1},
                    {"rate":0.07,"exponent":2}, {"rate":3,"exponent":1},
                    {"rate":"oops","exponent":1}, ["0.07"]):
            event=deepcopy(EVENT)
            event["markets"][0]["feeSchedule"]=fee
            with self.subTest(fee=fee),self.assertRaises(MarketParseError):
                parse_event(event,SLUG,fetched_at=AT)


if __name__ == "__main__":
    unittest.main()
