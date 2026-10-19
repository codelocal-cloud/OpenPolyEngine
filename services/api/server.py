"""Localhost-only HTTP API serving persisted PUBLIC PostgreSQL market snapshots."""
from __future__ import annotations

import argparse
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
from urllib.parse import parse_qs, urlsplit

import psycopg
from services.market_data.storage import PostgresStore
from services.market_data.observation_storage import ObservationStore
from services.market_data.models import SLUG_RE
from services.paper_trading.engine import PaperEngine, PaperTradeRejected
from datetime import datetime, timezone

LOCAL_UI_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}
PAPER_REQUEST_HEADER = "X-OpenPoly-Paper"
MAX_PAPER_BODY = 4096


def recent_snapshots(limit: int = 20, *, store: PostgresStore | None = None) -> list[dict]:
    return (store or PostgresStore()).recent_snapshots(limit)


class MarketHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, store: PostgresStore, observation_store: ObservationStore,
                 paper_engine: PaperEngine | None, **kwargs):
        self.store = store
        self.observation_store = observation_store
        self.paper_engine = paper_engine
        super().__init__(*args, **kwargs)

    def _send(self, code: int, payload: dict) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Vary", "Origin")
        if self.headers.get("Origin") in LOCAL_UI_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        uri = urlsplit(self.path)
        if uri.path == "/health":
            self._send(200, {"status": "ok", "mode": "READ_ONLY", "trading_enabled": False})
            return
        if uri.path in ("/api/paper/state", "/api/paper/quote", "/api/paper/request"):
            params = parse_qs(uri.query)
            account = params.get("account", ["clob"])[0]
            try:
                paper = self.paper_engine or PaperEngine()
                if uri.path == "/api/paper/state":
                    result = paper.state(account)
                elif uri.path == "/api/paper/request":
                    result = paper.request_status(account, params.get("request_id", [""])[0])
                else:
                    outcome = params.get("outcome", [""])[0]
                    result = paper.quote(account, outcome)
            except PaperTradeRejected as exc:
                self._send(422, {"error": "paper_rejected", "reason": str(exc)})
                return
            except (psycopg.Error, OSError, RuntimeError, ValueError) as exc:
                self._send(503, {"error": "paper_database_unavailable"})
                return
            self._send(200, result)
            return
        if uri.path == "/api/orderbooks":
            self._serve_orderbooks(uri.query)
            return
        if uri.path == "/api/observations":
            self._serve_observations(uri.query)
            return
        if uri.path != "/api/markets":
            self._send(404, {"error": "not_found"})
            return
        try:
            raw = parse_qs(uri.query).get("limit", ["20"])[0]
            limit = int(raw)
            if not 1 <= limit <= 50:
                raise ValueError("limit must be within 1..50")
            result = recent_snapshots(limit, store=self.store)
        except ValueError:
            self._send(400, {"error": "invalid_limit"})
            return
        except (psycopg.Error, OSError, json.JSONDecodeError):
            self._send(503, {"error": "market_database_unavailable"})
            return
        self._send(200, {"mode": "READ_ONLY", "markets": result, "count": len(result)})

    def _serve_orderbooks(self, query: str) -> None:
        params = parse_qs(query)
        slug = params.get("slug", [""])[0]
        if not SLUG_RE.fullmatch(slug):
            self._send(400, {"error": "invalid_slug"})
            return
        try:
            market = self.store.verified_market(slug)
            if market is None:
                self._send(404, {"error": "verified_market_not_found"})
                return
            books = {}
            now = datetime.now(timezone.utc)
            start = datetime.fromisoformat(market["slot_start"])
            end = datetime.fromisoformat(market["slot_end"])
            current = start <= now < end and not market.get("closed", False)
            for outcome, token in (("UP", market["token_up"]), ("DOWN", market["token_down"])):
                book = self.observation_store.latest_book(token)
                if book is not None:
                    age_seconds = (now - datetime.fromisoformat(book["received_at"])).total_seconds()
                    book["age_seconds"] = round(age_seconds, 3)
                    # Future-dated or old snapshots must never look executable.
                    book["stale"] = not current or age_seconds > 20 or age_seconds < -2
                books[outcome] = book
        except (psycopg.Error, OSError, ValueError, KeyError, json.JSONDecodeError):
            self._send(503, {"error": "orderbook_database_unavailable"})
            return
        self._send(200, {"mode": "READ_ONLY", "slug": slug, "books": books,
                         "live_trading_enabled": False})

    def _serve_observations(self, query: str) -> None:
        params = parse_qs(query)
        slug = params.get("slug", [""])[0]
        try:
            limit = int(params.get("limit", ["25"])[0])
            if not SLUG_RE.fullmatch(slug) or not 1 <= limit <= 100:
                raise ValueError("Invalid slug/limit")
        except ValueError:
            self._send(400, {"error": "invalid_slug_or_limit"})
            return
        try:
            observations = self.observation_store.recent(slug, limit=limit)
        except (psycopg.Error, OSError, ValueError, json.JSONDecodeError):
            self._send(503, {"error": "observation_database_unavailable"})
            return
        self._send(200, {"mode": "READ_ONLY", "observations": observations,
                         "count": len(observations)})

    def do_OPTIONS(self) -> None:
        if self.path.split("?", 1)[0] != "/api/paper/orders":
            self._send(404, {"error": "not_found"})
            return
        origin = self.headers.get("Origin")
        if origin not in LOCAL_UI_ORIGINS:
            self._send(403, {"error": "origin_not_allowed"})
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-OpenPoly-Paper")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_POST(self) -> None:
        uri = urlsplit(self.path)
        if uri.path != "/api/paper/orders":
            self._send(405, {"error": "real_trading_unavailable"})
            return
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        if origin is not None and origin not in LOCAL_UI_ORIGINS:
            self._send(403, {"error": "origin_not_allowed"})
            return
        if host not in (f"127.0.0.1:{self.server.server_port}",
                        f"localhost:{self.server.server_port}") or (
                            self.headers.get(PAPER_REQUEST_HEADER) != "1"
                        ):
            self._send(403, {"error": "paper_csrf_guard"})
            return
        if "application/json" not in self.headers.get("Content-Type", ""):
            self._send(415, {"error": "json_required"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > MAX_PAPER_BODY:
                raise ValueError("Body size")
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError("Object body required")
        except (ValueError, json.JSONDecodeError):
            self._send(400, {"error": "invalid_paper_request"})
            return
        account = parse_qs(uri.query).get("account", ["clob"])[0]
        try:
            result = (self.paper_engine or PaperEngine()).execute(account, payload)
        except PaperTradeRejected as exc:
            self._send(422, {"error": "paper_rejected", "reason": str(exc)})
            return
        except (psycopg.Error, OSError, RuntimeError, ValueError):
            self._send(503, {"error": "paper_database_unavailable"})
            return
        self._send(200, result)

    def do_PUT(self) -> None:
        self._send(405, {"error": "read_only_no_trading_endpoints"})

    def do_DELETE(self) -> None:
        self._send(405, {"error": "read_only_no_trading_endpoints"})


def make_server(
    store: PostgresStore | None = None, port: int = 8787,
    observation_store: ObservationStore | None = None,
    paper_engine: PaperEngine | None = None,
) -> ThreadingHTTPServer:
    if not 0 <= port <= 65535:
        raise ValueError("Invalid port")
    return ThreadingHTTPServer(
        ("127.0.0.1", port),
        partial(MarketHandler, store=store or PostgresStore(),
                observation_store=observation_store or ObservationStore(),
                paper_engine=paper_engine),
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Local-only, read-only PolyBTC market API")
    p.add_argument("--port", type=int, default=8787)
    args = p.parse_args()
    try:
        with make_server(port=args.port) as server:
            print(f"PolyBTC read-only API: http://127.0.0.1:{args.port} (Ctrl-C to stop)")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    except (ValueError, OSError) as exc:
        print(f"API failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
