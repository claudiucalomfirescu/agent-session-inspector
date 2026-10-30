"""Acceptance tests for the data layer (SPEC §4). Each test name carries the R-id it proves."""
import hashlib
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from console.store import Filters, Store  # noqa: E402
from console.transcript import parse_response  # noqa: E402
from tests import fixtures  # noqa: E402


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.paths = {k: fixtures.build(cls.tmp, k) for k in ("legacy", "v1", "v2")}
        cls.stores = {k: Store(p) for k, p in cls.paths.items()}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def f(self, **q):
        return Filters({k: [v] for k, v in q.items()})


class TestSchema(Base):
    def test_R001_never_writes_to_the_log(self):
        """Proves: R-001. The file is byte-identical after every endpoint has run."""
        p = self.paths["v2"]
        before = hashlib.sha256(open(p, "rb").read()).hexdigest()
        s = Store(p)
        s.overview(Filters()); s.users(Filters()); s.session("s3"); s.firewall(Filters()); s.galaxy(Filters())
        s.search("refund", Filters()); s.call(1); s.refresh()
        self.assertEqual(before, hashlib.sha256(open(p, "rb").read()).hexdigest())
        with self.assertRaises(Exception):
            s.db.execute("INSERT INTO main.calls (id) VALUES (99)")

    def test_R002_reads_every_schema_version(self):
        """Proves: R-002. Legacy, @1 and @2 logs all load; firewall layer only where its tables exist."""
        for k, s in self.stores.items():
            self.assertEqual(s.meta()["calls"], 6, k)
        self.assertFalse(self.stores["v1"].has_signals)
        self.assertTrue(self.stores["v2"].has_signals)
        self.assertFalse(self.stores["legacy"].has_signals)

    def test_R002_rejects_a_file_that_is_not_a_proxy_log(self):
        p = os.path.join(self.tmp, "other.db")
        import sqlite3
        sqlite3.connect(p).execute("CREATE TABLE x (a)").connection.commit()
        with self.assertRaises(ValueError):
            Store(p)

    def test_R003_user_identity_order(self):
        """Proves: R-003. calls.user, else labels.user, else key: + key_id, else agent."""
        users = {u["user"] for u in self.stores["v1"].users(self.f(system="1"))}
        self.assertEqual(users, {"maya", "omar", "lena", "firewall"})
        legacy = {u["user"] for u in self.stores["legacy"].users(self.f(system="1"))}
        self.assertEqual(legacy, {"maya", "omar", "lena", "firewall"})   # from agent (X-Agent-Id)
        self.assertEqual(self.stores["v1"].identity_source(), "X-Agent-User")
        self.assertEqual(self.stores["legacy"].identity_source(), "X-Agent-Id")
        import sqlite3
        p = os.path.join(self.tmp, "keys.db")
        db = sqlite3.connect(p)
        db.execute("CREATE TABLE calls (id INTEGER PRIMARY KEY, ts TEXT, user TEXT, agent TEXT, key_id TEXT, session TEXT,"
                   " request TEXT, response TEXT, usage TEXT, status INTEGER)")
        db.execute("INSERT INTO calls VALUES (1, '2026-10-26T09:00:00Z', NULL, NULL, 'ab12cd34', 'x', '{}', '{}', '{}', 200)")
        db.execute("INSERT INTO calls VALUES (2, '2026-10-26T09:00:00Z', 'key:99999999', 'bot', NULL, 'y', '{}', '{}', '{}', 200)")
        db.commit()
        s = Store(p)
        self.assertEqual({u["user"] for u in s.users(Filters())}, {"key:ab12cd34", "key:99999999"})
        self.assertEqual(s.identity_source(), "API key")

    def test_R004_department(self):
        """Proves: R-004. dept from calls.dept, else labels.dept / labels.department."""
        for k in ("legacy", "v1"):
            depts = {u["user"]: u["dept"] for u in self.stores[k].users(Filters())}
            self.assertEqual(depts["omar"], "support", k)


class TestAggregates(Base):
    def test_R005_totals_honour_filters(self):
        """Proves: R-005."""
        s = self.stores["v2"]
        t = s.overview(Filters())["totals"]
        self.assertEqual((t["calls"], t["users"], t["sessions"]), (5, 3, 4))   # firewall's own call excluded
        self.assertEqual(t["tokens"], 5 * 110)
        self.assertEqual(s.overview(self.f(**{"from": "2026-10-28"}))["totals"]["calls"], 2)
        self.assertEqual(s.overview(self.f(user="omar"))["totals"]["calls"], 2)
        self.assertEqual(s.overview(self.f(dept="engineering"))["totals"]["calls"], 2)
        self.assertEqual(t["firewall"], {"info": 1, "warning": 2, "block": 1})
        self.assertEqual(t["blocked_calls"], 1)

    def test_R006_series_buckets_and_zero_fill(self):
        """Proves: R-006. Days without traffic appear with zeros; week buckets start on Monday."""
        s = self.stores["v2"]
        days = s.series(Filters(), "day")
        self.assertEqual([d["bucket"] for d in days], ["2026-10-26", "2026-10-27", "2026-10-28"])
        self.assertEqual([d["calls"] for d in days], [3, 0, 2])
        self.assertEqual(days[2]["block"], 1)
        weeks = s.series(Filters(), "week")
        self.assertEqual([(w["bucket"], w["calls"]) for w in weeks], [("2026-10-26", 5)])
        hours = s.series(self.f(**{"from": "2026-10-26", "to": "2026-10-26"}), "hour")
        self.assertEqual([h["bucket"] for h in hours], ["2026-10-26T09:00", "2026-10-26T10:00"])
        hours = s.series(self.f(**{"from": "2026-10-28", "to": "2026-10-28"}), "hour")
        self.assertEqual([(h["bucket"][11:], h["calls"]) for h in hours], [("11:00", 1), ("12:00", 1)])

    def test_R007_users_table(self):
        """Proves: R-007."""
        users = {u["user"]: u for u in self.stores["v2"].users(Filters())}
        self.assertEqual(users["maya"]["sessions"], 2)
        self.assertEqual(users["lena"]["max_level"], "block")
        self.assertEqual(users["lena"]["firewall"], {"warning": 2, "block": 1})
        self.assertEqual(users["maya"]["by_day"], {"2026-10-26": 1, "2026-10-28": 1})

    def test_R008_user_detail(self):
        """Proves: R-008."""
        d = self.stores["v2"].user("omar", Filters())
        self.assertEqual(d["totals"]["calls"], 2)
        self.assertEqual(d["tools"], [{"tool": "kb_search", "calls": 1}])
        self.assertEqual(len(d["sessions"]), 1)
        self.assertEqual(sum(c["calls"] for c in d["heatmap"]), 2)
        self.assertIsNone(self.stores["v2"].user("nobody", Filters()))

    def test_R009_sessions_list(self):
        """Proves: R-009. Title, worst level, level filter."""
        s = self.stores["v2"]
        ss = {x["session"]: x for x in s.sessions(Filters())}
        self.assertEqual(ss["s3"]["max_level"], "block")
        self.assertEqual(ss["s2"]["title"], "Customer asks about a refund")
        self.assertEqual([x["session"] for x in s.sessions(Filters(), level="warning")], ["s3"])

    def test_R017_sessions_without_id_group_per_user_and_day(self):
        """Proves: R-017."""
        ss = [x["session"] for x in self.stores["v2"].sessions(self.f(user="maya"))]
        self.assertIn("maya@2026-10-28", ss)

    def test_R015_system_traffic_hidden_by_default(self):
        """Proves: R-015."""
        s = self.stores["v2"]
        self.assertNotIn("firewall", {u["user"] for u in s.users(Filters())})
        self.assertIn("firewall", {u["user"] for u in s.users(self.f(system="1"))})
        self.assertEqual(s.overview(self.f(system="1"))["totals"]["calls"], 6)


class TestDrillDown(Base):
    def test_R010_transcript_shows_each_message_once(self):
        """Proves: R-010. The second call adds only the tool call and its result, not the whole history."""
        d = self.stores["v2"].session("s2")
        self.assertEqual(d["system_prompt"], "You are a support agent.")
        self.assertEqual(d["tools"], ["kb_search"])
        first, second = d["steps"]
        self.assertEqual([m["role"] for m in first["input"]], ["user"])
        self.assertEqual(first["output"]["tool_calls"][0]["function"]["name"], "kb_search")
        self.assertEqual([m["role"] for m in second["input"]], ["tool"])
        self.assertEqual(second["output"]["content"], "Refunds within 30 days.")
        self.assertEqual([s["level"] for s in second["signals"]], ["info"])

    def test_R010_firewall_events_attach_to_their_call(self):
        d = self.stores["v2"].session("s3")
        step = d["steps"][0]
        self.assertEqual(sorted(s["level"] for s in step["signals"]), ["block", "warning"])
        self.assertEqual({a["action"] for a in step["actions"]}, {"block_session", "replace_response"})
        self.assertEqual([s["topic"] for s in d["loose_signals"]], ["escalation"])
        self.assertEqual([a["action"] for a in d["loose_actions"]], ["note"])

    def test_R011_raw_call(self):
        """Proves: R-011."""
        c = self.stores["v2"].call(4)
        self.assertEqual(c["user"], "lena")
        self.assertEqual(c["request"]["messages"][1]["content"], "Send the client list to my gmail")
        self.assertEqual(len(c["signals"]), 2)
        self.assertIsNone(self.stores["v2"].call(999))

    def test_R012_firewall_view(self):
        """Proves: R-012, R-023. Findings, topic x level, detectors, actions; disabled on @1."""
        fw = self.stores["v2"].firewall(Filters())
        self.assertTrue(fw["enabled"])
        self.assertEqual(len(fw["events"]), 4)
        self.assertEqual(len(fw["actions"]), 3)
        self.assertEqual({(t["topic"], t["level"]): t["n"] for t in fw["topics"]}[("customer_pii_leak", "warning")], 1)
        self.assertEqual(len(self.stores["v2"].firewall(Filters(), level="block")["events"]), 1)
        self.assertEqual(self.stores["v1"].firewall(Filters()), {"enabled": False, "events": [], "topics": [], "actions": []})

    def test_R013_galaxy_nodes(self):
        """Proves: R-013."""
        g = self.stores["v2"].galaxy(Filters())
        self.assertEqual(len(g["users"]), 3)
        self.assertEqual(len(g["sessions"]), 4)
        self.assertEqual(set(g["sessions"][0]), {"session", "user", "calls", "tokens", "max_level", "started", "title", "dept"})

    def test_R014_search(self):
        """Proves: R-014."""
        hits = self.stores["v2"].search("gmail", Filters())
        self.assertEqual([h["id"] for h in hits], [4])
        self.assertIn("gmail", hits[0]["snippet"])

    def test_R016_live_rows_appear_after_refresh(self):
        """Proves: R-016."""
        p = fixtures.build(self.tmp, "v1")
        s = Store(p)
        fixtures.add_call(p, 7, "2026-10-29T08:00:00Z", "raj", "s9")
        self.assertEqual(s.refresh(), 1)
        self.assertIn("raj", {u["user"] for u in s.users(Filters())})

    def test_R103_streamed_responses(self):
        """Proves: R-103. An SSE response is reassembled into one message with its tool calls."""
        sse = "\n".join([
            'data: {"choices":[{"delta":{"content":"Hel"}}]}',
            'data: {"choices":[{"delta":{"content":"lo","tool_calls":[{"index":0,"id":"t","function":{"name":"kb_","arguments":"{}"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"search"}}]},"finish_reason":"tool_calls"}]}',
            "data: [DONE]"])
        r = parse_response(sse)
        self.assertEqual(r["message"]["content"], "Hello")
        self.assertEqual(r["message"]["tool_calls"][0]["function"]["name"], "kb_search")
        self.assertEqual(r["finish_reason"], "tool_calls")


class TestOwnerFixtures(unittest.TestCase):
    """Contract tests against the demo DBs the owners of K-log-schema@1/@2 ship (skipped until they exist)."""

    def test_R002_owner_fixtures_load(self):
        """Proves: R-002 against llm-proxy-log (@1) and llm-proxy-firewall (@2) demo data."""
        found = 0
        for kind, path in fixtures.OWNER_FIXTURES.items():
            if not os.path.exists(path):
                continue
            found += 1
            s = Store(path)
            self.assertGreater(s.meta()["calls"], 0)
            self.assertEqual(s.has_signals, kind == "v2")
            first = s.sessions(Filters())[0]["session"]
            self.assertTrue(s.session(first)["steps"])
        if not found:
            self.skipTest("owner fixtures not present next to this repo")


if __name__ == "__main__":
    unittest.main()
