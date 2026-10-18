"""Public GET-only Gamma adapter. No credentials, trading routes or key material."""
from __future__ import annotations

from datetime import datetime
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import MarketParseError, MarketSnapshot, SLUG_RE, parse_event

GAMMA_ORIGIN = "https://gamma-api.polymarket.com"
MAX_BODY_BYTES = 2_000_000
RETRYABLE_HTTP = {429, 500, 502, 503, 504}


class GammaError(RuntimeError):
    """Gamma retrieval failed. Never substitute synthetic prices."""


class GammaClient:
    def __init__(
        self,
        *,
        timeout_seconds: float = 7.0,
        retries: int = 2,
        opener=None,
        sleep=None,
    ):
        if not 0 < timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 0 and 30")
        if not 0 <= retries <= 3:
            raise ValueError("retries must be between 0 and 3")
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self._open = opener or urlopen
        self._sleep = sleep or time.sleep

    def fetch_event(self, slug: str) -> dict | None:
        if not SLUG_RE.fullmatch(slug):
            raise MarketParseError("Disallowed market slug")
        request = Request(
            f"{GAMMA_ORIGIN}/events/slug/{slug}",
            headers={"Accept": "application/json", "User-Agent": "PolyBTC-ReadOnly/0.2"},
            method="GET",
        )
        for attempt in range(self.retries + 1):
            try:
                with self._open(request, timeout=self.timeout_seconds) as response:
                    data = response.read(MAX_BODY_BYTES + 1)
                break
            except HTTPError as exc:
                if exc.code == 404:
                    return None
                if exc.code not in RETRYABLE_HTTP or attempt == self.retries:
                    raise GammaError(f"Gamma HTTP {exc.code}") from exc
            except (URLError, OSError, TimeoutError) as exc:
                if attempt == self.retries:
                    raise GammaError(f"Gamma connection failed after {attempt + 1} attempts: {type(exc).__name__}") from exc
            # Bounded and conservative: no retries for malformed data or invalid slugs.
            self._sleep(0.5 * (2 ** attempt))

        if len(data) > MAX_BODY_BYTES:
            raise GammaError("Gamma payload exceeded safety limit")
        try:
            parsed = json.loads(data)
        except (ValueError, UnicodeDecodeError) as exc:
            raise GammaError("Gamma returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise GammaError("Gamma event must be a JSON object")
        return parsed

    def fetch_snapshot(self, slug: str, *, fetched_at: datetime | None = None) -> MarketSnapshot | None:
        event = self.fetch_event(slug)
        return None if event is None else parse_event(event, slug, fetched_at=fetched_at)
