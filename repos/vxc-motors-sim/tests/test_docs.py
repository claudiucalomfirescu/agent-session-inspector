"""The shipped artefacts: tool catalogue, day script, recorded demo day.

Proves: R-009, R-022, R-023, R-026, R-027
"""
import json
import os
import sqlite3
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEMO = os.path.join(ROOT, "demo", "data")


class Docs(unittest.TestCase):
    def test_R023_tool_catalogue_is_current(self):
        from apps.catalogue import render
        with open(os.path.join(ROOT, "TOOLS.md"), encoding="utf-8") as f:
            self.assertEqual(f.read(), render(), "TOOLS.md is stale: run python -m apps.catalogue")

    def test_R026_plan_needs_no_llm(self):
        env = {**os.environ, "LLM_BASE_URL": "http://127.0.0.1:9/v1", "OPENROUTER_API_KEY": ""}
        out = subprocess.run([sys.executable, "-m", "sim.run", "--plan"], cwd=ROOT, env=env,
                             capture_output=True, text=True, timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        from sim import day
        self.assertEqual(len(out.stdout.strip().splitlines()), len(day.EVENTS))

    def test_R027_incidents_have_ground_truth(self):
        from sim import day
        incidents = [e for e in day.EVENTS if e.get("incident")]
        self.assertEqual({e["incident"] for e in incidents}, {f"INC-{i}" for i in range(1, 7)})
        for e in incidents:
            self.assertIn(e.get("expect"), ("block", "warn", "either"), e["title"])


@unittest.skipUnless(os.path.exists(os.path.join(DEMO, "proxy.db")), "no recorded demo day yet")
class DemoData(unittest.TestCase):
    def test_R009_demo_data_is_a_complete_run(self):
        for f in ("proxy.db", "runner.jsonl", "summary.json"):
            self.assertTrue(os.path.exists(os.path.join(DEMO, f)), f)
        self.assertTrue(os.listdir(os.path.join(DEMO, "agents")))
        self.assertTrue(os.path.exists(os.path.join(DEMO, "systems", "internal", "messages.parquet")))
        with open(os.path.join(DEMO, "runner.jsonl")) as f:
            events = {json.loads(line)["event"] for line in f}
        self.assertTrue({"day_start", "task_start", "mail", "chat", "day_end"} <= events, events)
        db = sqlite3.connect(os.path.join(DEMO, "proxy.db"))
        try:
            n, users = db.execute("SELECT count(*), count(DISTINCT agent) FROM calls").fetchone()
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            db.close()
        self.assertGreater(n, 100)
        self.assertGreater(users, 12)
        self.assertTrue({"calls", "signals", "admin_actions"} <= tables)
        self.assertTrue(os.path.exists(os.path.join(ROOT, "viz", "workday.html")))

    def test_R022_demo_data_has_no_key(self):
        for root, _, files in os.walk(DEMO):
            for f in files:
                with open(os.path.join(root, f), "rb") as fh:
                    self.assertNotIn(b"sk-or-v1-", fh.read(), f)
