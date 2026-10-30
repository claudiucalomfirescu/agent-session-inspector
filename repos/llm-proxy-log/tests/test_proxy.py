"""The proxy as a black box: what reaches the provider, what comes back, what gets logged.

    python3 -m unittest -v tests.test_proxy
"""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

from helpers import REAL_KEY, Upstream, chat_body, free_port, post, rows, start_proxy, start_upstream

LOG_COLUMNS = {"id", "ts", "duration_ms", "user", "agent", "dept", "session", "method", "path", "status", "model",
               "upstream_model", "finish_reason", "usage", "cost_usd", "error", "request", "response", "labels",
               "key_id", "prompt_tokens", "completion_tokens", "total_tokens", "route", "attempts", "firewall_level"}


class ProxyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv, cls.upstream = start_upstream()
        cls.tmp = tempfile.mkdtemp()
        cls.db = os.path.join(cls.tmp, "proxy.db")
        cls.proc, cls.url = start_proxy(cls.upstream, cls.db, PROXY_GATEWAY="off")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait()
        cls.srv.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        Upstream.seen, Upstream.script = [], []

    def last(self):
        return rows(self.db)[-1]

    def test_R001_forwards_and_returns_unchanged(self):
        status, _, body = post(self.url + "/chat/completions", chat_body())
        self.assertEqual(status, 200)
        self.assertEqual(body["choices"][0]["message"]["content"], "pong")
        self.assertEqual(Upstream.seen[0][1], "/v1/chat/completions")
        self.assertEqual(json.loads(Upstream.seen[0][3]), chat_body())

    def test_R002_provider_gets_the_real_key_never_the_clients(self):
        post(self.url + "/chat/completions", chat_body(), {"Authorization": "Bearer client-key-abc"})
        headers = {k.lower(): v for k, v in Upstream.seen[0][2].items()}
        self.assertEqual(headers["authorization"], f"Bearer {REAL_KEY}")

    def test_R003_identity_headers_are_stripped_before_forwarding(self):
        post(self.url + "/chat/completions", chat_body(), {"X-Agent-User": "omar", "X-Agent-Dept": "support",
                                                           "X-Agent-Id": "bot", "X-Session-Id": "s1", "X-Agent-Role": "x"})
        sent = {k.lower() for k in Upstream.seen[0][2]}
        self.assertFalse({h for h in sent if h.startswith("x-agent-") or h == "x-session-id"})

    def test_R004_one_row_per_call_with_the_schema(self):
        before = len(rows(self.db))
        post(self.url + "/chat/completions", chat_body("a"))
        post(self.url + "/chat/completions", chat_body("b"))
        self.assertEqual(len(rows(self.db)), before + 2)
        r = self.last()
        self.assertTrue(LOG_COLUMNS <= set(r), LOG_COLUMNS - set(r))
        self.assertRegex(r["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual((r["method"], r["path"], r["status"], r["model"], r["finish_reason"]),
                         ("POST", "/v1/chat/completions", 200, "test-model", "stop"))
        self.assertEqual(json.loads(r["request"])["messages"][0]["content"], "b")
        self.assertEqual(json.loads(r["response"])["choices"][0]["message"]["content"], "pong")
        self.assertIsInstance(r["duration_ms"], int)

    def test_R005_identity_columns_from_headers(self):
        post(self.url + "/chat/completions", chat_body(), {"X-Agent-User": "omar", "X-Agent-Dept": "support",
                                                           "X-Agent-Id": "support-bot", "X-Session-Id": "sess-9"})
        r = self.last()
        self.assertEqual((r["user"], r["dept"], r["agent"], r["session"]), ("omar", "support", "support-bot", "sess-9"))

    def test_R006_fallback_user_from_key_then_anonymous(self):
        post(self.url + "/chat/completions", chat_body(), {"Authorization": "Bearer team-key-1"})
        r = self.last()
        import hashlib
        kid = hashlib.sha256(b"team-key-1").hexdigest()[:8]
        self.assertEqual((r["user"], r["key_id"], r["agent"]), (f"key:{kid}", kid, f"key:{kid}"))
        post(self.url + "/chat/completions", chat_body())
        r = self.last()
        self.assertEqual((r["user"], r["key_id"], r["agent"]), ("anonymous", None, "anonymous"))

    def test_R007_session_is_derived_when_missing_and_stable_across_turns(self):
        h = {"X-Agent-User": "lena"}
        first = chat_body("plan my call")
        post(self.url + "/chat/completions", first, h)
        s1 = self.last()["session"]
        second = {**first, "messages": first["messages"] + [{"role": "assistant", "content": "ok"},
                                                            {"role": "user", "content": "more"}]}
        post(self.url + "/chat/completions", second, h)
        self.assertEqual(self.last()["session"], s1)
        self.assertRegex(s1, r"^auto-[0-9a-f]{12}$")
        post(self.url + "/chat/completions", chat_body("another task"), h)
        self.assertNotEqual(self.last()["session"], s1)

    def test_R008_other_agent_headers_become_labels(self):
        post(self.url + "/chat/completions", chat_body(), {"X-Agent-User": "raj", "X-Agent-Role": "sre",
                                                           "X-Agent-Sim-Time": "09:30"})
        self.assertEqual(json.loads(self.last()["labels"]), {"role": "sre", "sim-time": "09:30"})

    def test_R009_token_columns_copied_from_usage(self):
        post(self.url + "/chat/completions", chat_body())
        r = self.last()
        self.assertEqual((r["prompt_tokens"], r["completion_tokens"], r["total_tokens"]), (11, 3, 14))
        self.assertEqual(json.loads(r["usage"])["total_tokens"], 14)

    def test_R010_provider_errors_pass_through_and_are_logged(self):
        Upstream.script = [(400, {"error": {"code": 400, "message": "unknown model"}})]
        status, _, body = post(self.url + "/chat/completions", chat_body())
        self.assertEqual((status, body["error"]["message"]), (400, "unknown model"))
        r = self.last()
        self.assertEqual((r["status"], json.loads(r["error"])["message"]), (400, "unknown model"))

    def test_R010_unreachable_provider_is_a_502(self):
        db = os.path.join(self.tmp, "down.db")
        proc, url = start_proxy(f"http://127.0.0.1:{free_port()}/v1", db, PROXY_GATEWAY="off")
        try:
            status, _, body = post(url + "/chat/completions", chat_body())
            self.assertEqual((status, body["error"]["code"]), (502, 502))
            self.assertEqual(rows(db)[-1]["status"], 502)
        finally:
            proc.terminate()
            proc.wait()

    def test_R011_logging_off_records_nothing(self):
        db = os.path.join(self.tmp, "off.db")
        proc, url = start_proxy(self.upstream, db, PROXY_GATEWAY="off", PROXY_LOGGING="off")
        try:
            status, _, _ = post(url + "/chat/completions", chat_body())
            self.assertEqual(status, 200)
            self.assertEqual(rows(db), [])
        finally:
            proc.terminate()
            proc.wait()

    def test_R012_a_failing_log_never_changes_the_reply(self):
        bad = os.path.join(self.tmp, "a-directory.db")
        os.makedirs(bad)
        proc, url = start_proxy(self.upstream, bad, PROXY_GATEWAY="off")
        try:
            status, _, body = post(url + "/chat/completions", chat_body())
            self.assertEqual((status, body["choices"][0]["message"]["content"]), (200, "pong"))
        finally:
            proc.terminate()
            proc.wait()

    def test_R013_no_secret_reaches_the_log(self):
        post(self.url + "/chat/completions", chat_body(f"my token is Bearer abcdefghijklmnop and {REAL_KEY}"),
             {"Authorization": "Bearer client-secret-key-xyz"})
        dump = json.dumps(rows(self.db))
        for secret in (REAL_KEY, "abcdefghijklmnop", "client-secret-key-xyz"):
            self.assertNotIn(secret, dump)

    def test_R014_old_log_files_are_upgraded(self):
        db = os.path.join(self.tmp, "old.db")
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE calls (id INTEGER PRIMARY KEY, ts TEXT, duration_ms INTEGER, agent TEXT, session TEXT, "
                    "method TEXT, path TEXT, status INTEGER, model TEXT, finish_reason TEXT, usage TEXT, error TEXT, "
                    "request TEXT, response TEXT)")
        con.execute("INSERT INTO calls (ts, agent) VALUES ('2026-01-01T00:00:00Z', 'old')")
        con.commit()
        con.close()
        proc, url = start_proxy(self.upstream, db, PROXY_GATEWAY="off")
        try:
            post(url + "/chat/completions", chat_body(), {"X-Agent-User": "new"})
            r = rows(db)
            self.assertEqual([x["agent"] for x in r], ["old", "new"])
            self.assertTrue(LOG_COLUMNS <= set(r[-1]))
        finally:
            proc.terminate()
            proc.wait()

    def test_R001_other_paths_pass_through(self):
        import urllib.request
        with urllib.request.urlopen(self.url + "/models", timeout=10) as r:
            self.assertEqual(json.loads(r.read())["data"][0]["id"], "fake-model")


class GatewayEndpointTest(unittest.TestCase):
    def test_R025_gateway_status_endpoint(self):
        srv, upstream = start_upstream()
        tmp = tempfile.mkdtemp()
        proc, url = start_proxy(upstream, os.path.join(tmp, "p.db"))
        try:
            from helpers import get_json
            st = get_json(url + "/gateway/status")
            self.assertTrue({"primary_model", "fallback_model", "free", "paid", "cache"} <= set(st))
            status, _, _ = post(url + "/chat/completions", chat_body(model="m:free"))
            self.assertEqual(status, 200)
            self.assertEqual(rows(os.path.join(tmp, "p.db"))[-1]["route"], "primary")
        finally:
            proc.terminate()
            proc.wait()
            srv.shutdown()
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
