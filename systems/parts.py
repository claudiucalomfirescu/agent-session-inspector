"""Parts Inventory: stock, bin locations, parts requests against job cards, issues and receipts."""
from systems.common import Param, ToolError, tool


@tool("parts", "Search parts stock by part number, description or model it fits.",
      query=Param("string", "e.g. 'brake pads G20', 'oil filter', '11 42 8 575 211'"),
      in_stock_only=Param("boolean", "Only parts we have on the shelf", default=False))
def parts_search(ctx, query, in_stock_only=False):
    words = [w for w in query.lower().replace("-", " ").split() if w]
    sql = ("SELECT part_no, description, fits, bin, qty_on_hand, qty_reserved, "
           "qty_on_hand - qty_reserved AS available, price FROM parts WHERE TRUE")
    args = []
    for w in words:
        sql += " AND (lower(description) LIKE ? OR lower(fits) LIKE ? OR replace(part_no,' ','') LIKE ?)"
        args += [f"%{w}%", f"%{w}%", f"%{w}%"]
    if in_stock_only:
        sql += " AND qty_on_hand - qty_reserved > 0"
    return ctx.rows(sql + " ORDER BY description LIMIT 25", args)


@tool("parts", "One part: stock, bin, prices, recent movements.", part_no=Param("string", "Part number"))
def parts_get(ctx, part_no):
    p = ctx.row("SELECT * FROM parts WHERE part_no = ?", [part_no])
    if not p:
        raise ToolError(f"no part {part_no} in our stock file; check bmw_search_parts")
    p["movements"] = ctx.rows("SELECT occurred_at, kind, qty, ref, staff_id FROM parts_movements WHERE part_no=? "
                              "ORDER BY occurred_at DESC LIMIT 8", [part_no])
    return p


@tool("parts", "Request parts for a job card (technicians). Reserves stock if available.", writes=True,
      job_no=Param("string", "Job card number"), part_no=Param("string", "Part number"),
      qty=Param("integer", "Quantity"))
def parts_request(ctx, job_no, part_no, qty):
    j = ctx.row("SELECT status FROM job_cards WHERE job_no=?", [job_no])
    if not j:
        raise ToolError(f"parts are only issued against a valid job card; {job_no} does not exist")
    if j["status"] in ("complete", "invoiced"):
        raise ToolError(f"job {job_no} is {j['status']}")
    p = ctx.row("SELECT * FROM parts WHERE part_no=?", [part_no])
    if qty < 1:
        raise ToolError("qty must be at least 1")
    rid = ctx.next_id("parts_requests", "request_id", "PR-")
    available = (p["qty_on_hand"] - p["qty_reserved"]) if p else 0
    if p and available >= qty:
        ctx.db.execute("UPDATE parts SET qty_reserved = qty_reserved + ? WHERE part_no=?", [qty, part_no])
    ctx.db.execute("INSERT INTO parts_requests VALUES (?,?,?,?,?,?,?,?,?,?)",
                   [rid, job_no, part_no, qty, ctx.actor, "requested", None, None, ctx.now, None])
    return {"request_id": rid, "in_stock": available >= qty, "available": available,
            "next": "parts counter will issue it" if available >= qty else
                    "not on the shelf: parts will order it from BMW (VOR if the car is off the road)"}


@tool("parts", "Open parts requests from the workshop.",
      status=Param("string", "Request status", default="requested", enum=["requested", "ordered", "issued", "any"]))
def parts_list_requests(ctx, status="requested"):
    sql = ("SELECT r.*, p.description, p.bin, p.qty_on_hand - p.qty_reserved + "
           "CASE WHEN r.status='requested' AND p.qty_on_hand >= r.qty THEN r.qty ELSE 0 END AS shelf_ok "
           "FROM parts_requests r LEFT JOIN parts p USING (part_no)")
    if status == "any":
        return ctx.rows(sql + " ORDER BY r.requested_at DESC LIMIT 40")
    return ctx.rows(sql + " WHERE r.status = ? ORDER BY r.requested_at LIMIT 40", [status])


@tool("parts", "Issue a requested part from the shelf to the technician; adds it to the job card.", writes=True,
      request_id=Param("string", "Parts request id"))
def parts_issue(ctx, request_id):
    r = ctx.row("SELECT * FROM parts_requests WHERE request_id=?", [request_id])
    if not r:
        raise ToolError(f"no parts request {request_id}")
    if r["status"] == "issued":
        raise ToolError(f"{request_id} was already issued")
    p = ctx.row("SELECT * FROM parts WHERE part_no=?", [r["part_no"]])
    if not p or p["qty_on_hand"] < r["qty"]:
        raise ToolError(f"not enough {r['part_no']} on the shelf ({p['qty_on_hand'] if p else 0}); order it from BMW")
    reserved = r["qty"] if r["status"] == "requested" and p["qty_reserved"] >= r["qty"] else 0
    ctx.db.execute("UPDATE parts SET qty_on_hand = qty_on_hand - ?, qty_reserved = qty_reserved - ? WHERE part_no=?",
                   [r["qty"], reserved, r["part_no"]])
    ctx.db.execute("UPDATE parts_requests SET status='issued', issued_by=?, issued_at=? WHERE request_id=?",
                   [ctx.actor, ctx.now, request_id])
    _move(ctx, r["part_no"], -r["qty"], "issue", r["job_no"])
    warranty = ctx.scalar("SELECT warranty FROM job_cards WHERE job_no=?", [r["job_no"]])
    ctx.db.execute("INSERT INTO job_lines VALUES (?,?,?,?,?,?,?,?,?,?)",
                   [ctx.next_id("job_lines", "line_id", "JL-", 6), r["job_no"], "part", p["description"],
                    r["part_no"], r["qty"], p["cost"] if warranty else p["price"], True, ctx.actor, ctx.now])
    return {"request_id": request_id, "issued": r["qty"], "job_no": r["job_no"], "bin": p["bin"]}


@tool("parts", "Mark a parts request as ordered from BMW (after bmw_place_parts_order).", writes=True,
      request_id=Param("string", "Parts request id"), bmw_order_no=Param("string", "BMW parts order number"))
def parts_mark_ordered(ctx, request_id, bmw_order_no):
    if not ctx.scalar("SELECT count(*) FROM parts_requests WHERE request_id=?", [request_id]):
        raise ToolError(f"no parts request {request_id}")
    ctx.db.execute("UPDATE parts_requests SET status='ordered', bmw_order_no=? WHERE request_id=?",
                   [bmw_order_no, request_id])
    return {"request_id": request_id, "status": "ordered"}


@tool("parts", "Book a delivery from BMW into stock (one line per call).", writes=True,
      part_no=Param("string", "Part number"), qty=Param("integer", "Quantity received"),
      bmw_order_no=Param("string", "BMW order / delivery note number"),
      description=Param("string", "Description, needed only for a part new to our stock file", default=None),
      cost=Param("number", "Dealer cost each, for a new part", default=None),
      price=Param("number", "Retail price each, for a new part", default=None))
def parts_receive(ctx, part_no, qty, bmw_order_no, description=None, cost=None, price=None):
    if qty < 1:
        raise ToolError("qty must be at least 1")
    if ctx.scalar("SELECT count(*) FROM parts WHERE part_no=?", [part_no]):
        ctx.db.execute("UPDATE parts SET qty_on_hand = qty_on_hand + ? WHERE part_no=?", [qty, part_no])
    else:
        if not (description and cost and price):
            raise ToolError("new part: give description, cost and price")
        ctx.db.execute("INSERT INTO parts VALUES (?,?,?,?,?,?,?,?,?,?)",
                       [part_no, description, "other", "", "Z-99", qty, 0, 0, cost, price])
    _move(ctx, part_no, qty, "receipt", bmw_order_no)
    # requests that were waiting for this order can now be issued
    waiting = ctx.rows("SELECT request_id, job_no, qty FROM parts_requests WHERE part_no=? AND status='ordered'", [part_no])
    return {"part_no": part_no, "received": qty, "waiting_requests": waiting}


@tool("parts", "Parts at or below their reorder level (what to put on the 15:00 stock order).")
def parts_low_stock(ctx):
    return ctx.rows("SELECT part_no, description, qty_on_hand, qty_reserved, reorder_level, "
                    "greatest(reorder_level * 2 - qty_on_hand + qty_reserved, 1) AS suggested_qty "
                    "FROM parts WHERE qty_on_hand - qty_reserved <= reorder_level ORDER BY description")


@tool("parts", "Sell parts over the counter to a customer.", writes=True,
      part_no=Param("string", "Part number"), qty=Param("integer", "Quantity"),
      customer_id=Param("string", "Customer id", default=None))
def parts_counter_sale(ctx, part_no, qty, customer_id=None):
    p = ctx.row("SELECT * FROM parts WHERE part_no=?", [part_no])
    if not p or p["qty_on_hand"] - p["qty_reserved"] < qty:
        raise ToolError("not enough stock")
    ctx.db.execute("UPDATE parts SET qty_on_hand = qty_on_hand - ? WHERE part_no=?", [qty, part_no])
    _move(ctx, part_no, -qty, "counter_sale", customer_id)
    from systems.finance import raise_invoice
    inv = raise_invoice(ctx, "parts", part_no, customer_id, float(p["price"]) * qty)
    return {"invoice_no": inv, "net": float(p["price"]) * qty}


def _move(ctx, part_no, qty, kind, ref):
    ctx.db.execute("INSERT INTO parts_movements VALUES (?,?,?,?,?,?,?)",
                   [ctx.next_id("parts_movements", "movement_id", "M-", 6), part_no, qty, kind, ref, ctx.actor, ctx.now])
