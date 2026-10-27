"""The open work waiting at VXC Motors on the seed morning (Tuesday 27 Oct 2026, 07:45).

The history in seed.py closes almost everything it starts. This module leaves a realistic set of
loose ends in every role's queue, so a multi-agent run started "this morning" has real work:

  Maria    overnight web leads to route, a customer moving a booking
  Daniel   a 5.5% discount approval from Sofia, Thursday stock planning
  Victor   a 4th stock order this week (needs him), manager notes
  Tom      a customer pushing for 10% off an M4 (his limit is 3%, Daniel's 8%)
  Sofia    a sold car arrived from BMW, needs PDI then handover
  Elena    a warranty approval and a goodwill request
  James    a customer chasing a car waiting for parts
  Nina     today's recall booking, check recalls in the portal
  Lucas    a diagnosis job in progress, a brake-squeal car matching a BMW bulletin
  Aisha    an iX with a high-voltage warning, a PDI
  Mark     a VOR delivery and yesterday's stock order to book in, a part to issue
  Priya    unpaid invoices, the October KPI summary for Victor
"""
import datetime as dt

from systems import catalog, rules
from systems.bmw_portal import DEALER_NO, car_order_timeline, vin_for

PORTAL_MAIL = "noreply@partner-portal.bmw.example"


def build(s):
    end = s.end
    today = end.date()
    mon = today - dt.timedelta(days=today.weekday())
    E = s.email

    def t(day, h, m=0):
        return dt.datetime.combine(day, dt.time(h, m))

    yesterday = today - dt.timedelta(days=1)

    # ---------------------------------------------------------------- sales
    # 1. overnight web leads, not yet assigned
    for h in (20, 22, 6):
        day = yesterday if h > 12 else today
        lead = s.lead(day, when=t(day, h, s.r.randint(0, 59)))
        lead.update(status="new", assigned_to=None, source="web")
    new_leads = [l for l in s.t[("internal", "leads")][-3:]]
    for l in new_leads:
        s.mail("webforms@vxcmotors.example", E("maria-santos"), f"New web enquiry {l['lead_id']}",
               f"Customer {l['customer_id']} is interested in: {l['interest']}. Budget about {l['budget']:,.0f} GBP. "
               "Please route to a sales consultant.", l["created_at"], read=False)

    # 2. Tom: customer wants 10% off an M4
    m4 = _stock_car(s, "G82-M4C", t(today - dt.timedelta(days=12), 10))
    c = s.new_customer(t(today - dt.timedelta(days=6), 11), "walk_in")
    lead = s.add("leads", lead_id=s.nid("L-"), customer_id=c["customer_id"], assigned_to="tom-becker", status="quoted",
                 interest="BMW M4 Competition Coupe", budget=80000, source="walk_in",
                 created_at=t(today - dt.timedelta(days=6), 11), updated_at=t(yesterday, 16), lost_reason=None)
    m4["status"] = "reserved"
    s.add("test_drives", test_drive_id=s.nid("TD-"), lead_id=lead["lead_id"], stock_no=m4["stock_no"],
          staff_id="tom-becker", scheduled_at=t(today - dt.timedelta(days=4), 14), status="done")
    deal = s.add("deals", deal_id=s.nid("D-"), lead_id=lead["lead_id"], customer_id=c["customer_id"],
                 stock_no=m4["stock_no"], salesperson="tom-becker", status="draft", list_price=m4["list_price"],
                 discount_pct=0, discount_amount=0, accessories_amount=0, trade_in_value=24500,
                 final_price=m4["list_price"], finance_product="pcp", created_at=t(yesterday, 15), signed_at=None,
                 delivered_at=None, notes="part-ex 2021 M340i")
    s.mail(c["email"], E("tom-becker"), "M4 - can you do better?",
           f"Hi Tom, thanks for the drive in the M4 ({m4['stock_no']}). Another BMW dealer has offered me 10% off list "
           "on the same spec. If you can match that I'll sign this week. Otherwise I'll go with them. "
           f"{c['first_name']}", t(today, 7, 2), read=False)

    # 3. Sofia: 5.5% on an X3 30e, waiting for Daniel
    x3 = _stock_car(s, "G45-X3-30E", t(today - dt.timedelta(days=20), 10))
    c2 = s.new_customer(t(today - dt.timedelta(days=9), 10), "referral")
    lead2 = s.add("leads", lead_id=s.nid("L-"), customer_id=c2["customer_id"], assigned_to="sofia-marin",
                  status="quoted", interest="BMW X3 30e xDrive M Sport", budget=56000, source="referral",
                  created_at=t(today - dt.timedelta(days=9), 10), updated_at=t(yesterday, 17), lost_reason=None)
    x3["status"] = "reserved"
    pct = 5.5
    lp = float(x3["list_price"])
    d2 = s.add("deals", deal_id=s.nid("D-"), lead_id=lead2["lead_id"], customer_id=c2["customer_id"],
               stock_no=x3["stock_no"], salesperson="sofia-marin", status="pending_approval", list_price=lp,
               discount_pct=pct, discount_amount=round(lp * pct / 100, 2), accessories_amount=0, trade_in_value=0,
               final_price=round(lp * (1 - pct / 100), 2), finance_product="pcp", created_at=t(yesterday, 16),
               signed_at=None, delivered_at=None, notes="referral from an existing customer; competitor quote")
    s.approval("discount", d2["deal_id"], "sofia-marin", "daniel-reed", t(yesterday, 17, 10),
               amount=d2["discount_amount"], pct=pct, status="pending",
               reason="Referred by a three-time customer; they have a written quote at 5% from another dealer.")

    # 4. stock orders: 3 placed Monday, a 4th waiting for Victor
    for i in range(3):
        code = ["U11-X1-20I", "G20-320I", "U11-IX1-E20"][i]
        req = s.nid("OR-")
        v = s.car_order(code, "stock", "daniel-reed", t(mon, 10, 10 * i + 5), req)
        s.add("order_requests", request_id=req, model_code=code, colour=v["colour"], customer_id=None, reason="stock",
              requested_by="daniel-reed", status="ordered", bmw_order_no=v["bmw_order_no"], stock_no=v["stock_no"],
              created_at=t(mon, 10, 10 * i))
    req = s.nid("OR-")
    s.add("order_requests", request_id=req, model_code="G26-I4E35", colour="Portimao Blue", customer_id=None,
          reason="stock", requested_by="daniel-reed", status="pending_approval", bmw_order_no=None, stock_no=None,
          created_at=t(yesterday, 17, 30))
    s.approval("stock_order", req, "daniel-reed", rules.GM, t(yesterday, 17, 31), status="pending",
               reason="4th stock car this week: i4 eDrive35 for the November EV event; two i4 enquiries open.")

    # 5. cars arrived at BMW's end (delivered), not yet booked into the DMS; one is sold to Sofia's customer
    arrived = []
    for code in ("G26-I4E35", "U11-X1-20I"):
        lead_w = catalog_lead(code)
        when = t(yesterday, 11) - dt.timedelta(weeks=lead_w)
        v = s.car_order(code, "stock", "daniel-reed", when, None)
        v["status"] = "in_transit"
        arrived.append(v)
    sold = arrived[0]
    c3 = s.new_customer(t(today - dt.timedelta(days=40), 12), "web")
    sold["status"] = "sold"
    s.add("deals", deal_id=s.nid("D-"), lead_id=None, customer_id=c3["customer_id"], stock_no=sold["stock_no"],
          salesperson="sofia-marin", status="signed", list_price=sold["list_price"], discount_pct=2.0,
          discount_amount=round(float(sold["list_price"]) * 0.02, 2), accessories_amount=895, trade_in_value=0,
          final_price=round(float(sold["list_price"]) * 0.98 + 895, 2), finance_product="pcp",
          created_at=t(today - dt.timedelta(days=38), 15), signed_at=t(today - dt.timedelta(days=37), 11),
          delivered_at=None, notes="customer wants handover on Saturday")
    s.mail(PORTAL_MAIL, E("mark-doyle"), "Vehicle deliveries: 2 cars delivered to GB-40712",
           "Delivered to dealer yesterday: " + ", ".join(f"{v['bmw_order_no']} ({v['model']}, VIN {vin_for(v['bmw_order_no'])})"
                                                        for v in arrived) + ". Please confirm receipt.",
           t(yesterday, 18), read=False)

    # ---------------------------------------------------------------- aftersales
    by_fuel = lambda f: [cv for cv in s.cvs if cv["fuel"] == f and cv["year"] <= 2025]
    # 6. today's and the coming days' bookings
    ix = next(cv for cv in s.cvs if cv["_code"] == "I20-IX-45")
    recall_vin = next(rv for rv in s.t[("bmw_portal", "recall_vins")]
                      if rv["completed_at"] is None and rv["recall_code"] == "RC-0061260210")
    recall_cv = next(cv for cv in s.cvs if cv["vin"] == recall_vin["vin"])
    squeal = next(cv for cv in s.cvs if cv["_code"].startswith("G20") and cv is not recall_cv)
    today_bookings = [
        (ix, "diagnosis", "High-voltage battery warning on dash, range dropped to 120 miles. Customer needs car by Friday."),
        (recall_cv, "recall", "recall RC-0061260210: HV battery cell module software update"),
        (squeal, "repair", "Brake squeal at low speed, front. Customer asks for a courtesy car."),
        (s.r.choice(by_fuel("petrol")), "service", "annual service"),
        (s.r.choice(by_fuel("diesel")), "service", "annual service + MOT"),
        (s.r.choice(by_fuel("hybrid")), "mot", "MOT test"),
    ]
    todays = []
    for cv, st, notes in today_bookings:
        todays.append(s.add("bookings", booking_id=s.nid("BK-"), customer_id=cv["customer_id"], vin=cv["vin"],
                            date=today, service_type=st, notes=notes, created_by=s.r.choice(["maria-santos", "nina-kovac"]),
                            status="booked", created_at=t(today - dt.timedelta(days=s.r.randint(3, 12)), 10)))
    for k in range(1, 9):
        day = today + dt.timedelta(days=k)
        if day.weekday() == 6:
            continue
        for _ in range(2 if day.weekday() == 5 else s.r.randint(3, 6)):
            cv = s.r.choice(s.cvs)
            s.add("bookings", booking_id=s.nid("BK-"), customer_id=cv["customer_id"], vin=cv["vin"], date=day,
                  service_type=s.r.choice(["service", "service", "mot", "repair", "tyres"]), notes="",
                  created_by="maria-santos", status="booked", created_at=t(today - dt.timedelta(days=s.r.randint(1, 14)), 11))
    moving = next(b for b in s.t[("internal", "bookings")] if b["date"] == today + dt.timedelta(days=2))
    mc = next(c for c in s.customers if c["customer_id"] == moving["customer_id"])
    s.mail(mc["email"], E("maria-santos"), f"Booking {moving['booking_id']}: can I move it?",
           f"Hello, my car is booked in on {moving['date']:%A}. Could we move it to Friday instead? Thanks, {mc['first_name']}",
           t(yesterday, 19, 40), read=False)

    # 7. yesterday's job waiting for a VOR part that BMW delivered at 07:30 today
    cv = s.r.choice([c for c in by_fuel("petrol") if c["_code"].split("-")[0] in ("G20", "G22", "G45", "G60")])
    j1 = _job(s, cv, t(yesterday, 8, 20), "james-okafor", "lucas-meyer", "repair",
              "Coolant warning, loss of coolant. Found: electric water pump leaking.", "waiting_parts")
    pump = next(p for p in s.inv.values() if p["_key"] == "water-pump-b48")
    po = s.parts_order("vor", [(pump, 1)], t(yesterday, 11, 5), j1)
    s.add("parts_requests", request_id=s.nid("PR-"), job_no=j1, part_no=pump["part_no"], qty=1,
          requested_by="lucas-meyer", status="ordered", bmw_order_no=po, issued_by=None,
          requested_at=t(yesterday, 10, 50), issued_at=None)
    s.mail(s.customer_email(cv["customer_id"]), E("james-okafor"), f"Any news on my car? ({cv['reg']})",
           "Hi James, you said yesterday the part would come this morning. Will the car be ready today? "
           "I need it for work tomorrow.", t(today, 7, 15), read=False)

    # 8. a diagnosis in progress with a part requested, waiting to be issued
    cv = s.r.choice(by_fuel("diesel"))
    j2 = _job(s, cv, t(yesterday, 9), "nina-kovac", "lucas-meyer", "diagnosis",
              "Engine management light, low power. Fault code for thermostat. Replacing thermostat.", "in_progress")
    thermo = next(p for p in s.inv.values() if p["_key"] == "thermostat-b47")
    thermo["qty_on_hand"] = max(thermo["qty_on_hand"], 1)
    thermo["qty_reserved"] = 1
    s.add("parts_requests", request_id=s.nid("PR-"), job_no=j2, part_no=thermo["part_no"], qty=1,
          requested_by="lucas-meyer", status="requested", bmw_order_no=None, issued_by=None,
          requested_at=t(yesterday, 16, 40), issued_at=None)

    # 9. a warranty job finished yesterday, the claim needs Elena before it goes to BMW
    cv = next(c for c in by_fuel("electric") if c["warranty_until"] >= today and c is not ix)
    j3 = _job(s, cv, t(yesterday, 8, 40), "nina-kovac", "aisha-rahman", "diagnosis",
              "AC charging stops at 80%. Found: matches SIB-61-11-26; CCU updated and charge profile reset.",
              "complete", warranty=True)
    s.approval("warranty", j3, "nina-kovac", rules.AFTERSALES_MANAGER, t(yesterday, 16, 30), amount=144.0,
               status="pending", reason="SIB-61-11-26 CCU update, 1.2h. Fault codes 0x80A1 stored.")
    # 10. goodwill request from James
    cv = s.r.choice(by_fuel("petrol"))
    j4 = _job(s, cv, t(yesterday, 9, 10), "james-okafor", "lucas-meyer", "repair",
              "Rattle from rear, second visit for the same fault. Heat shield clip replaced.", "complete")
    s.approval("goodwill", j4, "james-okafor", rules.AFTERSALES_MANAGER, t(yesterday, 17, 5), amount=350,
               status="pending", reason="Second visit for the same rattle; customer unhappy. Suggest waiving labour.")

    # 11. a BMW warranty rejection Elena should act on
    rejected = [c for c in s.t[("bmw_portal", "warranty_claims")] if c["status"] == "rejected"]
    if rejected:
        r = rejected[-1]
        s.mail(PORTAL_MAIL, E("elena-popescu"), f"Warranty claim {r['claim_no']} rejected",
               f"Claim {r['claim_no']} for job {r['job_ref']}: {r['decision_note']}", r["decided_at"],
               read=False)

    # ---------------------------------------------------------------- management & finance
    s.mail(E("victor-hale"), E("priya-nair"), "October numbers",
           "Priya, can I have the October KPI summary (cars, service revenue, unpaid invoices) by Thursday? "
           "Want to see how we track against last month before the BMW area manager visit.", t(yesterday, 18, 5), read=False)
    for to in ("daniel-reed", "elena-popescu"):
        s.mail(E("victor-hale"), E(to), "This week",
               "Morning. Three things: 1) BMW area manager visits Friday, I want clean approvals and no overdue "
               "jobs. 2) Plate-change prep for March starts now. 3) If anyone from another dealer group approaches "
               "the team about jobs or our customer data, I want to know.", t(today, 7, 30), read=False)


def catalog_lead(code):
    return next(m[6] for m in catalog.MODELS if m[0] == code)


def _stock_car(s, code, arrived):
    pool = [v for v in s.stock.values() if v["model_code"] == code and v["status"] == "in_stock"
            and v["condition"] == "new"]
    if pool:
        return pool[0]
    m = next(m for m in catalog.MODELS if m[0] == code)
    v = s.car_order(code, "stock", "daniel-reed", arrived - dt.timedelta(weeks=m[6]), None, arrived=arrived)
    s.arrive(v, arrived)
    return v


def _job(s, cv, opened, advisor, tech, stype, findings, status, warranty=False):
    bid = s.nid("BK-")
    s.add("bookings", booking_id=bid, customer_id=cv["customer_id"], vin=cv["vin"], date=opened.date(),
          service_type=stype, notes=findings.split(".")[0], created_by="maria-santos", status="arrived",
          created_at=opened - dt.timedelta(days=5))
    jno = s.nid("J-")
    s.add("job_cards", job_no=jno, booking_id=bid, vin=cv["vin"], customer_id=cv["customer_id"], advisor=advisor,
          technician=tech, status=status, complaint=findings.split(".")[0], findings=findings, warranty=warranty,
          opened_at=opened, closed_at=opened + dt.timedelta(hours=7) if status == "complete" else None)
    rate = rules.WARRANTY_LABOUR_RATE if warranty else rules.LABOUR_RATE
    s.add("job_lines", line_id=s.nid("JL-", 6), job_no=jno, kind="labour", description=findings.split(".")[0],
          part_no=None, qty=1.2, unit_price=rate, authorised=True, added_by=advisor, added_at=opened)
    s.add("time_entries", entry_id=s.nid("T-", 6), job_no=jno, technician=tech, hours=1.2, note="",
          occurred_at=opened + dt.timedelta(hours=2))
    return jno
