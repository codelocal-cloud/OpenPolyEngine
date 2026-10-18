"""Fail-closed Phase 1 execution gate; not configurable through environment vars."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import NoReturn


class Mode(str, Enum):
    READ_ONLY = "READ_ONLY"
    PAPER = "PAPER"
    LIVE = "LIVE"


class LiveTradingDisabled(PermissionError):
    """This version cannot authorize sending any live order."""


@dataclass(frozen=True)
class RiskGate:
    mode: Mode = Mode.READ_ONLY
    max_quote_age_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.mode is Mode.LIVE:
            raise LiveTradingDisabled("LIVE mode is not available in Phase 1")
        if not 0 < self.max_quote_age_seconds <= 30:
            raise ValueError("Invalid quote age limit")

    def check_quote_freshness(self, observed_at: datetime, now: datetime) -> bool:
        if observed_at.tzinfo is None or now.tzinfo is None:
            return False
        age = (now.astimezone(timezone.utc) - observed_at.astimezone(timezone.utc)).total_seconds()
        return 0 <= age <= self.max_quote_age_seconds

    def authorize_live_order(self, *_args: object, **_kwargs: object) -> NoReturn:
        raise LiveTradingDisabled("No live execution code is installed in Phase 1")
