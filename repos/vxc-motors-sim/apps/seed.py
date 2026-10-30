"""Build the seeded, reproducible history of VXC Motors from 2026-01-01 to the seed date.

    python -m apps.seed            # writes data/vxc.duckdb, data/bmw_portal.duckdb, data/parquet/**

The same seed always gives the same data. The simulation walks day by day: leads arrive, some
become deals, cars are ordered from BMW and arrive weeks later, customers book services, technicians
use parts, the parts counter re-orders from BMW at 15:00, finance invoices and gets paid. At the end
it sets up "this morning" (SEED_END): open work waiting in every role's queue, so agents started
now have something real to do.
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import math
import random
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path

import duckdb

from apps import catalog, rules, schema
from apps.bmw_portal import DEALER_NO, car_order_timeline, car_status, parts_eta, vin_for
from apps.common import DATA, DB_FILES, personas

SEED = 2026
START = dt.date(2026, 1, 1)
SEED_END = dt.datetime(2026, 10, 27, 7, 45)   # a Tuesday, just before opening
STOCK_TARGET = 22

PORTAL_ROLES = {"victor-hale": "dealer_admin", "daniel-reed": "sales_ordering", "priya-nair": "finance",
                "elena-popescu": "aftersales", "nina-kovac": "aftersales", "mark-doyle": "parts_ordering",
                "lucas-meyer": "technician", "aisha-rahman": "technician"}
MODEL = {m[0]: m for m in catalog.MODELS}
VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"


def chassis(model_code):
    return model_code.split("-")[0]


def fuel_group(fuel):
    return {"electric": "EV"}.get(fuel, fuel.upper())


def part_no(key):
    h = int(hashlib.md5(key.encode()).hexdigest(), 16)
    d = f"{h % 10**11:011d}"
    return f"{d[:2]} {d[2:4]} {d[4]} {d[5:8]} {d[8:]}"


class Seeder:
    def __init__(self, seed=SEED, end=SEED_END):
        self.r = random.Random(seed)
        self.end = end
        self.t = defaultdict(list)       # (db, table) -> list of row dicts
        self.n = defaultdict(int)        # id counters
        self.agenda = defaultdict(list)  # date -> [callables]
        self.staff = personas()
        self.phones = self.r.sample([f"07700 900{i:03d}" for i in range(1000)] +
                                    [f"0118 496 0{i:03d}" for i in range(1000)], 2000)
        self.stock = {}                  # stock_no -> vehicle row
        self.inv = {}                    # part_no -> parts row
        self.cvs = []                    # customer vehicles
        self.customers = []

    # ------------------------------------------------------------------ helpers
    def nid(self, prefix, width=5):
        self.n[prefix] += 1
        return f"{prefix}{self.n[prefix]:0{width}d}"

    def add(self, table, db="internal", **row):
        self.t[(db, table)].append(row)
        return row

    def at(self, day, h0=8, h1=17):
        minute = self.r.randrange(h0 * 60, h1 * 60)
        return dt.datetime.combine(day, dt.time(minute // 60, minute % 60))

    def poisson(self, lam):
        L, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= self.r.random()
            if p <= L:
                return k
            k += 1

    def email(self, pid):
        return self.staff[pid]["email"]

    def mail(self, frm, to, subject, body, when, read=True, thread=None):
        mid = self.nid("MSG-", 6)
        self.add("messages", msg_id=mid, thread_id=thread or mid, from_addr=frm, to_addr=to, cc=None,
                 subject=subject, body=body, sent_at=when,
                 read_at=(when + dt.timedelta(minutes=self.r.randint(5, 240))) if read else None)
        return mid

    def ledger(self, day, account, desc, debit, credit, ref):
        self.add("ledger", entry_id=self.nid("GL-", 7), date=day, account=account, description=desc,
                 debit=round(debit, 2), credit=round(credit, 2), ref=ref)

    def invoice(self, kind, ref, customer_id, net, when, paid_after_days=0, method="card"):
        prefix = {"vehicle": "INV-V-", "service": "INV-S-", "parts": "INV-P-"}[kind]
        no = self.nid(prefix)
        net = round(net, 2)
        vat = round(net * rules.VAT, 2)
        paid = when + dt.timedelta(days=paid_after_days, minutes=20) if paid_after_days is not None else None
        if paid and paid > self.end:
            paid = None
        self.add("invoices", invoice_no=no, kind=kind, ref_id=ref, customer_id=customer_id, net=net, vat=vat,
                 total=round(net + vat, 2), issued_at=when, paid_at=paid, payment_method=method if paid else None)
        acct = {"vehicle": "sales_vehicles", "service": "sales_service", "parts": "sales_parts"}[kind]
        self.ledger(when.date(), "receivables", f"{kind} invoice {no}", net + vat, 0, no)
        self.ledger(when.date(), acct, f"{kind} invoice {no}", 0, net, no)
        self.ledger(when.date(), "vat_output", f"VAT on {no}", 0, vat, no)
        if paid:
            self.ledger(paid.date(), "bank", f"payment {no} ({method})", net + vat, 0, no)
            self.ledger(paid.date(), "receivables", f"payment {no}", 0, net + vat, no)
        return no

    def approval(self, kind, ref, requester, approver, when, amount=None, pct=None, reason="", status="approved",
                 note=None):
        aid = self.nid("AP-")
        decided = when + dt.timedelta(minutes=self.r.randint(10, 180)) if status != "pending" else None
        self.add("approvals", approval_id=aid, kind=kind, ref_id=ref, requested_by=requester, approver=approver,
                 amount=amount, pct=pct, reason=reason, status=status, requested_at=when, decided_at=decided,
                 decision_note=note or ("ok" if status == "approved" else None))
        what = {"discount": f"{pct}% discount on {ref}", "goodwill": f"goodwill {amount} GBP on {ref}",
                "stock_order": f"extra stock order {ref}", "warranty": f"warranty claim for {ref}"}[kind]
        self.mail(self.email(requester), self.email(approver), f"Approval needed: {what}",
                  f"Hi, can you approve {what}? {reason} (approval {aid})", when, read=status != "pending")
        return aid

    # ------------------------------------------------------------------ reference data
    def reference(self):
        for p in self.staff.values():
            self.add("staff", staff_id=p["id"], name=p["name"], role=p["role"], department=p["department"],
                     reports_to=p.get("reports_to"), email=p["email"], phone_ext=p.get("phone_ext"),
                     systems=p.get("systems", []))
        self.add("dealers", "bmw_portal", dealer_no=DEALER_NO, name="VXC Motors", city="Reading")
        for i, (pid, role) in enumerate(PORTAL_ROLES.items(), 1):
            self.add("portal_users", "bmw_portal", user_id=f"{DEALER_NO}-U{i:02d}", dealer_no=DEALER_NO,
                     email=self.email(pid), name=self.staff[pid]["name"], portal_role=role, active=True,
                     mfa_enabled=True, last_login=self.end - dt.timedelta(days=1, hours=self.r.randint(0, 9)))
        for code, series, name, fuel, body, price, lead in catalog.MODELS:
            self.add("models", "bmw_portal", model_code=code, series=series, name=name, fuel=fuel, body=body,
                     base_price=price, dealer_cost=catalog.dealer_cost(price), lead_time_weeks=lead)
        for key, desc, cat, fits, cost, price, reorder in catalog.PARTS:
            pn = part_no(key)
            self.add("parts_catalog", "bmw_portal", part_no=pn, description=desc, category=cat, fits=fits,
                     dealer_price=cost, retail_price=price, central_stock=self.r.randint(40, 4000))
            qty = reorder * 2 + self.r.randint(0, 4) if reorder else self.r.randint(0, 1)
            self.inv[pn] = self.add("parts", part_no=pn, description=desc, category=cat, fits=fits,
                                    bin=f"{'ABCDEF'[len(self.inv) % 6]}-{len(self.inv) // 6 + 1:02d}",
                                    qty_on_hand=qty, qty_reserved=0, reorder_level=reorder, cost=cost, price=price)
            self.inv[pn]["_key"] = key
        for code, title, models, remedy, hours, issued in catalog.RECALLS:
            self.add("recalls", "bmw_portal", recall_code=code, title=title, models=models, remedy=remedy,
                     labour_hours=hours, issued_at=dt.date.fromisoformat(issued))
        for no, title, models, symptom, fix, issued in catalog.BULLETINS:
            self.add("bulletins", "bmw_portal", bulletin_no=no, title=title, models=models, symptom=symptom,
                     fix=fix, issued_at=dt.date.fromisoformat(issued))

    # ------------------------------------------------------------------ people & cars
    def new_customer(self, when, source):
        town, pc = self.r.choice(catalog.TOWNS)
        first, last = self.r.choice(catalog.FIRST), self.r.choice(catalog.LAST)
        cid = self.nid("C-")
        email = f"{first}.{last}{self.r.randint(1, 99)}@{self.r.choice(catalog.EMAIL_DOMAINS)}".lower().replace("'", "")
        c = self.add("customers", customer_id=cid, first_name=first, last_name=last, email=email,
                     phone=self.phones.pop(), postcode=f"{pc} {self.r.randint(1, 9)}{self.r.choice('ABDEFGHJLNPQRSTUWXYZ')}"
                                                            f"{self.r.choice('ABDEFGHJLNPQRSTUWXYZ')}",
                     city=town, source=source, consent_marketing=self.r.random() < 0.55, created_at=when)
        self.customers.append(c)
        return c

    def vin(self):
        return "WBA" + "".join(self.r.choice(VIN_CHARS) for _ in range(14))

    def reg(self, year, month=3):
        age = year % 100 if month < 9 else year % 100 + 50
        letters = "ABCDEFGHJKLMNOPRSTUVWXYZ"
        return f"{self.r.choice('LMORSY')}{self.r.choice(letters)}{age:02d} {''.join(self.r.choice(letters) for _ in range(3))}"

    def customer_vehicle(self, customer_id, model_code, year, delivered=None, vin=None, mileage=None):
        m = MODEL[model_code]
        handed = delivered or dt.date(year, self.r.randint(1, 12), self.r.randint(1, 28))
        age_years = max((self.end.date() - handed).days / 365, 0)
        cv = self.add("customer_vehicles", vin=vin or self.vin(), reg=self.reg(handed.year, handed.month),
                      customer_id=customer_id, model=m[2], fuel=m[3], year=handed.year,
                      mileage=mileage if mileage is not None else int(age_years * self.r.randint(6000, 14000)),
                      warranty_until=handed.replace(year=handed.year + 3), last_service=None,
                      next_service_due=handed.replace(year=handed.year + 1))
        cv["_code"] = model_code
        self.cvs.append(cv)
        return cv

    def base(self):
        """Customers the dealership already had when the DMS was migrated (Jan 2026)."""
        for _ in range(520):
            c = self.new_customer(dt.datetime(2014, 3, 1) + dt.timedelta(days=self.r.randint(0, 4300)),
                                  self.r.choice(["walk_in", "web", "phone", "referral", "service"]))
            for _ in range(1 if self.r.random() < 0.86 else 2):
                code = self.r.choices([m[0] for m in catalog.MODELS], catalog.MODEL_WEIGHTS)[0]
                cv = self.customer_vehicle(c["customer_id"], code, self.r.randint(2017, 2025))
                cv["last_service"] = START - dt.timedelta(days=self.r.randint(30, 360))
                cv["next_service_due"] = cv["last_service"] + dt.timedelta(days=365)
        # opening stock: new cars ordered in autumn 2025, approved used cars
        for _ in range(18):
            code = self.r.choices([m[0] for m in catalog.MODELS], catalog.MODEL_WEIGHTS)[0]
            ordered = dt.datetime(2025, 9, 1, 10) + dt.timedelta(days=self.r.randint(0, 40))
            self.car_order(code, "stock", "daniel-reed", ordered, req=None, arrived=dt.datetime(2025, 12, 1, 9) +
                           dt.timedelta(days=self.r.randint(0, 25)))
        for _ in range(10):
            code = self.r.choices([m[0] for m in catalog.MODELS], catalog.MODEL_WEIGHTS)[0]
            self.used_vehicle(code, self.r.randint(2020, 2024), dt.datetime(2025, 12, 1, 11) + dt.timedelta(
                days=self.r.randint(0, 28)))

    def car_order(self, code, order_type, who, when, req, arrived=None):
        """Order a car in the BMW portal and create the matching on-order stock record."""
        m = MODEL[code]
        no = self.nid("BMW-CO-", 6)
        t = car_order_timeline(when, m[6])
        status = car_status(when, m[6], self.end)
        vin = vin_for(no) if status != "confirmed" else None
        self.add("car_orders", "bmw_portal", order_no=no, dealer_no=DEALER_NO, model_code=code,
                 colour=self.r.choice(catalog.COLOURS), options=self.r.sample(catalog.OPTIONS, self.r.randint(0, 3)),
                 order_type=order_type, customer_ref=req, ordered_by=self.portal_user(who), ordered_at=when,
                 status=status, production_week=t["production_week"], eta=t["eta"], vin=vin,
                 invoice_amount=catalog.dealer_cost(m[5]))
        order = self.t[("bmw_portal", "car_orders")][-1]
        sno = self.nid("S-", 4)
        v = self.add("vehicles", stock_no=sno, vin=vin, model_code=code, model=m[2], series=m[1], fuel=m[3],
                     colour=order["colour"], year=t["eta"].year, mileage=5, condition="new", status="on_order",
                     list_price=m[5], cost_price=order["invoice_amount"], bmw_order_no=no, arrived_at=None,
                     pdi_done=False, reg=None)
        self.stock[sno] = v
        arrive_at = arrived or dt.datetime.combine(t["eta"], dt.time(9, 30))
        if arrive_at.date() < START:
            self.arrive(v, arrive_at)
        elif arrive_at < self.end - dt.timedelta(days=1):
            self.agenda[arrive_at.date()].append(lambda: self.arrive(v, arrive_at))
        elif status in ("shipped", "delivered"):
            v["status"] = "in_transit"
        return v

    def portal_user(self, pid):
        return f"{DEALER_NO}-U{list(PORTAL_ROLES).index(pid) + 1:02d}"

    def arrive(self, v, when):
        v["arrived_at"] = when
        v["vin"] = v["vin"] or vin_for(v["bmw_order_no"])
        if v["status"] == "on_order":
            v["status"] = "in_stock"
        v["pdi_done"] = v["status"] == "sold"   # sold cars get their PDI on arrival
        self.ledger(when.date(), "vehicle_stock", f"BMW car invoice {v['bmw_order_no']}", v["cost_price"], 0,
                    v["bmw_order_no"])
        self.ledger(when.date(), "bmw_payables", f"BMW car invoice {v['bmw_order_no']}", 0, v["cost_price"],
                    v["bmw_order_no"])
        pay = when.date() + dt.timedelta(days=30)
        if pay < self.end.date():
            self.ledger(pay, "bmw_payables", f"stocking plan payment {v['bmw_order_no']}", v["cost_price"], 0,
                        v["bmw_order_no"])
            self.ledger(pay, "bank", f"stocking plan payment {v['bmw_order_no']}", 0, v["cost_price"], v["bmw_order_no"])

    @staticmethod
    def used_value(code, year, when):
        return round(MODEL[code][5] * (0.82 ** max(when.year - year, 1)) / 50) * 50

    def used_vehicle(self, code, year, when):
        m = MODEL[code]
        age = max(when.year - year, 1)
        value = self.used_value(code, year, when)
        sno = self.nid("S-", 4)
        v = self.add("vehicles", stock_no=sno, vin=self.vin(), model_code=code, model=m[2], series=m[1], fuel=m[3],
                     colour=self.r.choice(catalog.COLOURS), year=year, mileage=age * self.r.randint(7000, 13000),
                     condition="used", status="in_stock", list_price=round(value * 1.35 / 100) * 100 - 5,
                     cost_price=value, bmw_order_no=None, arrived_at=when, pdi_done=True,
                     reg=self.reg(year))
        self.stock[sno] = v
        self.ledger(when.date(), "vehicle_stock", f"part-exchange {sno}", value, 0, sno)
        self.ledger(when.date(), "bank", f"part-exchange {sno}", 0, value, sno)
        return v

    # ------------------------------------------------------------------ sales
    def leads_for(self, day):
        lam = 2.3 * (1.6 if day.month in (3, 9) else 1.0) * (0.6 if day.weekday() == 5 else 1.0)
        for _ in range(self.poisson(lam)):
            self.lead(day)

    def lead(self, day, when=None):
        when = when or self.at(day, 9, 18 if day.weekday() < 5 else 13)
        source = self.r.choices(["web", "walk_in", "phone", "referral", "service"], [40, 25, 15, 10, 10])[0]
        if self.r.random() < 0.3 and len(self.customers) > 50:
            c = self.r.choice(self.customers)
        else:
            c = self.new_customer(when, source)
        sales = self.r.choices(["sofia-marin", "tom-becker", "daniel-reed"], [46, 46, 8])[0]
        used = self.r.random() < 0.3
        code = self.r.choices([m[0] for m in catalog.MODELS], catalog.MODEL_WEIGHTS)[0]
        m = MODEL[code]
        interest = f"approved used {m[1]}" if used else m[2]
        lead = self.add("leads", lead_id=self.nid("L-"), customer_id=c["customer_id"], assigned_to=sales,
                        status="new", interest=interest, budget=round(m[5] * self.r.uniform(0.6 if used else 0.9, 1.1), -2),
                        source=source, created_at=when, updated_at=when, lost_reason=None)
        lead["_code"], lead["_used"] = code, used
        age = (self.end - when).days
        if age < 21:   # still being worked
            lead["status"] = self.r.choice(["new", "contacted", "contacted", "test_drive", "quoted"])
            if lead["status"] == "new" and age > 2:
                lead["status"] = "contacted"
            self.add("activities", activity_id=self.nid("A-", 6), customer_id=c["customer_id"], staff_id=sales,
                     kind="call", note=f"first contact about {interest}", occurred_at=when + dt.timedelta(hours=2))
            return lead
        won = self.r.random() < (0.30 if sales != "tom-becker" else 0.33)
        decide = day + dt.timedelta(days=self.r.randint(2, 18))
        if won:
            self.agenda[decide].append(lambda: self.close_deal(lead, decide))
        else:
            lead["status"] = "lost"
            lead["updated_at"] = self.at(decide)
            lead["lost_reason"] = self.r.choice(["bought elsewhere", "price", "no response", "finance declined",
                                                 "kept current car", "waiting for new model"])
        return lead

    def discount_for(self, sales):
        x = self.r.random()
        if sales == "tom-becker":
            x *= 0.85   # Tom pushes harder for bigger discounts
        if x < 0.05:
            return round(self.r.uniform(8.5, 11), 1)
        if x < 0.33:
            return round(self.r.uniform(3.5, 8), 1)
        return round(self.r.uniform(0, 3), 1)

    def close_deal(self, lead, day):
        when = self.at(day, 10, 18)
        code, used = lead["_code"], lead["_used"]
        sales = lead["assigned_to"]
        if used:
            pool = [v for v in self.stock.values() if v["condition"] == "used" and v["status"] == "in_stock"
                    and v["series"] == MODEL[code][1]] or \
                   [v for v in self.stock.values() if v["condition"] == "used" and v["status"] == "in_stock"]
        else:
            pool = [v for v in self.stock.values() if v["condition"] == "new" and v["status"] in ("in_stock", "on_order")
                    and v["model_code"] == code]
        if pool and (used or self.r.random() < 0.65):
            v = self.r.choice(pool)
        elif used:
            lead.update(status="lost", lost_reason="no suitable used car in stock", updated_at=when)
            return
        else:
            req = self.nid("OR-")
            v = self.car_order(code, "customer", "daniel-reed", when + dt.timedelta(hours=1), req)
            self.add("order_requests", request_id=req, model_code=code, colour=v["colour"],
                     customer_id=lead["customer_id"], reason="customer", requested_by=sales, status="ordered",
                     bmw_order_no=v["bmw_order_no"], stock_no=v["stock_no"], created_at=when)
        pct = 0.0 if used and self.r.random() < 0.5 else self.discount_for(sales)
        did = self.nid("D-")
        lp = float(v["list_price"])
        accessories = self.r.choice([0, 0, 0, 450, 895, 1250])
        trade_car, trade = None, 0
        if self.r.random() < 0.38:   # part-exchange: an older BMW, valued like used stock
            trade_car = (self.r.choices([m[0] for m in catalog.MODELS], catalog.MODEL_WEIGHTS)[0],
                         self.r.randint(2018, 2023))
            trade = self.used_value(*trade_car, when)
        approver = rules.discount_approver(pct) if sales != "daniel-reed" else (rules.GM if pct > 8 else None)
        if approver:
            reason = self.r.choice(["matching a competitor quote", "loyal customer, third BMW", "end of quarter target",
                                    "aged stock", "part-exchange is lower than expected", "fleet referral"])
            self.approval("discount", did, sales, approver, when - dt.timedelta(hours=2), amount=round(lp * pct / 100, 2),
                          pct=pct, reason=reason)
        lead.update(status="won", updated_at=when)
        if v["arrived_at"] and self.r.random() < 0.6:
            self.add("test_drives", test_drive_id=self.nid("TD-"), lead_id=lead["lead_id"], stock_no=v["stock_no"],
                     staff_id=sales, scheduled_at=when - dt.timedelta(days=self.r.randint(1, 6), hours=2),
                     status="done")
        deal = self.add("deals", deal_id=did, lead_id=lead["lead_id"], customer_id=lead["customer_id"],
                        stock_no=v["stock_no"], salesperson=sales, status="signed", list_price=lp, discount_pct=pct,
                        discount_amount=round(lp * pct / 100, 2), accessories_amount=accessories, trade_in_value=trade,
                        final_price=round(lp * (1 - pct / 100) + accessories, 2),
                        finance_product=self.r.choices(["pcp", "cash", "hp", "lease"], [55, 25, 10, 10])[0],
                        created_at=when - dt.timedelta(days=self.r.randint(1, 5)), signed_at=when,
                        delivered_at=None, notes=None)
        deal["_trade"] = trade_car
        v["status"] = "sold"
        if v["arrived_at"]:
            v["pdi_done"] = True
            dday = day + dt.timedelta(days=self.r.randint(3, 9))
        else:
            dday = dt.date.fromisoformat(str(self.eta(v))) + dt.timedelta(days=self.r.randint(2, 6))
        if dday < self.end.date():
            self.agenda[dday].append(lambda: self.deliver(deal, v, dday))

    def eta(self, v):
        o = next(o for o in self.t[("bmw_portal", "car_orders")] if o["order_no"] == v["bmw_order_no"])
        return o["eta"]

    def deliver(self, deal, v, day):
        if day.weekday() == 6:
            day += dt.timedelta(days=1)
        when = self.at(day, 10, 17)
        deal.update(status="delivered", delivered_at=when)
        v["status"] = "delivered"
        if v["condition"] == "new" and not v["reg"]:
            v["reg"] = self.reg(day.year, day.month)
        self.invoice("vehicle", deal["deal_id"], deal["customer_id"], deal["final_price"] / (1 + rules.VAT), when,
                     paid_after_days=self.r.choice([0, 1, 2, 3, 5]),
                     method="finance_company" if deal["finance_product"] != "cash" else "bank_transfer")
        self.ledger(day, "cost_of_sales", f"cost of {v['stock_no']}", v["cost_price"], 0, deal["deal_id"])
        self.ledger(day, "vehicle_stock", f"cost of {v['stock_no']}", 0, v["cost_price"], deal["deal_id"])
        cv = self.customer_vehicle(deal["customer_id"], v["model_code"], v["year"], delivered=day,
                                   vin=v["vin"], mileage=v["mileage"])
        cv["reg"] = v["reg"]
        if v["condition"] == "used":
            cv["warranty_until"] = day.replace(year=day.year + 1)
        if deal["_trade"]:
            self.used_vehicle(*deal["_trade"], when)
        self.mail(self.email(deal["salesperson"]), self.customer_email(deal["customer_id"]),
                  f"Your new {v['model']}", "Thank you for collecting your car today. Any questions, just reply.",
                  when + dt.timedelta(hours=1))

    def customer_email(self, cid):
        return next(c["email"] for c in self.customers if c["customer_id"] == cid)

    def stock_order(self, day):
        """Thursday: Daniel tops up new-car stock. More than 3 cars a week needs Victor."""
        avail = [v for v in self.stock.values() if v["condition"] == "new" and v["status"] in ("in_stock", "on_order")]
        gap = STOCK_TARGET - len(avail)
        n = max(0, min(gap, 5 if self.r.random() < 0.2 else 3))
        when = self.at(day, 9, 11)
        for i in range(n):
            code = self.r.choices([m[0] for m in catalog.MODELS], catalog.MODEL_WEIGHTS)[0]
            req = self.nid("OR-")
            if i >= rules.MAX_STOCK_ORDERS_PER_WEEK:
                self.approval("stock_order", req, "daniel-reed", rules.GM, when, reason="plate-change demand")
            v = self.car_order(code, "stock", "daniel-reed", when + dt.timedelta(hours=2), req)
            self.add("order_requests", request_id=req, model_code=code, colour=v["colour"], customer_id=None,
                     reason="stock", requested_by="daniel-reed", status="ordered", bmw_order_no=v["bmw_order_no"],
                     stock_no=v["stock_no"], created_at=when)

    # ------------------------------------------------------------------ aftersales
    def parts_for(self, cv, service_type):
        fits = {fuel_group(cv["fuel"]), chassis(cv["_code"]), "ALL"}
        ok = [p for p in self.inv.values() if fits & set(p["fits"].split())]

        def pick(*keys):
            return [(p, q) for k, q in keys for p in ok if p["_key"] == k]
        if service_type == "service":
            if cv["fuel"] == "electric":
                return pick(("cabin-filter", 1), ("cabin-filter-ix", 1), ("brake-fluid", 1), ("washer-fluid", 1))
            six = chassis(cv["_code"]) in ("G80", "G82", "G07", "G05")
            filt = "oilfilter-b58" if six else "oilfilter-b47" if cv["fuel"] == "diesel" else "oilfilter-b48"
            items = pick(("oil-ll04", 6 if six else 5), (filt, 1), ("washer-fluid", 1))
            if self.r.random() < 0.5:
                items += pick(("airfilter-4", 1), ("cabin-filter", 1))
            return items
        if service_type == "repair":
            choice = self.r.choice(["front-brakes", "rear-brakes", "battery", "coil", "pdc", "water-pump"])
            return {"front-brakes": pick(("pads-front-s", 1), ("pads-front-m", 1), ("pads-front-l", 1), ("pad-sensor", 1)),
                    "rear-brakes": pick(("pads-rear-m", 1), ("discs-rear-m", 2), ("pad-sensor", 1)),
                    "battery": pick(("battery-12v-70", 1)),
                    "coil": pick(("ignition-coil", 1)),
                    "pdc": pick(("pdc-sensor", 1)),
                    "water-pump": pick(("water-pump-b48", 1), ("thermostat-b47", 1))}[choice]
        if service_type == "tyres":
            return pick(("tyre-225-45r18", 2), ("tyre-245-45r19", 2), ("tyre-255-50r20", 2), ("tyre-225-55r17", 2))[:1] \
                + pick(("tpms", 1))[: self.r.random() < 0.3]
        if service_type == "diagnosis" and cv["fuel"] in ("electric", "hybrid") and self.r.random() < 0.3:
            return pick(("charge-flap", 1), ("onboard-charger-fuse", 1))[:1]
        return []

    def service_day(self, day):
        lam = 3.0 if day.weekday() == 5 else 6.0
        for _ in range(self.poisson(lam)):
            cv = self.r.choice(self.cvs)
            stype = self.r.choices(["service", "mot", "repair", "diagnosis", "tyres"], [48, 14, 17, 12, 9])[0]
            self.job(day, cv, stype)

    def job(self, day, cv, stype, recall=None):
        advisor = self.r.choice(["james-okafor", "nina-kovac"])
        booked = self.at(day - dt.timedelta(days=self.r.randint(2, 16)), 8, 17)
        bid = self.nid("BK-")
        notes = recall or {"service": "annual service", "mot": "MOT test", "repair": self.r.choice(
            ["brake noise", "warning light on dash", "parking sensor fault", "rough idle", "battery keeps going flat"]),
            "diagnosis": self.r.choice(["intermittent charging fault", "iDrive freezes", "engine management light",
                                        "rattle from rear"]), "tyres": "two tyres worn"}.get(stype, stype)
        b = self.add("bookings", booking_id=bid, customer_id=cv["customer_id"], vin=cv["vin"], date=day,
                     service_type=stype if not recall else "recall", notes=notes,
                     created_by=self.r.choice(["maria-santos", "maria-santos", advisor]), status="booked",
                     created_at=booked)
        if self.r.random() < 0.04:
            b["status"] = self.r.choice(["cancelled", "no_show"])
            return
        b["status"] = "arrived"
        if self.r.random() < 0.25:
            self.mail(self.email(advisor), self.customer_email(cv["customer_id"]), f"Booking {bid} confirmed",
                      f"Your {cv['model']} ({cv['reg']}) is booked in on {day:%A %d %B}. Drop-off from 8:00.", booked)
        opened = dt.datetime.combine(day, dt.time(8, self.r.randint(0, 59)))
        ev = cv["fuel"] in ("electric", "hybrid")
        tech = "aisha-rahman" if (ev and stype in ("diagnosis", "repair")) or (ev and self.r.random() < 0.5) \
            else self.r.choice(["lucas-meyer", "lucas-meyer", "aisha-rahman"])
        under_warranty = cv["warranty_until"] >= day
        warranty = under_warranty and stype in ("repair", "diagnosis") and self.r.random() < 0.45 or bool(recall)
        jno = self.nid("J-")
        job = self.add("job_cards", job_no=jno, booking_id=bid, vin=cv["vin"], customer_id=cv["customer_id"],
                       advisor=advisor, technician=tech, status="invoiced", complaint=notes, findings=None,
                       warranty=warranty, opened_at=opened, closed_at=None)
        rate = rules.WARRANTY_LABOUR_RATE if warranty else rules.LABOUR_RATE
        hours = {"service": 1.5, "mot": 0.8, "repair": round(self.r.uniform(1, 3.5), 1),
                 "diagnosis": round(self.r.uniform(0.8, 2), 1), "tyres": 0.8, "recall": 1.0}[stype if not recall else "recall"]
        self.add("job_lines", line_id=self.nid("JL-", 6), job_no=jno, kind="labour",
                 description=notes if stype != "service" else f"{cv['model']} annual service", part_no=None,
                 qty=hours, unit_price=rate, authorised=True, added_by=advisor, added_at=opened)
        self.add("time_entries", entry_id=self.nid("T-", 6), job_no=jno, technician=tech,
                 hours=round(hours * self.r.uniform(0.8, 1.2), 1), note="", occurred_at=opened + dt.timedelta(hours=2))
        vor = False
        waiting = False
        for p, qty in self.parts_for(cv, stype) if not recall else []:
            rid = self.nid("PR-")
            req_at = opened + dt.timedelta(minutes=self.r.randint(20, 120))
            if p["qty_on_hand"] >= qty:
                p["qty_on_hand"] -= qty
                issued = req_at + dt.timedelta(minutes=self.r.randint(3, 25))
                self.add("parts_requests", request_id=rid, job_no=jno, part_no=p["part_no"], qty=qty, requested_by=tech,
                         status="issued", bmw_order_no=None, issued_by="mark-doyle", requested_at=req_at, issued_at=issued)
                self.move(p, -qty, "issue", jno, "mark-doyle", issued)
            else:
                vor = True
                po = self.parts_order("vor", [(p, qty)], req_at + dt.timedelta(minutes=15), jno)
                arrive = parts_eta(req_at + dt.timedelta(minutes=15), "vor")
                if arrive + dt.timedelta(minutes=30) > self.end:   # delivered by BMW but not booked in yet
                    waiting = True
                    self.add("parts_requests", request_id=rid, job_no=jno, part_no=p["part_no"], qty=qty,
                             requested_by=tech, status="ordered", bmw_order_no=po, issued_by=None,
                             requested_at=req_at, issued_at=None)
                    continue
                self.add("parts_requests", request_id=rid, job_no=jno, part_no=p["part_no"], qty=qty, requested_by=tech,
                         status="issued", bmw_order_no=po, issued_by="mark-doyle", requested_at=req_at,
                         issued_at=arrive + dt.timedelta(minutes=30))
                self.move(p, qty, "receipt", po, "mark-doyle", arrive)
                self.move(p, -qty, "issue", jno, "mark-doyle", arrive + dt.timedelta(minutes=30))
            self.add("job_lines", line_id=self.nid("JL-", 6), job_no=jno, kind="part", description=p["description"],
                     part_no=p["part_no"], qty=qty, unit_price=p["cost"] if warranty else p["price"], authorised=True,
                     added_by="mark-doyle", added_at=req_at)
        if not warranty and self.r.random() < 0.22:
            extra = self.r.choice([("Replace worn rear wiper and front wipers", 0.3), ("Brake fluid change", 0.7),
                                   ("Wheel alignment", 1.0), ("Air-con service", 0.8), ("Clean and adjust rear brakes", 1.0)])
            agreed = self.r.random() < 0.7
            if agreed:
                self.add("job_lines", line_id=self.nid("JL-", 6), job_no=jno, kind="labour", description=extra[0],
                         part_no=None, qty=extra[1], unit_price=rate, authorised=True, added_by=tech,
                         added_at=opened + dt.timedelta(hours=1))
            self.add("activities", activity_id=self.nid("A-", 6), customer_id=cv["customer_id"], staff_id=advisor,
                     kind="call", note=f"{jno}: extra work '{extra[0]}' {'authorised' if agreed else 'declined'}",
                     occurred_at=opened + dt.timedelta(hours=1, minutes=20))
        closed = (parts_eta(opened, "vor") + dt.timedelta(hours=3)) if vor else \
            opened + dt.timedelta(minutes=self.r.randint(180, 480))
        if waiting or closed > self.end:
            job.update(status="waiting_parts" if waiting else "in_progress",
                       findings="Waiting for VOR parts from BMW." if waiting else None)
            return
        job["closed_at"] = closed
        job["findings"] = self.r.choice(["Work completed as requested.", "Completed, road tested OK.",
                                         "Completed; advised customer of tyre wear.", "No further faults found."])
        cv["last_service"] = day if stype == "service" else cv["last_service"]
        if stype == "service":
            cv["next_service_due"] = day + dt.timedelta(days=365)
        cv["mileage"] = (cv["mileage"] or 0) + self.r.randint(0, 800)
        lines = [l for l in self.t[("internal", "job_lines")][-12:] if l["job_no"] == jno]
        net = sum(float(l["qty"]) * float(l["unit_price"]) for l in lines)
        if warranty:
            claim_amount = round(net, 2)
            aid = self.approval("warranty", jno, advisor, rules.AFTERSALES_MANAGER, closed, amount=claim_amount,
                                reason=notes)
            self.warranty_claim(cv, jno, notes, hours, net - hours * rate, closed + dt.timedelta(hours=1), aid,
                                advisor if advisor == "nina-kovac" else "elena-popescu")
            if recall:
                for rv in self.t[("bmw_portal", "recall_vins")]:
                    if rv["vin"] == cv["vin"] and rv["recall_code"] == recall_code_of(recall):
                        rv["completed_at"] = closed
        else:
            late = self.r.random() < 0.08   # account customers pay on terms
            self.invoice("service", jno, cv["customer_id"], net, closed,
                         paid_after_days=self.r.randint(3, 30) if late else 0,
                         method="bank_transfer" if late else "card")
            if self.r.random() < 0.02:
                amt = self.r.choice([80, 150, 250, 400, 650])
                appr = rules.goodwill_approver(amt)
                self.approval("goodwill", jno, advisor, appr, closed - dt.timedelta(hours=1), amount=amt,
                              reason="repeat visit for the same fault")

    def warranty_claim(self, cv, jno, desc, hours, parts_amount, when, aid, who):
        no = self.nid("BMW-WC-", 6)
        amount = round(hours * rules.WARRANTY_LABOUR_RATE + max(parts_amount, 0), 2)
        c = self.add("warranty_claims", "bmw_portal", claim_no=no, dealer_no=DEALER_NO, vin=cv["vin"], job_ref=jno,
                     description=f"{desc} [dealer approval {aid}]", labour_hours=hours, parts_amount=max(parts_amount, 0),
                     amount=amount, submitted_by=self.portal_user(who), submitted_at=when, status="submitted",
                     decided_at=None, decision_note=None)
        if when + dt.timedelta(days=3) <= self.end:
            ok = amount <= 2500 and int(hashlib.md5(no.encode()).hexdigest(), 16) % 10 != 0
            c.update(status="approved" if ok else "rejected", decided_at=when + dt.timedelta(days=3),
                     decision_note="approved as claimed" if ok else "insufficient diagnostic evidence; resubmit with fault codes")
            if ok:
                d = (when + dt.timedelta(days=3)).date()
                self.ledger(d, "warranty_receivable", f"BMW warranty {no}", amount, 0, no)
                self.ledger(d, "sales_service", f"BMW warranty {no}", 0, amount, no)
                if when + dt.timedelta(days=17) <= self.end:
                    c["status"] = "paid"
                    pd = d + dt.timedelta(days=14)
                    self.ledger(pd, "bank", f"BMW warranty payment {no}", amount, 0, no)
                    self.ledger(pd, "warranty_receivable", f"BMW warranty payment {no}", 0, amount, no)

    def recall_campaigns(self):
        for code, title, models, *_ in catalog.RECALLS:
            affected = [cv for cv in self.cvs if chassis(cv["_code"]) in models.split()]
            for cv in self.r.sample(affected, min(len(affected), max(6, len(affected) // 3))):
                self.add("recall_vins", "bmw_portal", recall_code=code, vin=cv["vin"], completed_at=None)
                cv["_recall"] = code

    def recall_jobs(self, day):
        if day.weekday() >= 5:
            return
        pending = [rv for rv in self.t[("bmw_portal", "recall_vins")] if rv["completed_at"] is None
                   and RECALL_ISSUED[rv["recall_code"]] < day]
        if pending and self.r.random() < 0.5:
            rv = self.r.choice(pending)
            cv = next(c for c in self.cvs if c["vin"] == rv["vin"])
            rv["completed_at"] = "booked"
            self.job(day, cv, "repair", recall=f"recall {rv['recall_code']}: {RECALL_TITLE[rv['recall_code']]}")

    # ------------------------------------------------------------------ parts supply chain
    def move(self, p, qty, kind, ref, staff, when):
        self.add("parts_movements", movement_id=self.nid("M-", 6), part_no=p["part_no"], qty=qty, kind=kind, ref=ref,
                 staff_id=staff, occurred_at=when)

    def parts_order(self, kind, lines, when, job_ref=None):
        no = self.nid("BMW-PO-", 6)
        eta = parts_eta(when, kind)
        total = sum(float(p["cost"]) * q for p, q in lines)
        status = "delivered" if eta <= self.end else ("dispatched" if eta - dt.timedelta(hours=10) <= self.end else "confirmed")
        self.add("parts_orders", "bmw_portal", order_no=no, dealer_no=DEALER_NO, kind=kind, job_ref=job_ref,
                 ordered_by=self.portal_user("mark-doyle"), ordered_at=when, status=status, eta=eta, total=round(total, 2))
        for p, q in lines:
            self.add("parts_order_lines", "bmw_portal", order_no=no, part_no=p["part_no"], qty=q, unit_price=p["cost"])
        self.ledger(when.date(), "parts_stock", f"BMW parts order {no}", total, 0, no)
        self.ledger(when.date(), "bmw_payables", f"BMW parts order {no}", 0, total, no)
        return no

    def daily_parts_order(self, day):
        if day.weekday() == 6:
            return
        low = [(p, p["reorder_level"] * 2 - p["qty_on_hand"]) for p in self.inv.values()
               if p["reorder_level"] and p["qty_on_hand"] <= p["reorder_level"]]
        if not low:
            return
        when = dt.datetime.combine(day, dt.time(14, self.r.randint(30, 58)))
        no = self.parts_order("stock", low, when)
        eta = parts_eta(when, "stock")
        if eta + dt.timedelta(minutes=40) <= self.end:   # else: delivered, waiting for Mark to book it in
            for p, q in low:
                p["qty_on_hand"] += q
                self.move(p, q, "receipt", no, "mark-doyle", eta + dt.timedelta(minutes=40))

    def weekly(self, day):
        if day.weekday() == 4:   # Friday: Priya pays BMW parts invoices for the week
            week = [o for o in self.t[("bmw_portal", "parts_orders")]
                    if day - dt.timedelta(days=7) < o["ordered_at"].date() <= day]
            total = round(sum(float(o["total"]) for o in week), 2)
            if total:
                self.ledger(day, "bmw_payables", f"BMW parts statement w/e {day}", total, 0, f"PS-{day:%Y%m%d}")
                self.ledger(day, "bank", f"BMW parts statement w/e {day}", 0, total, f"PS-{day:%Y%m%d}")
            self.mail(self.email("priya-nair"), self.email("victor-hale"), f"Week ending {day:%d %b}: BMW parts paid",
                      f"Paid BMW parts statement {total:,.2f} GBP. Reconciled against Mark's orders.",
                      dt.datetime.combine(day, dt.time(16, 30)))

    # ------------------------------------------------------------------ run
    def run(self):
        self.reference()
        self.base()
        self.recall_campaigns()
        day = START
        while day < self.end.date():
            for fn in self.agenda.pop(day, []):
                fn()
            if day.weekday() != 6:
                if day.weekday() == 3:
                    self.stock_order(day)
                self.leads_for(day)
                if day.weekday() < 6 and day not in BANK_HOLIDAYS:
                    self.service_day(day)
                    self.recall_jobs(day)
                self.daily_parts_order(day)
                self.weekly(day)
            day += dt.timedelta(days=1)
        for rv in self.t[("bmw_portal", "recall_vins")]:
            if rv["completed_at"] == "booked":
                rv["completed_at"] = None
        self.this_morning()

    # ------------------------------------------------------------------ open work for today
    def this_morning(self):
        from apps import scenario_today
        scenario_today.build(self)


RECALL_ISSUED = {c: dt.date.fromisoformat(d) for c, _, _, _, _, d in catalog.RECALLS}
RECALL_TITLE = {c: t for c, t, *_ in catalog.RECALLS}
BANK_HOLIDAYS = {dt.date(2026, 1, 1), dt.date(2026, 4, 3), dt.date(2026, 4, 6), dt.date(2026, 5, 4),
                 dt.date(2026, 5, 25), dt.date(2026, 8, 31)}


def recall_code_of(text):
    return text.split()[1].rstrip(":")


# ---------------------------------------------------------------------- writing
def _cell(v):
    if v is None:
        return r"\N"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(str(x).replace(",", " ") for x in v) + "]"
    return str(v)


def write(seeder: Seeder, out_dir: Path = DATA, parquet: bool = True) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    tmp = Path(tempfile.mkdtemp())
    try:
        for db, ddl in (("internal", schema.INTERNAL), ("bmw_portal", schema.PORTAL)):
            path = out_dir / DB_FILES[db]
            path.unlink(missing_ok=True)
            con = duckdb.connect(str(path))
            con.execute(ddl)
            tables = [r[0] for r in con.execute("SELECT table_name FROM information_schema.tables "
                                                "WHERE table_schema='main' ORDER BY table_name").fetchall()]
            for table in tables:
                cols = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
                rows = seeder.t.get((db, table), [])
                if rows:
                    f = tmp / f"{db}.{table}.csv"
                    with f.open("w", newline="", encoding="utf-8") as fh:
                        w = csv.writer(fh)
                        for r in rows:
                            w.writerow([_cell(r.get(c)) for c in cols])
                    con.execute(f"COPY {table} ({', '.join(cols)}) FROM '{f}' "
                                "(FORMAT CSV, HEADER false, NULLSTR '\\N', QUOTE '\"')")
                counts[f"{db}.{table}"] = len(rows)
            if parquet:
                pq = out_dir / "parquet" / db
                shutil.rmtree(pq, ignore_errors=True)
                pq.mkdir(parents=True)
                for table in tables:
                    con.execute(f"COPY {table} TO '{pq / (table + '.parquet')}' (FORMAT PARQUET)")
            con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return counts


def build(out_dir: Path = DATA, parquet: bool = True, quiet: bool = True) -> dict:
    s = Seeder()
    s.run()
    counts = write(s, out_dir, parquet)
    if not quiet:
        for k, v in counts.items():
            print(f"{k:42s} {v:7d}")
    return counts


if __name__ == "__main__":
    build(quiet=False)
