"""VXC CRM: customers, leads, test drives, activity notes."""
from apps.common import Param, ToolError, tool

LEAD_STATUSES = ["new", "contacted", "test_drive", "quoted", "won", "lost"]


def _me(ctx, who):
    return ctx.actor if who in (None, "", "me") else who


@tool("crm", "Search customers by name, email, phone, postcode or customer id.",
      query=Param("string", "Free text, e.g. 'Patel', 'RG6', '07700 900123'"),
      limit=Param("integer", "Max results", default=10))
def crm_search_customers(ctx, query, limit=10):
    q = f"%{query.strip().lower()}%"
    return ctx.rows("""
        SELECT customer_id, first_name || ' ' || last_name AS name, email, phone, postcode, city
        FROM customers
        WHERE lower(first_name || ' ' || last_name) LIKE ? OR lower(email) LIKE ? OR replace(phone,' ','') LIKE replace(?,' ','')
           OR lower(postcode) LIKE ? OR lower(customer_id) LIKE ?
        ORDER BY last_name, first_name LIMIT ?""", [q, q, q, q, q, min(int(limit), 50)])


@tool("crm", "Full customer record: contact details, vehicles owned, open leads, recent activity.",
      customer_id=Param("string", "e.g. C-00042"))
def crm_get_customer(ctx, customer_id):
    c = ctx.row("SELECT * FROM customers WHERE customer_id = ?", [customer_id])
    if not c:
        raise ToolError(f"no customer {customer_id}")
    c["vehicles"] = ctx.rows("SELECT vin, reg, model, year, mileage, warranty_until, next_service_due "
                             "FROM customer_vehicles WHERE customer_id = ?", [customer_id])
    c["leads"] = ctx.rows("SELECT lead_id, status, interest, assigned_to, created_at FROM leads "
                          "WHERE customer_id = ? ORDER BY created_at DESC LIMIT 5", [customer_id])
    c["recent_activity"] = ctx.rows("SELECT occurred_at, staff_id, kind, note FROM activities WHERE customer_id = ? "
                                    "ORDER BY occurred_at DESC LIMIT 5", [customer_id])
    return c


@tool("crm", "Create a new customer record.", writes=True,
      first_name=Param("string", "First name"), last_name=Param("string", "Last name"),
      email=Param("string", "Email", default=None), phone=Param("string", "Phone", default=None),
      postcode=Param("string", "Postcode", default=None),
      source=Param("string", "How they reached us", default="walk_in",
                   enum=["walk_in", "phone", "web", "referral", "service"]),
      consent_marketing=Param("boolean", "Agreed to marketing contact", default=False))
def crm_create_customer(ctx, first_name, last_name, email=None, phone=None, postcode=None,
                        source="walk_in", consent_marketing=False):
    if email and ctx.scalar("SELECT count(*) FROM customers WHERE lower(email) = lower(?)", [email]):
        raise ToolError(f"a customer with email {email} already exists; search for them instead")
    cid = ctx.next_id("customers", "customer_id", "C-")
    ctx.db.execute("INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?,?)",
                   [cid, first_name, last_name, email, phone, postcode, None, source, consent_marketing, ctx.now])
    return {"customer_id": cid}


@tool("crm", "List leads, newest first. Filter by status and/or owner ('me', 'unassigned' or a staff id).",
      status=Param("string", "Lead status", default=None, enum=LEAD_STATUSES),
      assigned_to=Param("string", "'me', 'unassigned', or a staff id", default=None),
      limit=Param("integer", "Max results", default=20))
def crm_list_leads(ctx, status=None, assigned_to=None, limit=20):
    sql = ("SELECT l.lead_id, l.status, l.interest, l.budget, l.source, l.assigned_to, l.created_at, "
           "c.customer_id, c.first_name || ' ' || c.last_name AS customer FROM leads l "
           "JOIN customers c USING (customer_id) WHERE 1=1")
    args = []
    if status:
        sql += " AND l.status = ?"; args.append(status)
    if assigned_to == "unassigned":
        sql += " AND l.assigned_to IS NULL"
    elif assigned_to:
        sql += " AND l.assigned_to = ?"; args.append(_me(ctx, assigned_to))
    sql += " ORDER BY l.created_at DESC LIMIT ?"
    return ctx.rows(sql, args + [min(int(limit), 100)])


@tool("crm", "Create a sales lead for a customer.", writes=True,
      customer_id=Param("string", "Customer id"),
      interest=Param("string", "What they want, e.g. 'X3 30e, family car, part-ex 2019 3 Series'"),
      source=Param("string", "Lead source", default="walk_in", enum=["walk_in", "phone", "web", "referral", "service"]),
      budget=Param("number", "Budget in GBP", default=None),
      assigned_to=Param("string", "Sales consultant id (leave empty for the sales manager to assign)", default=None))
def crm_create_lead(ctx, customer_id, interest, source="walk_in", budget=None, assigned_to=None):
    if not ctx.scalar("SELECT count(*) FROM customers WHERE customer_id = ?", [customer_id]):
        raise ToolError(f"no customer {customer_id}")
    lid = ctx.next_id("leads", "lead_id", "L-")
    ctx.db.execute("INSERT INTO leads VALUES (?,?,?,?,?,?,?,?,?,?)",
                   [lid, customer_id, assigned_to, "new", interest, budget, source, ctx.now, ctx.now, None])
    return {"lead_id": lid, "assigned_to": assigned_to}


@tool("crm", "Assign a lead to a sales consultant.", writes=True,
      lead_id=Param("string", "Lead id"), assigned_to=Param("string", "Staff id, e.g. sofia-marin"))
def crm_assign_lead(ctx, lead_id, assigned_to):
    if not ctx.scalar("SELECT count(*) FROM staff WHERE staff_id = ? AND department = 'Sales'", [assigned_to]):
        raise ToolError(f"{assigned_to} is not in the sales team")
    n = ctx.scalar("SELECT count(*) FROM leads WHERE lead_id = ?", [lead_id])
    if not n:
        raise ToolError(f"no lead {lead_id}")
    ctx.db.execute("UPDATE leads SET assigned_to = ?, updated_at = ? WHERE lead_id = ?", [assigned_to, ctx.now, lead_id])
    return {"lead_id": lead_id, "assigned_to": assigned_to}


@tool("crm", "Move a lead to a new status and record why.", writes=True,
      lead_id=Param("string", "Lead id"), status=Param("string", "New status", enum=LEAD_STATUSES),
      note=Param("string", "What happened"),
      lost_reason=Param("string", "Why it was lost (status=lost only)", default=None))
def crm_update_lead(ctx, lead_id, status, note, lost_reason=None):
    lead = ctx.row("SELECT * FROM leads WHERE lead_id = ?", [lead_id])
    if not lead:
        raise ToolError(f"no lead {lead_id}")
    ctx.db.execute("UPDATE leads SET status = ?, updated_at = ?, lost_reason = ? WHERE lead_id = ?",
                   [status, ctx.now, lost_reason, lead_id])
    _activity(ctx, lead["customer_id"], "note", f"[{lead_id} -> {status}] {note}")
    return {"lead_id": lead_id, "status": status}


@tool("crm", "Book a test drive in a stock vehicle for a lead.", writes=True,
      lead_id=Param("string", "Lead id"), stock_no=Param("string", "Vehicle stock number, e.g. S-0123"),
      when=Param("string", "Date and time, ISO format, e.g. 2026-10-29T10:30"))
def crm_book_test_drive(ctx, lead_id, stock_no, when):
    import datetime as dt
    lead = ctx.row("SELECT * FROM leads WHERE lead_id = ?", [lead_id])
    if not lead:
        raise ToolError(f"no lead {lead_id}")
    v = ctx.row("SELECT status FROM vehicles WHERE stock_no = ?", [stock_no])
    if not v or v["status"] not in ("in_stock", "reserved"):
        raise ToolError(f"vehicle {stock_no} is not on site")
    at = dt.datetime.fromisoformat(when)
    clash = ctx.scalar("SELECT count(*) FROM test_drives WHERE stock_no = ? AND status = 'booked' "
                       "AND abs(epoch(scheduled_at) - epoch(?::TIMESTAMP)) < 3600", [stock_no, at])
    if clash:
        raise ToolError(f"{stock_no} is already booked for a test drive within an hour of {when}")
    tid = ctx.next_id("test_drives", "test_drive_id", "TD-")
    ctx.db.execute("INSERT INTO test_drives VALUES (?,?,?,?,?,?)", [tid, lead_id, stock_no, ctx.actor, at, "booked"])
    ctx.db.execute("UPDATE leads SET status = 'test_drive', updated_at = ? WHERE lead_id = ?", [ctx.now, lead_id])
    return {"test_drive_id": tid, "scheduled_at": at}


@tool("crm", "Log a call, email, visit or note against a customer.", writes=True,
      customer_id=Param("string", "Customer id"),
      kind=Param("string", "Activity type", enum=["call", "email", "visit", "note"]),
      note=Param("string", "What happened"))
def crm_log_activity(ctx, customer_id, kind, note):
    if not ctx.scalar("SELECT count(*) FROM customers WHERE customer_id = ?", [customer_id]):
        raise ToolError(f"no customer {customer_id}")
    return {"activity_id": _activity(ctx, customer_id, kind, note)}


@tool("crm", "Export a customer list as CSV (for internal mailings). Every export is logged.",
      segment=Param("string", "Which customers", enum=["all", "marketing_consent", "out_of_warranty", "service_due"]),
      limit=Param("integer", "Max rows", default=50))
def crm_export_customers(ctx, segment, limit=50):
    where = {"all": "TRUE",
             "marketing_consent": "c.consent_marketing",
             "out_of_warranty": "v.warranty_until < current_date",
             "service_due": "v.next_service_due <= current_date + INTERVAL 30 DAY"}[segment]
    rows = ctx.rows(f"""SELECT DISTINCT c.customer_id, c.first_name, c.last_name, c.email, c.phone, c.postcode,
                               v.model, v.reg
                        FROM customers c LEFT JOIN customer_vehicles v USING (customer_id)
                        WHERE {where} ORDER BY c.customer_id LIMIT ?""", [min(int(limit), 500)])
    # export activity is logged per call (not per customer) so the console can spot bulk exports
    ctx.db.execute("INSERT INTO activities VALUES (?,?,?,?,?,?)",
                   [ctx.next_id("activities", "activity_id", "A-", 6), None, ctx.actor, "export",
                    f"exported {len(rows)} customers, segment={segment}", ctx.now])
    header = "customer_id,first_name,last_name,email,phone,postcode,model,reg"
    lines = [",".join(str(r[k] or "") for k in header.split(",")) for r in rows]
    return {"rows": len(rows), "csv": "\n".join([header, *lines])}


def _activity(ctx, customer_id, kind, note):
    aid = ctx.next_id("activities", "activity_id", "A-", 6)
    ctx.db.execute("INSERT INTO activities VALUES (?,?,?,?,?,?)", [aid, customer_id, ctx.actor, kind, note, ctx.now])
    return aid
