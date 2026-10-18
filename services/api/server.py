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

LOCAL_UI_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}


def recent_snapshots(limit: int = 20, *, store: PostgresStore | None = None) -> list[dict]:
    return (store or PostgresStore()).recent_snapshots(limit)


class MarketHandler(BaseHTTPRequestHandler):
    def __init__(self, *args, store: PostgresStore, **kwargs):
        self.store = store
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

    def do_POST(self) -> None:
        self._send(405, {"error": "read_only_no_trading_endpoints"})

    def do_PUT(self) -> None:
        self._send(405, {"error": "read_only_no_trading_endpoints"})

    def do_DELETE(self) -> None:
        self._send(405, {"error": "read_only_no_trading_endpoints"})


def make_server(store: PostgresStore | None = None, port: int = 8787) -> ThreadingHTTPServer:
    if not 0 <= port <= 65535:
        raise ValueError("Invalid port")
    return ThreadingHTTPServer(
        ("127.0.0.1", port),
        partial(MarketHandler, store=store or PostgresStore()),
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
