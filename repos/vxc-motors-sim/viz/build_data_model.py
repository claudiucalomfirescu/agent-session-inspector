"""Build viz/data-model.html: the VXC Motors data model (both databases), with live row counts,
sample rows and the agent tools that touch each table.   python viz/build_data_model.py"""
import inspect
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from apps import tools  # noqa: E402,F401
from apps.common import REGISTRY, SYSTEM_DB, Store, jsonable  # noqa: E402

GROUPS = {
    "internal": [
        ("Company", "staff", ["staff"]),
        ("CRM", "crm", ["customers", "leads", "test_drives", "activities", "customer_vehicles"]),
        ("DMS", "dms", ["vehicles", "deals", "approvals", "order_requests", "invoices"]),
        ("Workshop", "workshop", ["bookings", "job_cards", "job_lines", "time_entries"]),
        ("Parts", "parts", ["parts", "parts_requests", "parts_movements"]),
        ("Finance", "finance", ["ledger"]),
        ("Mail", "mail", ["messages"]),
        ("Audit", "audit", ["audit_log"]),
    ],
    "bmw_portal": [
        ("Dealer access", "portal", ["dealers", "portal_users", "portal_access_log"]),
        ("New cars", "portal", ["models", "car_orders"]),
        ("Parts supply", "portal", ["parts_catalog", "parts_orders", "parts_order_lines"]),
        ("Warranty & quality", "portal", ["warranty_claims", "recalls", "recall_vins", "bulletins"]),
    ],
}
STAFF_COLS = {"assigned_to", "salesperson", "requested_by", "approver", "staff_id", "advisor", "technician",
              "created_by", "added_by", "issued_by"}
# column -> (db, table) it points to, per database
REFS = {
    "internal": {"customer_id": "customers", "lead_id": "leads", "stock_no": "vehicles", "deal_id": "deals",
                 "booking_id": "bookings", "job_no": "job_cards", "part_no": "parts", **{c: "staff" for c in STAFF_COLS}},
    "bmw_portal": {"dealer_no": "dealers", "model_code": "models", "order_no": None, "part_no": "parts_catalog",
                   "recall_code": "recalls", "ordered_by": "portal_users", "submitted_by": "portal_users"},
}
CROSS = {  # links between the two databases (no foreign key can cross them)
    ("internal", "vehicles", "bmw_order_no"): ("bmw_portal", "car_orders"),
    ("internal", "order_requests", "bmw_order_no"): ("bmw_portal", "car_orders"),
    ("internal", "parts_requests", "bmw_order_no"): ("bmw_portal", "parts_orders"),
    ("internal", "vehicles", "model_code"): ("bmw_portal", "models"),
    ("internal", "order_requests", "model_code"): ("bmw_portal", "models"),
    ("bmw_portal", "warranty_claims", "job_ref"): ("internal", "job_cards"),
    ("bmw_portal", "parts_orders", "job_ref"): ("internal", "job_cards"),
    ("bmw_portal", "car_orders", "customer_ref"): ("internal", "order_requests"),
    ("bmw_portal", "portal_users", "email"): ("internal", "staff"),
}
NOTES = {
    "approvals": "One table for every sign-off: discount, goodwill, stock_order, warranty. ref_id points to the deal, job or order request.",
    "audit_log": "Every tool call: who, which tool, arguments, ok or refused. Feeds the admin console.",
    "portal_access_log": "BMW's own record of what each dealer user did in the portal.",
    "ledger": "Double-entry: every invoice, payment and BMW purchase posts balanced debit and credit lines.",
    "vehicles": "Dealer stock, new and used. Status runs on_order, in_transit, in_stock, reserved, sold, delivered.",
    "car_orders": "Status is driven by the clock: confirmed, in_production, shipped, delivered (VIN assigned in production).",
    "customer_vehicles": "Cars customers own; what the workshop services. Delivered sales land here.",
    "messages": "Email between staff and to customers. External addresses are anything outside vxcmotors.example.",
}


def tables_touched(fn):
    src = inspect.getsource(fn)
    found = set(re.findall(r"(?:FROM|JOIN|INTO|UPDATE)\s+([a-z_]+)", src))
    helpers = {"raise_invoice(": ["invoices", "ledger"], "_request_approval(": ["approvals"], "post(": ["ledger"],
               "_move(": ["parts_movements"], "_activity(": ["activities"], "_job(ctx": ["job_cards"],
               "_user(ctx)": ["portal_users"]}
    for k, v in helpers.items():
        if k in src:
            found.update(v)
    return found


def main():
    model = {"dbs": {}, "cross": [], "tools": {}}
    for db in ("internal", "bmw_portal"):
        con = Store.get(db).con
        out = []
        for gname, system, tables in GROUPS[db]:
            g = {"name": gname, "system": system, "tables": []}
            for t in tables:
                cols = con.execute(f"DESCRIBE {t}").fetchall()
                n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                cur = con.execute(f"SELECT * FROM {t} LIMIT 3")
                names = [d[0] for d in cur.description]
                sample = [jsonable(dict(zip(names, r))) for r in cur.fetchall()]
                g["tables"].append({
                    "name": t, "rows": n, "note": NOTES.get(t, ""), "sample": sample,
                    "columns": [{"name": c[0], "type": c[1], "pk": c[3] == "PRI",
                                 "ref": (REFS[db].get(c[0]) if REFS[db].get(c[0]) != t else None),
                                 "cross": "{}.{}".format(*CROSS[(db, t, c[0])]) if (db, t, c[0]) in CROSS else None}
                                for c in cols]})
            out.append(g)
        model["dbs"][db] = out
    for name, tl in REGISTRY.items():
        model["tools"][name] = {"system": tl.system, "db": SYSTEM_DB[tl.system], "writes": tl.writes,
                                "description": tl.description, "tables": sorted(tables_touched(tl.fn))}
    tpl = (ROOT / "viz" / "data_model_template.html").read_text(encoding="utf-8")
    html = tpl.replace("/*__DATA__*/null", json.dumps(model, default=str, separators=(",", ":")))
    (ROOT / "viz" / "data-model.html").write_text(html, encoding="utf-8")
    print(f"wrote viz/data-model.html ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
