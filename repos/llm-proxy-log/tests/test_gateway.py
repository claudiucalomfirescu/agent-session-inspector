"""Gateway rules against a fake OpenRouter (no network, no real requests).   python3 -m unittest -v tests.test_gateway

The gateway is tested as a library (proxy/gateway.py) because its rules are about timing and budgets that
a black-box test could only reach slowly."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "proxy"))
from gateway import Config, Gateway, RateLimiter  # noqa: E402

FREE, PAID = "nvidia/nemotron-3.5-super-vl:free", "z-ai/glm-5.3-flash"


class FakeOpenRouter(BaseHTTPRequestHandler):
    script = {}      # model -> list of (status, body) to return before answering normally
    seen = []        # models requested, in order
    key = {"usage": 0, "free_model_daily_requests": {"used": 10, "limit": 1000, "remaining": 990}}

    def do_GET(self):
        self._send(200, {"data": FakeOpenRouter.key})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeOpenRouter.seen.append(req["model"])
        queue = FakeOpenRouter.script.get(req["model"]) or []
        if queue:
            status, body = queue.pop(0)
            if status == "hang":
                time.sleep(body)
                return self._send(200, {"model": req["model"], "choices": [{"message": {"role": "assistant", "content": "late"}}]})
            return self._send(status, body)
        usage = {"prompt_tokens": 1000, "completion_tokens": 200, "total_tokens": 1200}
        if req["model"] == PAID:
            usage["cost"] = 0.25
        self._send(200, {"model": req["model"], "choices": [{"message": {"role": "assistant", "content": "hi"},
                                                              "finish_reason": "stop"}], "usage": usage})

    def _send(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def rate_limited(kind):
    return 429, {"error": {"code": 429, "message": f"Rate limit exceeded: free-models-{kind}"}}


class GatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeOpenRouter)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/api/v1"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        FakeOpenRouter.script, FakeOpenRouter.seen = {}, []
        FakeOpenRouter.key = {"usage": 0, "free_model_daily_requests": {"used": 10, "limit": 1000, "remaining": 990}}
        self.tmp = tempfile.mkdtemp()

    def gateway(self, **kw):
        cfg = Config(primary_model=FREE, fallback_model=PAID, backoff_s=0.01, key_refresh_s=0,
                     db_path=os.path.join(self.tmp, "gw.db"), **kw)
        return Gateway(self.url, "test-key", cfg)

    def call(self, gw, model=FREE, content="hello"):
        body = json.dumps({"model": model, "messages": [{"role": "user", "content": content}]}).encode()
        status, _, data, meta = gw.chat("/chat/completions", body, {"Content-Type": "application/json"})
        return status, json.loads(data), meta

    def test_R022_free_model_used_normally(self):
        status, body, meta = self.call(self.gateway())
        self.assertEqual((status, meta["route"], body["model"]), (200, "primary", FREE))

    def test_R021_per_minute_429_retries_on_free_model_not_fallback(self):
        FakeOpenRouter.script = {FREE: [rate_limited("per-min"), rate_limited("per-min")]}
        status, body, meta = self.call(self.gateway())
        self.assertEqual((status, meta["route"], meta["attempts"]), (200, "primary", 3))
        self.assertEqual(FakeOpenRouter.seen, [FREE, FREE, FREE])

    def test_R021_busy_provider_retries_on_free_model(self):
        FakeOpenRouter.script = {FREE: [(503, {"error": {"code": 503, "message": "provider at capacity"}})]}
        status, _, meta = self.call(self.gateway())
        self.assertEqual((status, meta["route"]), (200, "primary"))
        self.assertNotIn(PAID, FakeOpenRouter.seen)

    def test_R022_daily_cap_429_switches_to_fallback_and_stays_there(self):
        FakeOpenRouter.script = {FREE: [rate_limited("per-day")]}
        gw = self.gateway()
        status, body, meta = self.call(gw)
        self.assertEqual((status, meta["route"], body["model"], meta["cost_usd"]), (200, "fallback", PAID, 0.25))
        self.call(gw, content="second")
        self.assertEqual(FakeOpenRouter.seen, [FREE, PAID, PAID])

    def test_R022_daily_cap_seen_in_key_info_goes_straight_to_fallback(self):
        FakeOpenRouter.key["free_model_daily_requests"] = {"used": 1000, "limit": 1000, "remaining": 0}
        _, _, meta = self.call(self.gateway())
        self.assertEqual(meta["route"], "fallback")
        self.assertEqual(FakeOpenRouter.seen, [PAID])

    def test_R022_hanging_free_model_times_out_to_fallback(self):
        FakeOpenRouter.script = {FREE: [("hang", 2.0)]}
        started = time.time()
        status, body, meta = self.call(self.gateway(free_timeout_s=0.5))
        self.assertEqual((status, meta["route"], body["model"]), (200, "fallback", PAID))
        self.assertLess(time.time() - started, 1.9)

    def test_R022_provider_504_on_free_model_goes_to_fallback(self):
        FakeOpenRouter.script = {FREE: [(200, {"error": {"code": 504, "message": "A Timeout Occurred"}})]}
        status, body, meta = self.call(self.gateway())
        self.assertEqual((status, meta["route"]), (200, "fallback"))

    def test_R022_fallback_keeps_reasoning_on(self):
        # GLM refuses {"enabled": false}; the gateway asks for the lowest effort instead
        from gateway import _for_fallback
        req = {"model": FREE, "messages": [], "reasoning": {"enabled": False}}
        self.assertEqual(_for_fallback(req, PAID)["reasoning"], {"effort": "low"})
        self.assertEqual(_for_fallback({"model": FREE, "messages": []}, PAID).get("reasoning"), None)

    def test_R023_spend_cap_stops_fallback(self):
        FakeOpenRouter.key["free_model_daily_requests"] = {"used": 1000, "limit": 1000, "remaining": 0}
        gw = self.gateway(spend_cap_usd=0.5)
        self.assertEqual(self.call(gw, content="a")[0], 200)   # 0.25
        self.assertEqual(self.call(gw, content="b")[0], 200)   # 0.50
        status, body, meta = self.call(gw, content="c")
        self.assertEqual((status, meta["route"], body["error"]["metadata"]["gateway"]), (429, "refused", "spend_cap"))

    def test_R023_key_usage_counts_toward_spend_cap(self):
        FakeOpenRouter.key = {"usage": 3.2, "free_model_daily_requests": {"used": 1000, "limit": 1000, "remaining": 0}}
        status, body, _ = self.call(self.gateway(spend_cap_usd=3.0))
        self.assertEqual((status, body["error"]["metadata"]["gateway"]), (429, "spend_cap"))

    def test_R024_replay_serves_from_cache(self):
        self.call(self.gateway())
        gw = self.gateway(cache="replay")
        status, body, meta = self.call(gw)
        self.assertEqual((status, meta["route"], len(FakeOpenRouter.seen)), (200, "cache", 1))

    def test_R024_strict_replay_miss_is_an_error(self):
        status, body, meta = self.call(self.gateway(cache="strict"), content="never recorded")
        self.assertEqual((status, body["error"]["metadata"]["gateway"]), (504, "cache_miss"))
        self.assertEqual(FakeOpenRouter.seen, [])


class RateLimiterTest(unittest.TestCase):
    def test_R020_waits_for_a_slot(self):
        rl = RateLimiter(2, window=0.3)
        start = time.monotonic()
        for _ in range(3):
            self.assertTrue(rl.acquire(5))
        self.assertGreaterEqual(time.monotonic() - start, 0.25)

    def test_R020_gives_up_after_max_wait(self):
        rl = RateLimiter(1, window=10)
        rl.acquire(1)
        self.assertFalse(rl.acquire(0.1))


if __name__ == "__main__":
    unittest.main()
