"""The dashboard's JSON API over a log file.   python3 -m unittest -v tests.test_dashboard"""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
import urllib.request

from helpers import ROOT, get_json, start_dashboard


def make_log(path):
    import sys
    sys.path.insert(0, os.path.join(ROOT, "proxy"))
    from logstore import open_db
    db = open_db(path)
    for i, (user, session, ts) in enumerate([("omar", "s1", "2026-10-29T09:00:00Z"), ("omar", "s1", "2026-10-29T09:00:05Z"),
                                             ("lena", "s2", "2026-10-28T15:00:00Z")]):
        db.execute("INSERT INTO calls (ts, user, agent, session, status, total_tokens, request, response) VALUES (?,?,?,?,?,?,?,?)",
                   (ts, user, "bot", session, 200, 10 + i, json.dumps({"messages": [{"role": "user", "content": f"q{i}"}]}),
                    json.dumps({"choices": [{"message": {"role": "assistant", "content": f"a{i}"}}]})))
    db.commit()
    db.close()


class DashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.db = os.path.join(cls.tmp, "proxy.db")
        make_log(cls.db)
        cls.proc, cls.url = start_dashboard(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_R030_calls_without_bodies_in_time_order(self):
        calls = get_json(self.url + "/api/calls")
        self.assertEqual([c["ts"][:10] for c in calls], ["2026-10-28", "2026-10-29", "2026-10-29"])
        self.assertNotIn("request", calls[0])
        self.assertTrue({"user", "session", "total_tokens", "status", "firewall_level"} <= set(calls[0]))

    def test_R031_one_session_with_bodies_decoded(self):
        rows = get_json(self.url + "/api/session/s1")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["request"]["messages"][0]["content"], "q0")
        self.assertEqual(rows[1]["response"]["choices"][0]["message"]["content"], "a1")

    def test_R032_read_only_and_missing_log_is_empty(self):
        before = os.path.getmtime(self.db)
        get_json(self.url + "/api/calls")
        self.assertEqual(os.path.getmtime(self.db), before)
        proc, url = start_dashboard(os.path.join(self.tmp, "nope.db"))
        try:
            self.assertEqual(get_json(url + "/api/calls"), [])
            self.assertFalse(os.path.exists(os.path.join(self.tmp, "nope.db")))
        finally:
            proc.terminate()
            proc.wait()

    def test_R230_firewall_routes(self):
        self.assertEqual(get_json(self.url + "/api/signals"), [])
        self.assertEqual(get_json(self.url + "/api/actions"), [])

    def test_R033_serves_the_page(self):
        with urllib.request.urlopen(self.url + "/", timeout=5) as r:
            page = r.read().decode()
        for part in ('id="kpis"', 'id="chart"', 'id="users"', 'id="sessions"', 'id="detail"', "/api/calls"):
            self.assertIn(part, page)
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(self.url + "/../proxy/proxy.py", timeout=5)


if __name__ == "__main__":
    unittest.main()
