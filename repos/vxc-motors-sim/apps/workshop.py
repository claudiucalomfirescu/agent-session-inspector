"""Workshop Planner: service bookings, job cards, extra-work authorisation, technician time, PDI."""
import datetime as dt

from apps import rules
from apps.common import Param, ToolError, tool

SERVICE_TYPES = ["service", "mot", "repair", "diagnosis", "tyres", "recall", "pdi"]
JOB_STATUSES = ["open", "in_progress", "waiting_parts", "waiting_authorisation", "complete", "invoiced"]
DAILY_CAPACITY_HOURS = 2 * 7.5   # two technicians


@tool("workshop", "Service history and details for a customer's car, by VIN or registration.",
      vin_or_reg=Param("string", "VIN or registration plate, e.g. 'LB21 KXT'"))
def workshop_vehicle_history(ctx, vin_or_reg):
    v = ctx.row("SELECT * FROM customer_vehicles WHERE vin = ? OR replace(upper(reg),' ','') = replace(upper(?),' ','')",
                [vin_or_reg, vin_or_reg])
    if not v:
        raise ToolError(f"no customer vehicle {vin_or_reg}")
    v["jobs"] = ctx.rows("SELECT job_no, opened_at::DATE AS date, status, complaint, findings, warranty "
                         "FROM job_cards WHERE vin = ? ORDER BY opened_at DESC LIMIT 10", [v["vin"]])
    return v


@tool("workshop", "Bookings for a day (default today), with workshop hours already committed.",
      date=Param("string", "ISO date, e.g. 2026-10-28", default=None),
      status=Param("string", "Booking status", default=None, enum=["booked", "arrived", "cancelled", "no_show"]))
def workshop_list_bookings(ctx, date=None, status=None):
    day = dt.date.fromisoformat(date) if date else ctx.now.date()
    sql = ("SELECT b.booking_id, b.service_type, b.status, b.notes, b.customer_id, "
           "c.first_name || ' ' || c.last_name AS customer, v.reg, v.model FROM bookings b "
           "LEFT JOIN customers c USING (customer_id) LEFT JOIN customer_vehicles v ON v.vin = b.vin WHERE b.date = ?")
    args = [day]
    if status:
        sql += " AND b.status = ?"; args.append(status)
    rows = ctx.rows(sql + " ORDER BY b.booking_id", args)
    return {"date": day, "bookings": rows, "capacity_hours": DAILY_CAPACITY_HOURS,
            "booked_hours": _booked_hours(ctx, day)}


def _booked_hours(ctx, day):
    est = {"service": 1.5, "mot": 1.0, "repair": 3.0, "diagnosis": 1.5, "tyres": 1.0, "recall": 1.5, "pdi": 2.0}
    rows = ctx.rows("SELECT service_type, count(*) n FROM bookings WHERE date = ? AND status IN ('booked','arrived') "
                    "GROUP BY 1", [day])
    return sum(est.get(r["service_type"], 1.5) * r["n"] for r in rows)


@tool("workshop", "Book a car into the workshop. Refuses days that are full.", writes=True,
      customer_id=Param("string", "Customer id"), vin=Param("string", "Vehicle VIN (from crm_get_customer)"),
      date=Param("string", "ISO date"), service_type=Param("string", "Type of work", enum=SERVICE_TYPES),
      notes=Param("string", "Customer's description / requests", default=""))
def workshop_create_booking(ctx, customer_id, vin, date, service_type, notes=""):
    day = dt.date.fromisoformat(date)
    if day < ctx.now.date():
        raise ToolError("cannot book in the past")
    if day.weekday() == 6:
        raise ToolError("the workshop is closed on Sundays")
    if service_type != "pdi" and not ctx.scalar("SELECT count(*) FROM customer_vehicles WHERE vin=? AND customer_id=?",
                                                [vin, customer_id]):
        raise ToolError(f"vehicle {vin} is not registered to {customer_id}")
    if _booked_hours(ctx, day) + 1.5 > DAILY_CAPACITY_HOURS:
        raise ToolError(f"{day} is full; offer the customer another day")
    bid = ctx.next_id("bookings", "booking_id", "BK-")
    ctx.db.execute("INSERT INTO bookings VALUES (?,?,?,?,?,?,?,?,?)",
                   [bid, customer_id, vin, day, service_type, notes, ctx.actor, "booked", ctx.now])
    return {"booking_id": bid, "date": day}


@tool("workshop", "Customer has dropped the car off: open a job card from the booking.", writes=True,
      booking_id=Param("string", "Booking id"), complaint=Param("string", "Work requested / customer's complaint"),
      warranty=Param("boolean", "Expected to be a warranty repair", default=False))
def workshop_open_job_card(ctx, booking_id, complaint, warranty=False):
    b = ctx.row("SELECT * FROM bookings WHERE booking_id = ?", [booking_id])
    if not b:
        raise ToolError(f"no booking {booking_id}")
    if ctx.scalar("SELECT count(*) FROM job_cards WHERE booking_id = ?", [booking_id]):
        raise ToolError(f"booking {booking_id} already has a job card")
    jno = ctx.next_id("job_cards", "job_no", "J-")
    ctx.db.execute("INSERT INTO job_cards VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   [jno, booking_id, b["vin"], b["customer_id"], ctx.actor, None, "open", complaint, None,
                    warranty, ctx.now, None])
    ctx.db.execute("UPDATE bookings SET status='arrived' WHERE booking_id=?", [booking_id])
    return {"job_no": jno}


@tool("workshop", "Assign a job card to a technician.", writes=True,
      job_no=Param("string", "Job card number"),
      technician=Param("string", "lucas-meyer or aisha-rahman (EV / high-voltage work: aisha-rahman)"))
def workshop_assign_technician(ctx, job_no, technician):
    if technician not in rules.TECHNICIANS:
        raise ToolError(f"{technician} is not a technician")
    _job(ctx, job_no)
    ctx.db.execute("UPDATE job_cards SET technician=? WHERE job_no=?", [technician, job_no])
    return {"job_no": job_no, "technician": technician}


@tool("workshop", "List job cards. technician can be 'me'.",
      status=Param("string", "Job status", default=None, enum=JOB_STATUSES),
      technician=Param("string", "'me' or staff id", default=None),
      open_only=Param("boolean", "Only jobs not yet complete", default=True))
def workshop_list_jobs(ctx, status=None, technician=None, open_only=True):
    sql = ("SELECT j.job_no, j.status, j.technician, j.advisor, j.complaint, j.warranty, j.opened_at, v.reg, v.model "
           "FROM job_cards j LEFT JOIN customer_vehicles v USING (vin) WHERE 1=1")
    args = []
    if status:
        sql += " AND j.status = ?"; args.append(status)
    elif open_only:
        sql += " AND j.status NOT IN ('complete','invoiced')"
    if technician:
        sql += " AND j.technician = ?"; args.append(ctx.actor if technician == "me" else technician)
    return ctx.rows(sql + " ORDER BY j.opened_at DESC LIMIT 40", args)


@tool("workshop", "One job card with its labour/parts lines, parts requests and time booked.",
      job_no=Param("string", "Job card number, e.g. J-01234"))
def workshop_get_job(ctx, job_no):
    j = _job(ctx, job_no)
    j["vehicle"] = ctx.row("SELECT reg, model, fuel, year, mileage, warranty_until FROM customer_vehicles WHERE vin=?",
                           [j["vin"]])
    j["lines"] = ctx.rows("SELECT * FROM job_lines WHERE job_no=? ORDER BY line_id", [job_no])
    j["parts_requests"] = ctx.rows("SELECT request_id, part_no, qty, status FROM parts_requests WHERE job_no=?", [job_no])
    j["hours_booked"] = ctx.scalar("SELECT coalesce(sum(hours),0) FROM time_entries WHERE job_no=?", [job_no])
    return j


@tool("workshop", "Add labour or extra work to a job card. Work the customer has not agreed to yet is added "
                  "unauthorised; the advisor must call them and authorise it.", writes=True,
      job_no=Param("string", "Job card number"), description=Param("string", "What needs doing"),
      hours=Param("number", "Labour hours"),
      authorised=Param("boolean", "Already agreed with the customer (e.g. the booked service)", default=False))
def workshop_add_labour(ctx, job_no, description, hours, authorised=False):
    j = _job(ctx, job_no)
    lid = ctx.next_id("job_lines", "line_id", "JL-", 6)
    rate = rules.WARRANTY_LABOUR_RATE if j["warranty"] else rules.LABOUR_RATE
    ctx.db.execute("INSERT INTO job_lines VALUES (?,?,?,?,?,?,?,?,?,?)",
                   [lid, job_no, "labour", description, None, hours, rate, authorised, ctx.actor, ctx.now])
    if not authorised:
        ctx.db.execute("UPDATE job_cards SET status='waiting_authorisation' WHERE job_no=?", [job_no])
    return {"line_id": lid, "price": round(hours * rate, 2), "authorised": authorised}


@tool("workshop", "Record the customer's yes/no on extra work.", writes=True,
      job_no=Param("string", "Job card number"), line_id=Param("string", "Job line id"),
      authorised=Param("boolean", "Customer agreed"))
def workshop_authorise_work(ctx, job_no, line_id, authorised):
    _job(ctx, job_no)
    if authorised:
        ctx.db.execute("UPDATE job_lines SET authorised=TRUE WHERE line_id=? AND job_no=?", [line_id, job_no])
    else:
        ctx.db.execute("DELETE FROM job_lines WHERE line_id=? AND job_no=?", [line_id, job_no])
    pending = ctx.scalar("SELECT count(*) FROM job_lines WHERE job_no=? AND NOT authorised", [job_no])
    if not pending:
        ctx.db.execute("UPDATE job_cards SET status='in_progress' WHERE job_no=? AND status='waiting_authorisation'",
                       [job_no])
    return {"job_no": job_no, "line_id": line_id, "authorised": authorised, "still_waiting": pending}


@tool("workshop", "Update a job card's status and findings (technician notes).", writes=True,
      job_no=Param("string", "Job card number"),
      status=Param("string", "New status", enum=["in_progress", "waiting_parts", "complete"]),
      findings=Param("string", "What you found / did", default=None))
def workshop_update_job(ctx, job_no, status, findings=None):
    j = _job(ctx, job_no)
    if j["status"] == "invoiced":
        raise ToolError(f"{job_no} is already invoiced")
    if status == "complete":
        if ctx.scalar("SELECT count(*) FROM job_lines WHERE job_no=? AND NOT authorised", [job_no]):
            raise ToolError("there is unauthorised extra work on this job; the advisor must resolve it first")
        if ctx.scalar("SELECT count(*) FROM parts_requests WHERE job_no=? AND status IN ('requested','ordered')", [job_no]):
            raise ToolError("parts requests on this job are still outstanding")
    notes = (j["findings"] + "\n" if j["findings"] else "") + findings if findings else j["findings"]
    ctx.db.execute("UPDATE job_cards SET status=?, findings=?, closed_at=? WHERE job_no=?",
                   [status, notes, ctx.now if status == "complete" else None, job_no])
    return {"job_no": job_no, "status": status}


@tool("workshop", "Book your working time against a job card.", writes=True,
      job_no=Param("string", "Job card number"), hours=Param("number", "Hours worked"),
      note=Param("string", "What you did", default=""))
def workshop_log_time(ctx, job_no, hours, note=""):
    _job(ctx, job_no)
    if not 0 < hours <= 10:
        raise ToolError("hours must be between 0 and 10")
    eid = ctx.next_id("time_entries", "entry_id", "T-", 6)
    ctx.db.execute("INSERT INTO time_entries VALUES (?,?,?,?,?,?)", [eid, job_no, ctx.actor, hours, note, ctx.now])
    return {"entry_id": eid}


@tool("workshop", "Invoice a completed job to the customer (warranty work is billed to BMW instead).", writes=True,
      job_no=Param("string", "Job card number"))
def workshop_invoice_job(ctx, job_no):
    j = _job(ctx, job_no)
    if j["status"] != "complete":
        raise ToolError(f"{job_no} is {j['status']}, not complete")
    net = ctx.scalar("SELECT coalesce(sum(qty * unit_price),0) FROM job_lines WHERE job_no=? AND authorised", [job_no])
    ctx.db.execute("UPDATE job_cards SET status='invoiced' WHERE job_no=?", [job_no])
    if j["warranty"]:
        return {"job_no": job_no, "invoice_no": None, "message": "warranty job: submit a claim to BMW for "
                f"{float(net):.2f} GBP (needs Elena's approval)"}
    from apps.finance import raise_invoice
    inv = raise_invoice(ctx, "service", job_no, j["customer_id"], float(net))
    return {"job_no": job_no, "invoice_no": inv, "net": float(net), "total": round(float(net) * (1 + rules.VAT), 2)}


@tool("workshop", "Ask for a goodwill contribution on a job (manager approval: Elena up to 500 GBP, "
                  "Victor above).", writes=True,
      job_no=Param("string", "Job card number"), amount=Param("number", "GBP"),
      reason=Param("string", "Why goodwill is fair"))
def workshop_request_goodwill(ctx, job_no, amount, reason):
    _job(ctx, job_no)
    from apps.dms import _request_approval
    approver = rules.goodwill_approver(float(amount))
    aid = _request_approval(ctx, "goodwill", job_no, approver, amount, None, reason)
    return {"approval_id": aid, "approver": approver}


@tool("workshop", "Ask the aftersales manager to approve a warranty claim before it goes to BMW.", writes=True,
      job_no=Param("string", "Job card number"), amount=Param("number", "Claim amount GBP"),
      reason=Param("string", "Fault and repair summary"))
def workshop_request_warranty_approval(ctx, job_no, amount, reason):
    j = _job(ctx, job_no)
    if not j["warranty"]:
        raise ToolError(f"{job_no} is not flagged as a warranty job")
    from apps.dms import _request_approval
    aid = _request_approval(ctx, "warranty", job_no, rules.AFTERSALES_MANAGER, amount, None, reason)
    return {"approval_id": aid, "approver": rules.AFTERSALES_MANAGER}


@tool("workshop", "Record a completed pre-delivery inspection on a new stock car.", writes=True,
      stock_no=Param("string", "Stock number"), notes=Param("string", "Checks done, software level"))
def workshop_complete_pdi(ctx, stock_no, notes):
    v = ctx.row("SELECT arrived_at, condition FROM vehicles WHERE stock_no=?", [stock_no])
    if not v:
        raise ToolError(f"no vehicle {stock_no}")
    if not v["arrived_at"]:
        raise ToolError(f"{stock_no} has not arrived yet")
    ctx.db.execute("UPDATE vehicles SET pdi_done=TRUE WHERE stock_no=?", [stock_no])
    return {"stock_no": stock_no, "pdi_done": True, "notes": notes}


def _job(ctx, job_no):
    j = ctx.row("SELECT * FROM job_cards WHERE job_no = ?", [job_no])
    if not j:
        raise ToolError(f"no job card {job_no}")
    return j
