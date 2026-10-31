"""The demo: offline run, recorded data, the fixture other repos test against, and self-containment.

    python3 -m unittest -v tests.test_demo
"""
import ast
import glob
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from helpers import ROOT, free_port

DEMO_DB = os.path.join(ROOT, "demo", "data", "demo.db")
SCHEMA_1 = {"id", "ts", "duration_ms", "user", "agent", "dept", "session", "method", "path", "status", "model",
            "upstream_model", "finish_reason", "usage", "cost_usd", "error", "request", "response", "labels"}
SCHEMA_2 = {"calls": {"firewall_level"},
            "signals": {"id", "ts", "session", "user", "agent", "call_id", "turn", "direction", "level", "topic",
                        "detector", "rule", "matched", "rationale", "confidence", "excerpt", "ref"},
            "admin_actions": {"id", "ts", "actor", "action", "session", "user", "agent", "topic", "reason", "ref",
                              "call_id"}}
sys.path.insert(0, os.path.join(ROOT, "demo"))


class DemoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_R040_offline_demo_runs_without_a_key(self):
        db = os.path.join(self.tmp, "proxy.db")
        env = {k: v for k, v in os.environ.items() if k != "OPENROUTER_API_KEY"}
        env.update(PROXY_LOG_DB=db, FAKE_LLM_PORT=str(free_port()), FAKE_LLM_LATENCY_MS="0")
        out = subprocess.run([sys.executable, os.path.join(ROOT, "demo", "run.py"), "--offline", "--only", "6",
                              "--port", str(free_port())], cwd=self.tmp, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr[-2000:])
        con = sqlite3.connect(db)
        users = {r[0] for r in con.execute("SELECT user FROM calls")}
        sessions = con.execute("SELECT COUNT(DISTINCT session) FROM calls").fetchone()[0]
        tools = con.execute("SELECT COUNT(*) FROM calls WHERE finish_reason='tool_calls'").fetchone()[0]
        self.assertEqual(sessions, 6)
        self.assertGreaterEqual(len(users), 2)
        self.assertGreater(tools, 0)

    def test_R041_recorded_data_loads_once_and_can_be_redated(self):
        import recording
        files = sorted(glob.glob(os.path.join(ROOT, "demo", "data", "*.json")))
        self.assertTrue(files)
        db = os.path.join(self.tmp, "p.db")
        n = recording.load(files, db)
        self.assertGreater(n, 0)
        self.assertEqual(recording.load(files, db), 0)  # second load adds nothing
        db2 = os.path.join(self.tmp, "r.db")
        recording.load(files, db2, redate_days=7, anchor="2026-11-10")
        con = sqlite3.connect(db2)
        days = {r[0] for r in con.execute("SELECT substr(ts, 1, 10) FROM calls")}
        self.assertTrue(days <= {f"2026-11-{d:02d}" for d in range(4, 11)}, days)
        self.assertGreater(len(days), 1)
        self.assertTrue(all(json.loads(r[0])["redated"] for r in con.execute("SELECT labels FROM calls")))
        # a session moves as a whole; intent checks travel with the session they judged instead
        for (s,) in con.execute("SELECT DISTINCT session FROM calls WHERE session != 'firewall-intent'"):
            self.assertEqual(con.execute("SELECT COUNT(DISTINCT substr(ts,1,10)) FROM calls WHERE session=?", (s,)).fetchone()[0], 1)

    def test_R042_demo_db_fixture_follows_the_log_schema(self):
        con = sqlite3.connect(f"file:{DEMO_DB}?mode=ro", uri=True)
        cols = {r[1] for r in con.execute("PRAGMA table_info(calls)")}
        self.assertTrue(SCHEMA_1 <= cols, SCHEMA_1 - cols)
        users = {r[0] for r in con.execute("SELECT user FROM calls")}
        self.assertTrue({"maya", "omar", "lena", "raj"} <= users)
        self.assertGreaterEqual(con.execute("SELECT COUNT(DISTINCT session) FROM calls").fetchone()[0], 12)
        self.assertGreaterEqual(con.execute("SELECT COUNT(DISTINCT substr(ts,1,10)) FROM calls").fetchone()[0], 3)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM calls WHERE user IS NULL OR session IS NULL").fetchone()[0], 0)
        dump = "".join(r[0] or "" for r in con.execute("SELECT request || response FROM calls"))
        self.assertNotIn("sk-or-", dump)  # no provider key in shipped data

    def test_R242_demo_db_has_the_firewall_tables_with_every_level(self):
        con = sqlite3.connect(f"file:{DEMO_DB}?mode=ro", uri=True)
        for table, cols in SCHEMA_2.items():
            have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
            self.assertTrue(cols <= have, (table, cols - have))
        levels = {r[0] for r in con.execute("SELECT DISTINCT level FROM signals")}
        self.assertEqual(levels, {"info", "warning", "block"})
        self.assertEqual({r[0] for r in con.execute("SELECT DISTINCT firewall_level FROM calls WHERE firewall_level IS NOT NULL")},
                         {"info", "warning", "block"})
        self.assertGreater(con.execute("SELECT COUNT(*) FROM admin_actions WHERE action='block_session'").fetchone()[0], 2)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM signals WHERE user IS NULL").fetchone()[0], 0)
        # every signal points at a call of the same session (the console joins on it)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM signals s LEFT JOIN calls c ON c.id = s.call_id "
                                     "WHERE c.id IS NULL OR c.session != s.session").fetchone()[0], 0)

    def test_R043_pacer_spaces_calls(self):
        from team import Pacer
        p = Pacer(0.2)
        start = time.monotonic()
        for _ in range(3):
            p.wait()
        self.assertGreaterEqual(time.monotonic() - start, 0.38)


class SelfContainedTest(unittest.TestCase):
    """Proves: R-100, R-101"""
    STDLIB_ONLY = ["proxy", "dashboard"]

    def imports(self, path):
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                yield from (a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                yield node.module.split(".")[0]

    def local_modules(self):
        names = set()
        for p in glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True):
            names.add(os.path.splitext(os.path.basename(p))[0])
        return names | {"client"}

    def test_R100_proxy_and_dashboard_need_only_the_standard_library(self):
        allowed = set(sys.stdlib_module_names) | self.local_modules() | {"yaml"}  # yaml: the firewall topics file only
        for d in self.STDLIB_ONLY:
            for p in glob.glob(os.path.join(ROOT, d, "*.py")):
                with self.subTest(p=p):
                    self.assertEqual(set(self.imports(p)) - allowed, set())

    def test_R101_no_imports_from_outside_the_folder(self):
        allowed = set(sys.stdlib_module_names) | self.local_modules() | {"openai", "yaml"}
        for p in glob.glob(os.path.join(ROOT, "**", "*.py"), recursive=True):
            with self.subTest(p=p):
                self.assertEqual(set(self.imports(p)) - allowed, set())
                self.assertNotIn("..", "".join(l for l in open(p) if "sys.path" in l and ".." in l and "ROOT" not in l))


if __name__ == "__main__":
    unittest.main()
