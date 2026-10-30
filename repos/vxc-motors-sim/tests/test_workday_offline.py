"""The whole workday, offline: real proxy, real application services, a scripted fake LLM.

Proves: R-001, R-002, R-003, R-004, R-005, R-006, R-007, R-008, R-020, R-021, R-022
Runs `python -m sim.run` as a subprocess (it starts the apps service and the proxy itself) against
sim/fake_llm.py, then reads what the proxy logged and what the director recorded.
"""
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class OfflineWorkday(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, ROOT)
        from sim import fake_llm
        cls.fake = fake_llm.serve(0)
        cls.dir = tempfile.mkdtemp(prefix="vxc-day-")
        env = {**os.environ,
               "VXC_DATA_DIR": os.path.join(cls.dir, "data"), "VXC_RUN_DIR": os.path.join(cls.dir, "run"),
               "VXC_INTERNAL_URL": "http://127.0.0.1:18110", "VXC_PORTAL_URL": "http://127.0.0.1:18210",
               "UPSTREAM_BASE_URL": f"http://127.0.0.1:{cls.fake.server_port}/api/v1",
               "OPENROUTER_API_KEY": "sk-fake-test", "PROXY_PORT": "18090", "LLM_BASE_URL": "http://127.0.0.1:18090/v1",
               "GATEWAY_FREE_RPM": "1000", "GATEWAY_CACHE": "off", "FIREWALL_INTENT": "off", "VXC_BMW_AGENT": "on"}
        env.pop("PROXY_LOG_DB", None)
        env.pop("AGENT_LOG_DIR", None)
        os.makedirs(env["VXC_DATA_DIR"], exist_ok=True)
        cls.proc = subprocess.run([sys.executable, "-m", "sim.run", "--workers", "3"], cwd=ROOT, env=env,
                                  capture_output=True, text=True, timeout=900)
        run = env["VXC_RUN_DIR"]
        cls.rows = [json.loads(line) for line in open(os.path.join(run, "runner.jsonl"))]
        cls.db = sqlite3.connect(os.path.join(run, "proxy.db"))
        cls.calls = cls.db.execute("SELECT agent, labels, request, response FROM calls").fetchall()

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls.fake.shutdown()

    def events(self, kind):
        return [r for r in self.rows if r["event"] == kind]

    def test_R001_day_runs_to_the_end(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr[-2000:])
        self.assertTrue(self.events("day_end"))

    def test_R002_every_agent_call_carries_identity_headers(self):
        self.assertGreater(len(self.calls), 40)
        for agent, labels, _, _ in self.calls:
            if agent == "firewall":
                continue
            lab = json.loads(labels or "{}")
            self.assertEqual(lab.get("user"), agent)
            self.assertTrue(lab.get("dept"), agent)

    def test_R003_outside_parties_are_agents_too(self):
        users = {a for a, *_ in self.calls}
        self.assertTrue(any(u.startswith("customer-") for u in users), users)
        self.assertIn("bmw-retailer-support", users)
        self.assertIn("bmw-tech-support", users)      # the judgment tool's agent

    def test_R004_email_is_a_tool_call_seen_by_the_proxy(self):
        sent = [c for c in self.calls if '"mail_send"' in (c[3] or "")]
        self.assertTrue(sent)

    def test_R005_recipient_reads_mail_by_tool_after_doorbell(self):
        mails = self.events("mail")
        self.assertTrue(mails)
        reads = [r for r in self.events("tool") if r.get("tool") == "mail_read"]
        self.assertTrue(reads)
        # the doorbell names the message, never its body
        for t in self.events("task_start"):
            if "New email MSG-" in t.get("text", ""):
                self.assertIn("Read it with mail_read", t["text"])

    def test_R006_chat_is_a_tool_call_and_read_by_tool(self):
        self.assertTrue(self.events("chat"))
        self.assertTrue([r for r in self.events("tool") if r.get("tool") == "chat_unread"])

    def test_R007_customer_and_bmw_answer_by_email(self):
        replies = [t for t in self.events("task_end") if t.get("task_kind") == "reply"]
        self.assertTrue(replies)
        self.assertTrue(any("mail_send" in (t.get("tools") or []) for t in replies))

    def test_R008_staged_incidents_hit_the_firewall(self):
        blocked = {r.get("incident") for r in self.events("blocked")}
        self.assertTrue({"INC-1", "INC-3", "INC-5"} <= blocked, blocked)

    def test_R020_director_never_touches_business_data(self):
        src = open(os.path.join(ROOT, "sim", "run.py")).read()
        self.assertNotIn("duckdb", src)
        self.assertNotIn("Store.get", src)

    def test_R021_tech_case_answered_by_bmw_agent(self):
        tech = [c for c in self.calls if c[0] == "bmw-tech-support"]
        self.assertTrue(tech)
        self.assertEqual(json.loads(tech[0][1]).get("dept"), "BMW UK")

    def test_R022_no_key_in_logs(self):
        for _, labels, req, resp in self.calls:
            self.assertNotIn("sk-fake-test", (req or "") + (resp or "") + (labels or ""))
