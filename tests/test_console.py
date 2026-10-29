"""Console model over the synthetic demo day: hierarchy, transcripts, signals and the static export."""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "console"))
import model  # noqa: E402


class ConsoleModelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.db = os.path.join(cls.tmp, "demo.db")
        subprocess.run([sys.executable, os.path.join(ROOT, "console", "seed_demo.py"), "--out", cls.db],
                       check=True, capture_output=True)
        cls.snap = model.build(cls.db)

    def test_hierarchy(self):
        s = self.snap
        self.assertEqual(len(s["people"]), 12)
        self.assertEqual(sum(d["sessions"] for d in s["departments"]), len(s["sessions"]))
        self.assertTrue(all(p["avatar"] for p in s["people"]))

    def test_blocks_and_signals(self):
        blocked = {x["agent"] for x in self.snap["sessions"] if x["blocked"]}
        self.assertEqual(blocked, {"tom-becker", "james-okafor", "mark-doyle", "sofia-marin"})
        self.assertEqual(self.snap["totals"]["signals"]["block"], 6)

    def test_transcript_has_each_message_once_and_pins_signals(self):
        tom = next(x for x in self.snap["sessions"] if x["agent"] == "tom-becker" and x["blocked"])
        convo = self.snap["conversations"][tom["id"]]
        users = [m for m in convo if m["role"] == "user"]
        self.assertEqual(len(users), 2)
        self.assertEqual(len(users[0]["signals"]), 2)  # two warnings on the split-discount ask
        self.assertEqual(convo[-1]["route"], "firewall")

    def test_tool_names_map_to_systems(self):
        self.assertEqual(model.tool_system("bmw_portal_order_parts"), "bmw_portal")
        self.assertEqual(model.tool_system("crm_find_customer"), "crm")
        self.assertEqual(model.tool_system("weather"), "other")

    def test_console_agent_is_hidden(self):
        import sqlite3
        db = sqlite3.connect(self.db)
        db.execute("INSERT INTO calls (ts, agent, session, request, response) VALUES ('2026-10-27T18:00:00Z', "
                   "'console-summarizer', 'x', '{}', '{}')")
        db.commit()
        db.close()
        self.assertNotIn("console-summarizer", {c["agent"] for c in model.build(self.db)["calls"]})

    def test_export_embeds_snapshot(self):
        out = os.path.join(self.tmp, "viz")
        subprocess.run([sys.executable, os.path.join(ROOT, "console", "export.py"), self.db, "--out", out],
                       check=True, capture_output=True)
        page = open(os.path.join(out, "console.html"), encoding="utf-8").read()
        self.assertIn("window.SNAPSHOT = {", page)
        self.assertNotIn("<!--SNAPSHOT-->", page)


if __name__ == "__main__":
    unittest.main()
