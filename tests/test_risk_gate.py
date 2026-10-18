from datetime import datetime, timedelta, timezone
import os
import unittest

from services.risk_engine.gate import LiveTradingDisabled, Mode, RiskGate


class RiskGateTest(unittest.TestCase):
    def test_read_only_is_default(self):
        self.assertIs(RiskGate().mode, Mode.READ_ONLY)

    def test_live_mode_always_rejected(self):
        with self.assertRaises(LiveTradingDisabled):
            RiskGate(mode=Mode.LIVE)

    def test_live_order_is_never_accepted(self):
        for mode in (Mode.READ_ONLY, Mode.PAPER):
            with self.assertRaises(LiveTradingDisabled):
                RiskGate(mode=mode).authorize_live_order("UP", amount=10)

    def test_env_variables_cannot_unlock_live(self):
        old = os.environ.get("FORCE_PROD")
        os.environ["FORCE_PROD"] = "true"
        try:
            with self.assertRaises(LiveTradingDisabled):
                RiskGate(mode=Mode.LIVE)
        finally:
            if old is None:
                os.environ.pop("FORCE_PROD", None)
            else:
                os.environ["FORCE_PROD"] = old

    def test_quote_age_is_bounded_and_future_quotes_fail(self):
        gate = RiskGate(max_quote_age_seconds=2)
        now = datetime.now(timezone.utc)
        self.assertTrue(gate.check_quote_freshness(now - timedelta(seconds=1), now))
        self.assertFalse(gate.check_quote_freshness(now - timedelta(seconds=3), now))
        self.assertFalse(gate.check_quote_freshness(now + timedelta(seconds=1), now))
        self.assertFalse(gate.check_quote_freshness(now.replace(tzinfo=None), now))


if __name__ == "__main__":
    unittest.main()
