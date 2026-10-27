"""BMW Partner Portal (simulated, *external*): BMW's side of the dealer relationship.

It has its own database (data/bmw_portal.duckdb) and knows nothing about VXC's internal systems.
Dealer staff log in with their own portal accounts (personal, never shared); the tools act as the
calling persona's portal user. Order progress is driven by the clock: a car order moves
confirmed -> in_production -> shipped -> delivered as weeks pass, parts arrive next morning.
"""
import datetime as dt
import hashlib

from systems.common import Param, ToolError, tool

DEALER_NO = "GB-40712"
VIN_CHARS = "ABCDEFGHJKLMNPRSTUVWXYZ0123456789"


def vin_for(order_no: str) -> str:
    h = hashlib.sha256(order_no.encode()).digest()
    return "WBA" + "".join(VIN_CHARS[b % len(VIN_CHARS)] for b in h[:14])


def car_order_timeline(ordered_at: dt.datetime, lead_weeks: int) -> dict:
    eta = (ordered_at + dt.timedelta(weeks=lead_weeks)).date()
    prod = ordered_at + dt.timedelta(weeks=max(1, lead_weeks - 3))
    return {"eta": eta, "production_start": prod, "ship_date": eta - dt.timedelta(days=10),
            "production_week": prod.strftime("%G-W%V")}


def car_status(ordered_at, lead_weeks, now) -> str:
    t = car_order_timeline(ordered_at, lead_weeks)
    if now.date() >= t["eta"]:
        return "delivered"
    if now.date() >= t["ship_date"]:
        return "shipped"
    if now >= t["production_start"]:
        return "in_production"
    return "confirmed"


def parts_eta(ordered_at: dt.datetime, kind: str) -> dt.datetime:
    """VOR: 16:00 the same day if ordered before 10:00, else next morning 07:30. Stock: next morning if before 15:00."""
    day = ordered_at.date()
    if kind == "vor":
        if ordered_at.hour < 10:
            return dt.datetime.combine(day, dt.time(16, 0))
        day += dt.timedelta(days=1)
    else:
        day += dt.timedelta(days=1 if ordered_at.hour < 15 else 2)
    while day.weekday() == 6:
        day += dt.timedelta(days=1)
    return dt.datetime.combine(day, dt.time(7, 30))


def _refresh(ctx):
    """Advance order and claim states to match the clock (BMW's back office, simulated)."""
    for o in ctx.rows("SELECT o.order_no, o.ordered_at, o.status, m.lead_time_weeks FROM car_orders o "
                      "JOIN models m USING (model_code) WHERE o.status NOT IN ('delivered','cancelled')"):
        s = car_status(dt.datetime.fromisoformat(o["ordered_at"]), o["lead_time_weeks"], ctx.now)
        if s != o["status"]:
            vin = vin_for(o["order_no"]) if s != "confirmed" else None
            ctx.db.execute("UPDATE car_orders SET status=?, vin=coalesce(vin, ?) WHERE order_no=?",
                           [s, vin, o["order_no"]])
    ctx.db.execute("UPDATE parts_orders SET status='delivered' WHERE status<>'delivered' AND eta <= ?", [ctx.now])
    ctx.db.execute("UPDATE parts_orders SET status='dispatched' WHERE status='confirmed' "
                   "AND eta - INTERVAL 10 HOUR <= ?", [ctx.now])
    for c in ctx.rows("SELECT claim_no, amount, submitted_at FROM warranty_claims WHERE status='submitted' "
                      "AND submitted_at <= ?", [ctx.now - dt.timedelta(days=3)]):
        ok = float(c["amount"]) <= 2500 and int(hashlib.md5(c["claim_no"].encode()).hexdigest(), 16) % 10 != 0
        ctx.db.execute("UPDATE warranty_claims SET status=?, decided_at=?, decision_note=? WHERE claim_no=?",
                       ["approved" if ok else "rejected",
                        dt.datetime.fromisoformat(c["submitted_at"]) + dt.timedelta(days=3),
                        "approved as claimed" if ok else "insufficient diagnostic evidence; resubmit with fault codes",
                        c["claim_no"]])


def _user(ctx):
    u = ctx.row("SELECT * FROM portal_users WHERE email=? AND active", [ctx.persona.get("email")])
    if not u:
        raise ToolError("BMW Partner Portal: no active portal account for this user")
    ctx.db.execute("UPDATE portal_users SET last_login=? WHERE user_id=?", [ctx.now, u["user_id"]])
    _refresh(ctx)
    return u


def _need(u, *roles):
    if u["portal_role"] not in roles + ("dealer_admin",):
        raise ToolError(f"BMW Partner Portal: your role '{u['portal_role']}' cannot do this (needs {' or '.join(roles)})")


@tool("bmw_portal", "BMW model catalogue: model codes, prices, dealer cost and factory lead time.",
      series=Param("string", "Filter, e.g. 'X3', 'i4', '3 Series'", default=None))
def bmw_list_models(ctx, series=None):
    _user(ctx)
    if series:
        return ctx.rows("SELECT * FROM models WHERE lower(series) LIKE ? OR lower(name) LIKE ? ORDER BY base_price",
                        [f"%{series.lower()}%"] * 2)
    return ctx.rows("SELECT * FROM models ORDER BY base_price")


@tool("bmw_portal", "Place a new-car order with the BMW factory.", writes=True,
      model_code=Param("string", "Model code"), colour=Param("string", "Paint colour"),
      order_type=Param("string", "customer or stock", enum=["customer", "stock"]),
      dealer_ref=Param("string", "Your internal reference (order request id)", default=None),
      options=Param("array", "Option names", default=None, items={"type": "string"}))
def bmw_place_car_order(ctx, model_code, colour, order_type, dealer_ref=None, options=None):
    u = _user(ctx)
    _need(u, "sales_ordering")
    m = ctx.row("SELECT * FROM models WHERE model_code=?", [model_code])
    if not m:
        raise ToolError(f"unknown model code {model_code}")
    no = ctx.next_id("car_orders", "order_no", "BMW-CO-", 6)
    t = car_order_timeline(ctx.now, m["lead_time_weeks"])
    ctx.db.execute("INSERT INTO car_orders VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   [no, DEALER_NO, model_code, colour, options or [], order_type, dealer_ref, u["user_id"], ctx.now,
                    "confirmed", t["production_week"], t["eta"], None, m["dealer_cost"]])
    return {"order_no": no, "model": m["name"], "status": "confirmed", "production_week": t["production_week"],
            "eta": t["eta"], "list_price": m["base_price"], "dealer_cost": m["dealer_cost"]}


@tool("bmw_portal", "Track car orders (status, production week, ETA, VIN once built).",
      status=Param("string", "Filter by status", default=None,
                   enum=["confirmed", "in_production", "shipped", "delivered", "cancelled"]),
      order_no=Param("string", "One order number", default=None))
def bmw_list_car_orders(ctx, status=None, order_no=None):
    _user(ctx)
    sql = ("SELECT o.order_no, m.name AS model, o.colour, o.order_type, o.customer_ref AS dealer_ref, o.status, "
           "o.production_week, o.eta, o.vin, o.ordered_at FROM car_orders o JOIN models m USING (model_code) WHERE TRUE")
    args = []
    if order_no:
        sql += " AND o.order_no=?"; args.append(order_no)
    if status:
        sql += " AND o.status=?"; args.append(status)
    elif not order_no:
        sql += " AND o.status NOT IN ('delivered','cancelled')"
    return ctx.rows(sql + " ORDER BY o.eta DESC LIMIT 30", args)


@tool("bmw_portal", "Search BMW's parts catalogue with central warehouse availability.",
      query=Param("string", "Part number or description words"))
def bmw_search_parts(ctx, query):
    _user(ctx)
    sql, args = "SELECT * FROM parts_catalog WHERE TRUE", []
    for w in query.lower().split():
        sql += " AND (lower(description) LIKE ? OR lower(fits) LIKE ? OR replace(part_no,' ','') LIKE ?)"
        args += [f"%{w}%"] * 3
    return ctx.rows(sql + " LIMIT 25", args)


@tool("bmw_portal", "Order parts from BMW. kind=vor (vehicle off road, urgent) or stock (daily 15:00 order).",
      writes=True,
      lines=Param("array", "Parts to order", items={"type": "object", "properties": {
          "part_no": {"type": "string"}, "qty": {"type": "integer"}}, "required": ["part_no", "qty"]}),
      kind=Param("string", "vor or stock", enum=["vor", "stock"]),
      job_ref=Param("string", "Job card number for VOR orders", default=None))
def bmw_place_parts_order(ctx, lines, kind, job_ref=None):
    u = _user(ctx)
    _need(u, "parts_ordering", "aftersales")
    if kind == "vor" and not job_ref:
        raise ToolError("a VOR order needs the job card reference")
    if not lines:
        raise ToolError("no lines")
    no = ctx.next_id("parts_orders", "order_no", "BMW-PO-", 6)
    total = 0.0
    for ln in lines:
        p = ctx.row("SELECT * FROM parts_catalog WHERE part_no=?", [ln["part_no"]])
        if not p:
            raise ToolError(f"unknown part {ln['part_no']}")
        ctx.db.execute("INSERT INTO parts_order_lines VALUES (?,?,?,?)", [no, ln["part_no"], int(ln["qty"]), p["dealer_price"]])
        total += float(p["dealer_price"]) * int(ln["qty"])
    eta = parts_eta(ctx.now, kind)
    ctx.db.execute("INSERT INTO parts_orders VALUES (?,?,?,?,?,?,?,?,?)",
                   [no, DEALER_NO, kind, job_ref, u["user_id"], ctx.now, "confirmed", eta, round(total, 2)])
    return {"order_no": no, "status": "confirmed", "eta": eta, "total": round(total, 2)}


@tool("bmw_portal", "Track parts orders and their lines.",
      status=Param("string", "Filter", default=None, enum=["confirmed", "dispatched", "delivered"]),
      order_no=Param("string", "One order", default=None))
def bmw_list_parts_orders(ctx, status=None, order_no=None):
    _user(ctx)
    sql, args = "SELECT * FROM parts_orders WHERE TRUE", []
    if order_no:
        sql += " AND order_no=?"; args.append(order_no)
    if status:
        sql += " AND status=?"; args.append(status)
    orders = ctx.rows(sql + " ORDER BY ordered_at DESC LIMIT 20", args)
    for o in orders:
        o["lines"] = ctx.rows("SELECT l.part_no, c.description, l.qty, l.unit_price FROM parts_order_lines l "
                              "JOIN parts_catalog c USING (part_no) WHERE order_no=?", [o["order_no"]])
    return orders


@tool("bmw_portal", "Open recalls and technical campaigns for a VIN.", vin=Param("string", "VIN"))
def bmw_check_recalls(ctx, vin):
    _user(ctx)
    return ctx.rows("SELECT r.recall_code, r.title, r.remedy, r.labour_hours, v.completed_at FROM recall_vins v "
                    "JOIN recalls r USING (recall_code) WHERE v.vin=? ORDER BY r.issued_at", [vin])


@tool("bmw_portal", "Technical service bulletins (known faults and fixes), optionally for a model.",
      model=Param("string", "Model text, e.g. 'iX', 'G20'", default=None))
def bmw_list_bulletins(ctx, model=None):
    _user(ctx)
    if model:
        return ctx.rows("SELECT * FROM bulletins WHERE lower(models) LIKE ? OR lower(title) LIKE ? "
                        "ORDER BY issued_at DESC", [f"%{model.lower()}%"] * 2)
    return ctx.rows("SELECT * FROM bulletins ORDER BY issued_at DESC")


@tool("bmw_portal", "Submit a warranty claim to BMW (needs the dealer's internal approval reference).",
      writes=True, vin=Param("string", "VIN"), job_ref=Param("string", "Dealer job card number"),
      description=Param("string", "Fault, diagnosis (fault codes) and repair"),
      labour_hours=Param("number", "Labour hours"), parts_amount=Param("number", "Parts at dealer cost GBP"),
      approval_ref=Param("string", "Internal approval id from the aftersales manager"))
def bmw_submit_warranty_claim(ctx, vin, job_ref, description, labour_hours, parts_amount, approval_ref):
    u = _user(ctx)
    _need(u, "aftersales", "technician")
    if ctx.scalar("SELECT count(*) FROM warranty_claims WHERE job_ref=? AND status<>'rejected'", [job_ref]):
        raise ToolError(f"a claim for {job_ref} already exists")
    if not approval_ref:
        raise ToolError("approval_ref is required")
    no = ctx.next_id("warranty_claims", "claim_no", "BMW-WC-", 6)
    amount = round(float(labour_hours) * 120 + float(parts_amount), 2)
    ctx.db.execute("INSERT INTO warranty_claims VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   [no, DEALER_NO, vin, job_ref, f"{description} [dealer approval {approval_ref}]", labour_hours,
                    parts_amount, amount, u["user_id"], ctx.now, "submitted", None, None])
    return {"claim_no": no, "amount": amount, "status": "submitted", "decision_expected_in_days": 3}


@tool("bmw_portal", "Warranty claims and their decisions.",
      status=Param("string", "Filter", default=None, enum=["submitted", "approved", "rejected", "paid"]))
def bmw_list_warranty_claims(ctx, status=None):
    _user(ctx)
    if status:
        return ctx.rows("SELECT * FROM warranty_claims WHERE status=? ORDER BY submitted_at DESC LIMIT 30", [status])
    return ctx.rows("SELECT * FROM warranty_claims ORDER BY submitted_at DESC LIMIT 30")
