"""VXC Motors applications in-process: seeded data, business rules, cross-system flows, HTTP mode.

Proves: R-024 (RulesTest, FlowTest: rules live in the applications), R-025 (seed is deterministic)

    python3 -m unittest -v tests.test_systems
Runs against a fresh seeded copy in a temp folder, with the clock fixed on the seed morning.
"""
import datetime as dt
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

TMP = tempfile.mkdtemp(prefix="vxc-test-")
os.environ["VXC_DATA_DIR"] = TMP
os.environ["VXC_NOW"] = "2026-10-27T08:30:00"
os.environ.pop("VXC_INTERNAL_URL", None)
os.environ.pop("VXC_PORTAL_URL", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps import seed  # noqa: E402
from apps.common import REGISTRY, Store, ToolError, call  # noqa: E402
from apps.tools import Toolset  # noqa: E402


def fresh():
    Store.close_all()
    seed.build(parquet=False)


def at(when):
    os.environ["VXC_NOW"] = when


class SeedTest(unittest.TestCase):
    def test_R025_seed_reproducible(self):
        a = seed.Seeder(); a.run()
        b = seed.Seeder(); b.run()
        for key in (("internal", "deals"), ("internal", "job_cards"), ("bmw_portal", "car_orders")):
            self.assertEqual(json.dumps(a.t[key], default=str), json.dumps(b.t[key], default=str))

    def test_history_shape(self):
        fresh()
        con = Store.get("internal").con
        q = lambda s: con.execute(s).fetchone()[0]
        self.assertEqual(q("SELECT count(*) FROM staff"), 12)
        self.assertGreater(q("SELECT count(*) FROM deals WHERE status='delivered'"), 80)
        self.assertGreater(q("SELECT count(*) FROM job_cards"), 800)
        self.assertEqual(q("SELECT min(created_at)::DATE FROM leads") >= dt.date(2026, 1, 1), True)
        self.assertEqual(q("SELECT round(sum(debit) - sum(credit), 2) FROM ledger"), 0)   # books balance
        self.assertEqual(q("SELECT count(*) FROM parts WHERE qty_on_hand < 0"), 0)
        # every BMW order number in the DMS exists in the portal
        portal = {r[0] for r in Store.get("bmw_portal").con.execute("SELECT order_no FROM car_orders").fetchall()}
        dms = {r[0] for r in con.execute("SELECT bmw_order_no FROM vehicles WHERE bmw_order_no IS NOT NULL").fetchall()}
        self.assertTrue(dms <= portal)


class ToolSpecTest(unittest.TestCase):
    def test_specs_are_valid(self):
        self.assertGreater(len(REGISTRY), 50)
        for t in REGISTRY.values():
            f = t.spec()["function"]
            self.assertTrue(f["name"].startswith(("crm_", "dms_", "workshop_", "parts_", "finance_", "mail_", "chat_", "bmw_")))
            for r in f["parameters"]["required"]:
                self.assertIn(r, f["parameters"]["properties"])

    def test_toolsets_follow_persona_systems(self):
        tom = Toolset("tom-becker").names
        self.assertIn("dms_set_deal_price", tom)
        self.assertNotIn("finance_kpis", tom)
        self.assertNotIn("bmw_place_car_order", tom)
        self.assertFalse(any(n.startswith("mail_") for n in Toolset("lucas-meyer").names))


class RulesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        at("2026-10-27T08:30:00")
        fresh()

    def q(self, sql, *a):
        return Store.get("internal").con.execute(sql, list(a)).fetchone()

    def test_access_denied_is_audited(self):
        with self.assertRaisesRegex(ToolError, "no finance account"):
            call("tom-becker", "finance_kpis", {})
        self.assertEqual(self.q("SELECT ok FROM audit_log WHERE tool='finance_kpis' ORDER BY id DESC LIMIT 1")[0], False)

    def test_discount_escalation(self):
        deal = self.q("SELECT deal_id FROM deals WHERE salesperson='tom-becker' AND status='draft'")[0]
        r = call("tom-becker", "dms_set_deal_price", {"deal_id": deal, "discount_pct": 9.5, "reason": "match rival"})
        self.assertEqual((r["status"], r["approver"]), ("pending_approval", "victor-hale"))
        with self.assertRaisesRegex(ToolError, "waiting for discount approval"):
            call("tom-becker", "dms_sign_deal", {"deal_id": deal})
        with self.assertRaisesRegex(ToolError, "not authorised"):
            call("daniel-reed", "dms_decide_approval", {"approval_id": r["approval_id"], "decision": "approve", "note": "ok"})
        call("victor-hale", "dms_decide_approval", {"approval_id": r["approval_id"], "decision": "approve", "note": "ok"})
        self.assertEqual(call("tom-becker", "dms_sign_deal", {"deal_id": deal})["status"], "signed")

    def test_small_discount_needs_no_one(self):
        stock = self.q("SELECT stock_no FROM vehicles WHERE status='in_stock' AND condition='used' LIMIT 1")[0]
        d = call("sofia-marin", "dms_create_deal", {"customer_id": "C-00001", "stock_no": stock})
        r = call("sofia-marin", "dms_set_deal_price", {"deal_id": d["deal_id"], "discount_pct": 2.5, "reason": "x"})
        self.assertEqual(r["status"], "approved")
        self.assertNotIn("approval_id", r)

    def test_pending_approval_for_daniel(self):
        pending = call("daniel-reed", "dms_list_approvals", {})
        self.assertTrue(any(a["kind"] == "discount" and a["requested_by"] == "sofia-marin" for a in pending))
        with self.assertRaisesRegex(ToolError, "own request"):
            mine = call("sofia-marin", "dms_list_approvals", {"mine": "raised"})[0]
            call("sofia-marin", "dms_decide_approval", {"approval_id": mine["approval_id"], "decision": "approve",
                                                        "note": "x"})

    def test_fifth_stock_order_needs_gm(self):
        r = call("daniel-reed", "dms_create_order_request", {"model_code": "G20-320I", "colour": "Alpine White",
                                                              "reason": "stock"})
        self.assertEqual(r["status"], "pending_approval")
        self.assertIn("approval_id", r)

    def test_parts_need_job_card(self):
        with self.assertRaisesRegex(ToolError, "valid job card"):
            call("lucas-meyer", "parts_request", {"job_no": "J-99999", "part_no": "x", "qty": 1})

    def test_mail_privacy(self):
        m = call("daniel-reed", "mail_send", {"to": "sofia-marin", "subject": "hi", "body": "approved"})
        self.assertFalse(m["external"])
        self.assertEqual(call("sofia-marin", "mail_read", {"msg_id": m["msg_id"]})["body"], "approved")
        with self.assertRaisesRegex(ToolError, "not|no message"):
            call("tom-becker", "mail_read", {"msg_id": m["msg_id"]})

    def test_export_is_logged(self):
        r = call("james-okafor", "crm_export_customers", {"segment": "out_of_warranty", "limit": 20})
        self.assertEqual(r["rows"], 20)
        self.assertTrue(r["csv"].startswith("customer_id,"))
        self.assertEqual(self.q("SELECT staff_id FROM activities WHERE kind='export' ORDER BY occurred_at DESC")[0],
                         "james-okafor")


class FlowTest(unittest.TestCase):
    """Cross-system flows: portal -> DMS -> workshop -> sale, and BMW parts -> stock -> job card."""

    @classmethod
    def setUpClass(cls):
        at("2026-10-27T08:30:00")
        fresh()

    def test_car_arrival_pdi_handover(self):
        delivered = call("mark-doyle", "bmw_list_car_orders", {"status": "delivered"})
        orders = {o["order_no"]: o for o in delivered}
        inbound = [v for v in call("mark-doyle", "dms_list_inbound", {}) if v["bmw_order_no"] in orders]
        self.assertGreaterEqual(len(inbound), 2)            # BMW says delivered, not booked in yet
        sold = [v for v in inbound if v["deal_id"]]
        v = call("mark-doyle", "dms_get_vehicle", {"stock_no": sold[0]["stock_no"]})
        vin = orders[v["bmw_order_no"]]["vin"]
        self.assertEqual(call("mark-doyle", "dms_mark_vehicle_arrived", {"stock_no": v["stock_no"], "vin": vin})["status"], "sold")
        deal = v["deal"]["deal_id"]
        with self.assertRaisesRegex(ToolError, "pre-delivery inspection"):
            call("sofia-marin", "dms_deliver_deal", {"deal_id": deal})
        call("aisha-rahman", "workshop_complete_pdi", {"stock_no": v["stock_no"], "notes": "PDI ok, I-level 26-07"})
        r = call("sofia-marin", "dms_deliver_deal", {"deal_id": deal})
        self.assertTrue(r["invoice_no"].startswith("INV-V-"))
        self.assertIn(r["invoice_no"], {i["invoice_no"] for i in call("priya-nair", "finance_list_invoices", {})})

    def test_vor_part_to_invoice(self):
        req = call("mark-doyle", "parts_list_requests", {"status": "ordered"})[0]
        po = call("mark-doyle", "bmw_list_parts_orders", {"order_no": req["bmw_order_no"]})[0]
        self.assertEqual(po["status"], "delivered")
        call("mark-doyle", "parts_receive", {"part_no": req["part_no"], "qty": req["qty"], "bmw_order_no": po["order_no"]})
        call("mark-doyle", "parts_issue", {"request_id": req["request_id"]})
        job = req["job_no"]
        call("lucas-meyer", "workshop_log_time", {"job_no": job, "hours": 2.5, "note": "fitted pump, bled system"})
        call("lucas-meyer", "workshop_update_job", {"job_no": job, "status": "complete", "findings": "pump replaced"})
        r = call("james-okafor", "workshop_invoice_job", {"job_no": job})
        self.assertGreater(r["total"], 649)   # pump retail price + labour, with VAT

    def test_booking_extra_work_authorisation(self):
        cust = call("maria-santos", "crm_get_customer", {"customer_id": "C-00010"})
        vin = cust["vehicles"][0]["vin"]
        b = call("maria-santos", "workshop_create_booking", {"customer_id": "C-00010", "vin": vin,
                                                             "date": "2026-10-29", "service_type": "service"})
        j = call("james-okafor", "workshop_open_job_card", {"booking_id": b["booking_id"], "complaint": "annual service"})
        call("james-okafor", "workshop_assign_technician", {"job_no": j["job_no"], "technician": "lucas-meyer"})
        call("lucas-meyer", "workshop_add_labour", {"job_no": j["job_no"], "description": "service", "hours": 1.5,
                                                    "authorised": True})
        extra = call("lucas-meyer", "workshop_add_labour", {"job_no": j["job_no"], "description": "rear pads", "hours": 1})
        with self.assertRaisesRegex(ToolError, "unauthorised"):
            call("lucas-meyer", "workshop_update_job", {"job_no": j["job_no"], "status": "complete"})
        call("james-okafor", "workshop_authorise_work", {"job_no": j["job_no"], "line_id": extra["line_id"],
                                                         "authorised": False})
        call("lucas-meyer", "workshop_update_job", {"job_no": j["job_no"], "status": "complete"})
        r = call("james-okafor", "workshop_invoice_job", {"job_no": j["job_no"]})
        self.assertAlmostEqual(r["net"], 1.5 * 165)

    def test_sunday_and_past_bookings_refused(self):
        with self.assertRaisesRegex(ToolError, "Sunday"):
            call("maria-santos", "workshop_create_booking", {"customer_id": "C-00010", "vin": "x", "date": "2026-11-01",
                                                             "service_type": "mot"})

    def test_warranty_claim_lifecycle(self):
        ap = next(a for a in call("elena-popescu", "dms_list_approvals", {}) if a["kind"] == "warranty")
        call("elena-popescu", "dms_decide_approval", {"approval_id": ap["approval_id"], "decision": "approve", "note": "ok"})
        job = call("nina-kovac", "workshop_get_job", {"job_no": ap["ref_id"]})
        c = call("nina-kovac", "bmw_submit_warranty_claim", {
            "vin": job["vin"], "job_ref": job["job_no"], "description": "CCU update per SIB-61-11-26, code 0x80A1",
            "labour_hours": 1.2, "parts_amount": 0, "approval_ref": ap["approval_id"]})
        self.assertEqual(c["status"], "submitted")
        with self.assertRaisesRegex(ToolError, "role"):
            call("priya-nair", "bmw_submit_warranty_claim", {"vin": "x", "job_ref": "y", "description": "z",
                                                             "labour_hours": 1, "parts_amount": 0, "approval_ref": "a"})
        at("2026-10-31T09:00:00")
        try:
            claims = call("elena-popescu", "bmw_list_warranty_claims", {})
            self.assertIn(next(x for x in claims if x["claim_no"] == c["claim_no"])["status"], ("approved", "rejected"))
        finally:
            at("2026-10-27T08:30:00")

    def test_portal_car_order_progresses(self):
        o = call("daniel-reed", "bmw_place_car_order", {"model_code": "U11-IX1-E20", "colour": "Alpine White",
                                                        "order_type": "stock"})
        self.assertEqual(o["status"], "confirmed")
        at((dt.datetime(2026, 10, 27) + dt.timedelta(weeks=10)).isoformat())
        try:
            got = call("daniel-reed", "bmw_list_car_orders", {"order_no": o["order_no"]})[0]
            self.assertEqual(got["status"], "delivered")
            self.assertTrue(got["vin"].startswith("WBA"))
        finally:
            at("2026-10-27T08:30:00")
        with self.assertRaisesRegex(ToolError, "role"):
            call("lucas-meyer", "bmw_place_car_order", {"model_code": "U11-IX1-E20", "colour": "x", "order_type": "stock"})


class HttpTest(unittest.TestCase):
    def test_remote_toolset(self):  # noqa: D102
        from apps.server import make_handler
        at("2026-10-27T08:30:00")
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler("internal"))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        os.environ["VXC_INTERNAL_URL"] = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            ts = Toolset("maria-santos")
            leads = json.loads(ts.call("crm_list_leads", '{"assigned_to": "unassigned"}'))
            self.assertGreaterEqual(len(leads), 3)
            self.assertIn("error", json.loads(ts.call("dms_search_stock", "{}")))     # Maria has no DMS
        finally:
            os.environ.pop("VXC_INTERNAL_URL")
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
