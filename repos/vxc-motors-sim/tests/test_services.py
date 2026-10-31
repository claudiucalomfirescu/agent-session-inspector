"""Contract tests for the application services (K-vxc-tools@1): agents see the apps only over HTTP.

Proves: R-010, R-011, R-012, R-013, R-014, R-015, R-016, R-017, R-018
Runs offline: the services start in this process on spare ports with a fresh seeded data folder,
and the BMW technical support agent is switched off (VXC_BMW_AGENT=off).
"""
import json
import os
import tempfile
import unittest
import urllib.request

TMP = tempfile.mkdtemp(prefix="vxc-test-")
os.environ.update(VXC_DATA_DIR=TMP, VXC_INTERNAL_URL="http://127.0.0.1:18100",
                  VXC_PORTAL_URL="http://127.0.0.1:18200", VXC_BMW_AGENT="off", VXC_NOW="2026-10-27T08:30:00")

from agents.toolclient import ToolClient, wait_ready  # noqa: E402
from apps import seed, server  # noqa: E402


def get(path, base="http://127.0.0.1:18100"):
    with urllib.request.urlopen(base + path, timeout=30) as r:
        return json.loads(r.read())


def post(path, body, base="http://127.0.0.1:18100"):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


class Services(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        seed.build(parquet=False)
        cls.servers = [server.serve("internal", port=18100), server.serve("bmw_portal", port=18200)]
        wait_ready(60)

    @classmethod
    def tearDownClass(cls):
        for s in cls.servers:
            s.shutdown()

    def test_R010_apps_listed_per_service(self):
        apps = get("/apps")
        self.assertEqual(set(apps), {"crm", "dms", "workshop", "parts", "finance", "mail", "chat"})
        self.assertEqual(set(get("/apps", "http://127.0.0.1:18200")), {"bmw_portal"})

    def test_R011_tools_follow_persona_systems(self):
        tom = ToolClient("tom-becker").names
        self.assertIn("dms_set_deal_price", tom)
        self.assertIn("chat_send", tom)
        self.assertFalse(any(n.startswith(("bmw_", "workshop_", "finance_")) for n in tom))
        lucas = ToolClient("lucas-meyer").names
        self.assertNotIn("mail_send", lucas)          # technicians have no email, only chat
        self.assertIn("bmw_open_tech_case", lucas)

    def test_R012_external_actor_has_only_mail(self):
        ext = ToolClient("ext:hannah.clarke@mail.example")
        self.assertEqual(ext.names, {"mail_inbox", "mail_read", "mail_send"})
        out = post("/call", {"actor": "ext:hannah.clarke@mail.example", "tool": "crm_search_customers",
                             "args": {"query": "a"}})
        self.assertIn("error", out)

    def test_R013_chat_is_stored_and_read_by_tool(self):
        mark, lucas = ToolClient("mark-doyle"), ToolClient("lucas-meyer")
        sent = json.loads(mark.call("chat_send", {"to": "lucas-meyer", "message": "VOR part is in"}))
        self.assertTrue(sent["chat_id"].startswith("CH-"))
        unread = json.loads(lucas.call("chat_unread"))
        self.assertEqual([m["body"] for m in unread if m["chat_id"] == sent["chat_id"]], ["VOR part is in"])
        self.assertEqual(json.loads(lucas.call("chat_unread")), [])   # read once

    def test_R014_email_lands_in_recipient_mailbox(self):
        ext = ToolClient("ext:hannah.clarke@mail.example")
        sent = json.loads(ext.call("mail_send", {"to": "maria-santos", "subject": "Test drive", "body": "Thursday?"}))
        maria = ToolClient("maria-santos")
        inbox = json.loads(maria.call("mail_inbox"))
        self.assertIn(sent["msg_id"], [m["msg_id"] for m in inbox])
        msg = json.loads(maria.call("mail_read", {"msg_id": sent["msg_id"]}))
        self.assertEqual(msg["body"], "Thursday?")

    def test_R015_events_carry_no_message_text(self):
        ToolClient("sofia-marin").call("chat_send", {"to": "daniel-reed", "message": "secret words"})
        ev = get("/events?mail_after=0&chat_after=0")
        self.assertTrue(ev["chat"] and ev["mail"])
        self.assertNotIn("secret words", json.dumps(ev))
        self.assertNotIn("body", ev["mail"][0])

    def test_R016_clock_is_set_by_the_director(self):
        post("/clock", {"now": "2026-10-27T11:11:00"})
        sent = json.loads(ToolClient("tom-becker").call("chat_send", {"to": "sofia-marin", "message": "time?"}))
        hist = json.loads(ToolClient("sofia-marin").call("chat_history", {"colleague": "tom-becker"}))
        self.assertTrue(any(m["chat_id"] == sent["chat_id"] and m["sent_at"].startswith("2026-10-27T11:11")
                            for m in hist))
        post("/clock", {"now": "2026-10-27T08:30:00"})

    def test_R017_tech_case_is_recorded_without_agent(self):
        out = json.loads(ToolClient("aisha-rahman").call(
            "bmw_open_tech_case", {"vin": "WBA0000TEST", "symptom": "HV battery warning after charging"}))
        self.assertEqual(out["status"], "queued")
        self.assertTrue(out["case_no"].startswith("BMW-TC-"))

    def test_R018_every_call_is_audited_and_refusals_explained(self):
        out = json.loads(ToolClient("tom-becker").call("dms_set_deal_price", {"deal_id": "D-NOPE", "discount_pct": 2}))
        self.assertIn("error", out)
        from apps.common import Store
        st = Store.get("internal")
        with st.lock:
            n = st.con.execute("SELECT count(*) FROM audit_log WHERE actor='tom-becker' AND tool='dms_set_deal_price' "
                               "AND NOT ok").fetchone()[0]
        self.assertGreaterEqual(n, 1)

    def test_R019_link_bmw_order_creates_stock_record(self):
        victor = ToolClient("victor-hale")
        for a in json.loads(victor.call("dms_list_approvals", {})):
            if a["kind"] == "stock_order":
                victor.call("dms_decide_approval", {"approval_id": a["approval_id"], "decision": "approve", "note": "ok"})
        reqs = json.loads(victor.call("dms_list_order_requests", {"status": "open"}))
        if not reqs:
            self.skipTest("no open order request in the seed")
        out = json.loads(victor.call("dms_link_bmw_order", {"request_id": reqs[0]["request_id"],
                                                             "bmw_order_no": "BMW-CO-TEST01", "model": "BMW i4 eDrive35",
                                                             "list_price": 52900, "cost_price": 40100}))
        self.assertNotIn("error", out, out)
        self.assertTrue(out["stock_no"].startswith("S-"))


if __name__ == "__main__":
    unittest.main()
