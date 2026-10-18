"""HTTP paper routes: opt-in only, localhost origin protection and no real order paths."""
from http.server import ThreadingHTTPServer
from threading import Thread
from http.client import HTTPConnection
import json
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from services.api.server import make_server
from services.paper_trading.engine import PaperTradeRejected


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
        if account != "demo":
            raise PaperTradeRejected("unsupported")
        return {"mode": "PAPER_ONLY", "account": account, "cash_balance": "1000"}
    def quote(self, account, outcome):
        if account != "demo" or outcome not in ("UP","DOWN"):
            raise PaperTradeRejected("unsupported")
        return {"mode": "PAPER_ONLY", "source": "synthetic_demo", "outcome": outcome}
    def execute(self, account, request):
        self.calls.append((account, request))
        return {"mode": "PAPER_ONLY", "source": "synthetic_demo", "duplicate": False}


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

    def test_get_state_and_demo_quote(self):
        with urlopen(self.base + "/api/paper/state?account=demo", timeout=3) as response:
            self.assertEqual(json.loads(response.read())["cash_balance"], "1000")
        with urlopen(self.base + "/api/paper/quote?account=demo&outcome=UP", timeout=3) as response:
            self.assertEqual(json.loads(response.read())["source"], "synthetic_demo")

    def test_post_requires_explicit_paper_header(self):
        body = json.dumps({"side":"BUY"}).encode()
        request = Request(
            self.base+"/api/paper/orders?account=demo",
            data=body, method="POST", headers={"Content-Type":"application/json"})
        with self.assertRaises(HTTPError) as err:
            urlopen(request, timeout=3)
        self.assertEqual(err.exception.code, 403)
        self.assertEqual(len(self.engine.calls), 0)

    def test_origin_rejects_untrusted_websites(self):
        request = Request(
            self.base+"/api/paper/orders?account=demo", data=b"{}",
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
            self.base+"/api/paper/orders?account=demo", data=b'{"side":"BUY"}',
            method="POST", headers={
                "Content-Type":"application/json",
                "X-OpenPoly-Paper":"1",
                "Origin":"http://127.0.0.1:5173",
            })
        with urlopen(request,timeout=3) as result:
            data=json.loads(result.read())
        self.assertEqual(data["mode"],"PAPER_ONLY")
        self.assertEqual(self.engine.calls[-1],("demo",{"side":"BUY"}))

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
