"""HTTP paper routes: opt-in only, localhost origin protection and no real order paths."""
from http.server import ThreadingHTTPServer
from threading import Thread
from http.client import HTTPConnection
import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from services.api.server import make_server
from services.paper_trading.engine import PaperTradeRejected, parse_request_id


class StubMarketStore:
    def recent_snapshots(self, limit):
        return []


class StubBookStore:
    def recent(self, slug, limit):
        return []


class StubPaperEngine:
    def __init__(self):
        self.calls = []
    def state(self, account):
        if account != "clob":
            raise PaperTradeRejected("unsupported")
        return {"mode": "PAPER_ONLY", "account": account, "cash_balance": "1000"}
    def quote(self, account, outcome):
        if account != "clob" or outcome not in ("UP","DOWN"):
            raise PaperTradeRejected("unsupported")
        return {"mode": "PAPER_ONLY", "source": "polymarket_clob_ws", "outcome": outcome}
    def execute(self, account, request):
        self.calls.append((account, request))
        return {"mode": "PAPER_ONLY", "source": "polymarket_clob_ws", "duplicate": False}
    def request_status(self, account, request_id):
        parse_request_id(request_id)
        if account != "clob":
            raise PaperTradeRejected("Invalid paper account")
        return {"mode": "PAPER_ONLY", "account": account, "request_id": request_id,
                "found": account == "clob" and request_id == "e7382c97-3322-43a0-9217-a0da59169ef2"}


class PaperApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = StubPaperEngine()
        cls.server = make_server(
            store=StubMarketStore(), observation_store=StubBookStore(),
            paper_engine=cls.engine, port=0)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def test_get_state_and_verified_quote(self):
        with urlopen(self.base + "/api/paper/state?account=clob", timeout=3) as response:
            self.assertEqual(json.loads(response.read())["cash_balance"], "1000")
        with urlopen(self.base + "/api/paper/quote?account=clob&outcome=UP", timeout=3) as response:
            self.assertEqual(json.loads(response.read())["source"], "polymarket_clob_ws")

    def test_request_lookup_is_scoped_and_validated(self):
        rid = "e7382c97-3322-43a0-9217-a0da59169ef2"
        with urlopen(self.base+f"/api/paper/request?account=clob&request_id={rid}", timeout=3) as response:
            self.assertTrue(json.loads(response.read())["found"])
        with self.assertRaises(HTTPError) as err:
            urlopen(self.base+f"/api/paper/request?account=demo&request_id={rid}", timeout=3)
        self.assertEqual(err.exception.code, 422)
        with self.assertRaises(HTTPError) as err:
            urlopen(self.base+"/api/paper/request?account=clob&request_id=invalid", timeout=3)
        self.assertEqual(err.exception.code, 422)

    def test_demo_account_disabled_even_for_get(self):
        with self.assertRaises(HTTPError) as err:
            urlopen(self.base + "/api/paper/state?account=demo", timeout=3)
        self.assertEqual(err.exception.code, 422)

    def test_post_requires_explicit_paper_header(self):
        body = json.dumps({"side":"BUY"}).encode()
        request = Request(
            self.base+"/api/paper/orders?account=clob",
            data=body, method="POST", headers={"Content-Type":"application/json"})
        with self.assertRaises(HTTPError) as err:
            urlopen(request, timeout=3)
        self.assertEqual(err.exception.code, 403)
        self.assertEqual(len(self.engine.calls), 0)

    def test_origin_rejects_untrusted_websites(self):
        request = Request(
            self.base+"/api/paper/orders?account=clob", data=b"{}",
            method="POST", headers={
                "Content-Type":"application/json",
                "X-OpenPoly-Paper":"1",
                "Origin":"https://malicious.example",
            })
        with self.assertRaises(HTTPError) as err:
            urlopen(request, timeout=3)
        self.assertEqual(err.exception.code, 403)
        self.assertEqual(len(self.engine.calls), 0)

    def test_valid_browser_paper_post(self):
        request = Request(
            self.base+"/api/paper/orders?account=clob", data=b'{"side":"BUY"}',
            method="POST", headers={
                "Content-Type":"application/json",
                "X-OpenPoly-Paper":"1",
                "Origin":"http://127.0.0.1:5173",
            })
        with urlopen(request,timeout=3) as result:
            data=json.loads(result.read())
        self.assertEqual(data["mode"],"PAPER_ONLY")
        self.assertEqual(self.engine.calls[-1],("clob",{"side":"BUY"}))

    def test_real_trading_routes_remain_inaccessible(self):
        request=Request(
            self.base+"/api/orders",method="POST",
            data=b"{}",headers={"X-OpenPoly-Paper":"1"})
        with self.assertRaises(HTTPError) as err:
            urlopen(request,timeout=3)
        self.assertEqual(err.exception.code,405)

    def test_browser_preflight(self):
        request = Request(
            self.base+"/api/paper/orders",method="OPTIONS",
            headers={"Origin":"http://127.0.0.1:5173",
                     "Access-Control-Request-Method":"POST",
                     "Access-Control-Request-Headers":"content-type,x-openpoly-paper"})
        with urlopen(request,timeout=3) as result:
            self.assertEqual(result.status,204)
            self.assertIn("X-OpenPoly-Paper",result.headers["Access-Control-Allow-Headers"])


if __name__ == "__main__":
    unittest.main()
