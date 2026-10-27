"""Dealer Management System: vehicle stock, sales deals and discounts, approvals, car order requests."""
import datetime as dt

from systems import rules
from systems.common import Param, ToolError, tool

DEAL_STATUSES = ["draft", "pending_approval", "approved", "signed", "delivered", "cancelled"]


@tool("dms", "Search vehicle stock. Defaults to cars on site and available.",
      model=Param("string", "Text in the model name, e.g. 'X3', 'i4', 'M3'", default=None),
      condition=Param("string", "new or used", default=None, enum=["new", "used"]),
      fuel=Param("string", "Fuel type", default=None, enum=["petrol", "diesel", "hybrid", "electric"]),
      max_price=Param("number", "Max list price GBP", default=None),
      status=Param("string", "Vehicle status", default="in_stock",
                   enum=["on_order", "in_transit", "in_stock", "reserved", "sold", "delivered", "any"]),
      limit=Param("integer", "Max results", default=15))
def dms_search_stock(ctx, model=None, condition=None, fuel=None, max_price=None, status="in_stock", limit=15):
    sql = ("SELECT stock_no, model, colour, year, mileage, condition, fuel, status, list_price, "
           "arrived_at::DATE AS arrived, pdi_done FROM vehicles WHERE 1=1")
    args = []
    if status != "any":
        sql += " AND status = ?"; args.append(status)
    if model:
        sql += " AND lower(model) LIKE ?"; args.append(f"%{model.lower()}%")
    if condition:
        sql += " AND condition = ?"; args.append(condition)
    if fuel:
        sql += " AND fuel = ?"; args.append(fuel)
    if max_price:
        sql += " AND list_price <= ?"; args.append(max_price)
    return ctx.rows(sql + " ORDER BY list_price LIMIT ?", args + [min(int(limit), 50)])


@tool("dms", "One vehicle's full record, including cost price, BMW order number and any deal.",
      stock_no=Param("string", "Stock number (S-0123) or VIN"))
def dms_get_vehicle(ctx, stock_no):
    v = ctx.row("SELECT * FROM vehicles WHERE stock_no = ? OR vin = ?", [stock_no, stock_no])
    if not v:
        raise ToolError(f"no vehicle {stock_no}")
    v["deal"] = ctx.row("SELECT deal_id, status, customer_id, salesperson FROM deals WHERE stock_no = ? "
                        "AND status <> 'cancelled' ORDER BY created_at DESC LIMIT 1", [v["stock_no"]])
    return v


@tool("dms", "Start a sales deal (quote) for a customer on a stock vehicle. Reserves the car.", writes=True,
      customer_id=Param("string", "Customer id"), stock_no=Param("string", "Stock number"),
      lead_id=Param("string", "CRM lead id", default=None),
      trade_in_value=Param("number", "Part-exchange value GBP", default=0),
      finance_product=Param("string", "How they pay", default="cash", enum=["cash", "pcp", "hp", "lease"]))
def dms_create_deal(ctx, customer_id, stock_no, lead_id=None, trade_in_value=0, finance_product="cash"):
    v = ctx.row("SELECT * FROM vehicles WHERE stock_no = ?", [stock_no])
    if not v:
        raise ToolError(f"no vehicle {stock_no}")
    if v["status"] not in ("in_stock", "on_order", "in_transit"):
        raise ToolError(f"{stock_no} is {v['status']} and cannot be sold")
    if not ctx.scalar("SELECT count(*) FROM customers WHERE customer_id = ?", [customer_id]):
        raise ToolError(f"no customer {customer_id}")
    did = ctx.next_id("deals", "deal_id", "D-")
    price = float(v["list_price"])
    ctx.db.execute("INSERT INTO deals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   [did, lead_id, customer_id, stock_no, ctx.actor, "draft", price, 0, 0, 0, trade_in_value,
                    price, finance_product, ctx.now, None, None, None])
    if v["status"] == "in_stock":
        ctx.db.execute("UPDATE vehicles SET status = 'reserved' WHERE stock_no = ?", [stock_no])
    if lead_id:
        ctx.db.execute("UPDATE leads SET status = 'quoted', updated_at = ? WHERE lead_id = ?", [ctx.now, lead_id])
    return dms_get_deal(ctx, did)


@tool("dms", "One deal with price breakdown and approval history.", deal_id=Param("string", "Deal id, e.g. D-00042"))
def dms_get_deal(ctx, deal_id):
    d = ctx.row("SELECT d.*, v.model, v.condition, v.cost_price FROM deals d JOIN vehicles v USING (stock_no) "
                "WHERE deal_id = ?", [deal_id])
    if not d:
        raise ToolError(f"no deal {deal_id}")
    d["approvals"] = ctx.rows("SELECT approval_id, status, pct, approver, requested_by, reason, decision_note "
                              "FROM approvals WHERE kind = 'discount' AND ref_id = ? ORDER BY requested_at", [deal_id])
    return d


@tool("dms", "List deals. salesperson can be 'me' or a staff id.",
      status=Param("string", "Deal status", default=None, enum=DEAL_STATUSES),
      salesperson=Param("string", "'me' or staff id", default=None),
      limit=Param("integer", "Max results", default=20))
def dms_list_deals(ctx, status=None, salesperson=None, limit=20):
    sql = ("SELECT d.deal_id, d.status, d.salesperson, d.customer_id, c.first_name || ' ' || c.last_name AS customer, "
           "v.model, d.list_price, d.discount_pct, d.final_price, d.created_at FROM deals d "
           "JOIN vehicles v USING (stock_no) JOIN customers c USING (customer_id) WHERE 1=1")
    args = []
    if status:
        sql += " AND d.status = ?"; args.append(status)
    if salesperson:
        sql += " AND d.salesperson = ?"; args.append(ctx.actor if salesperson == "me" else salesperson)
    return ctx.rows(sql + " ORDER BY d.created_at DESC LIMIT ?", args + [min(int(limit), 100)])


@tool("dms", "Set the price on a deal. Discounts above your limit (consultants 3%, sales manager 8%) "
             "put the deal on hold and send an approval request to the right manager. Accessories are "
             "priced at retail and are not a discount.", writes=True,
      deal_id=Param("string", "Deal id"),
      discount_pct=Param("number", "Discount as % of list price, e.g. 4.5"),
      reason=Param("string", "Why this discount is justified"),
      accessories_amount=Param("number", "Accessories added at retail price GBP", default=0),
      trade_in_value=Param("number", "Part-exchange value GBP", default=None))
def dms_set_deal_price(ctx, deal_id, discount_pct, reason, accessories_amount=0, trade_in_value=None):
    d = ctx.row("SELECT * FROM deals WHERE deal_id = ?", [deal_id])
    if not d:
        raise ToolError(f"no deal {deal_id}")
    if d["status"] in ("signed", "delivered", "cancelled"):
        raise ToolError(f"deal {deal_id} is {d['status']}; price can no longer change")
    pct = round(float(discount_pct), 2)
    if pct < 0 or pct > 30:
        raise ToolError("discount must be between 0 and 30%")
    if accessories_amount < 0:
        raise ToolError("accessories amount cannot be negative; a reduction is a discount")
    tiv = float(d["trade_in_value"] if trade_in_value is None else trade_in_value)
    lp = float(d["list_price"])
    disc = round(lp * pct / 100, 2)
    final = round(lp - disc + float(accessories_amount), 2)
    own_limit = rules.DISCOUNT_LIMIT.get(ctx.actor, 0)
    needs = pct > own_limit
    status = "pending_approval" if needs else "approved"
    ctx.db.execute("UPDATE deals SET discount_pct=?, discount_amount=?, accessories_amount=?, trade_in_value=?, "
                   "final_price=?, status=?, notes=? WHERE deal_id=?",
                   [pct, disc, accessories_amount, tiv, final, status, reason, deal_id])
    # any earlier pending request is superseded
    ctx.db.execute("UPDATE approvals SET status='rejected', decided_at=?, decision_note='superseded by new price' "
                   "WHERE kind='discount' AND ref_id=? AND status='pending'", [ctx.now, deal_id])
    out = {"deal_id": deal_id, "list_price": lp, "discount_pct": pct, "discount_amount": disc,
           "accessories_amount": accessories_amount, "trade_in_value": tiv, "final_price": final,
           "balance_to_pay": round(final - tiv, 2), "status": status}
    if needs:
        approver = rules.discount_approver(pct) if ctx.actor in rules.SALES_CONSULTANTS else rules.GM
        aid = _request_approval(ctx, "discount", deal_id, approver, disc, pct, reason)
        out.update(approval_id=aid, approver=approver,
                   message=f"{pct}% is above your {own_limit}% limit; approval request {aid} sent to {approver}")
    return out


@tool("dms", "Approval requests waiting for you (or that you raised). Covers discounts, goodwill, stock orders.",
      mine=Param("string", "'to_decide' = waiting for my decision, 'raised' = ones I asked for",
                 default="to_decide", enum=["to_decide", "raised"]),
      status=Param("string", "Approval status", default="pending", enum=["pending", "approved", "rejected", "any"]))
def dms_list_approvals(ctx, mine="to_decide", status="pending"):
    col = "approver" if mine == "to_decide" else "requested_by"
    sql = f"SELECT * FROM approvals WHERE {col} = ?"
    args = [ctx.actor]
    if status != "any":
        sql += " AND status = ?"; args.append(status)
    return ctx.rows(sql + " ORDER BY requested_at DESC LIMIT 30", args)


@tool("dms", "Approve or reject an approval request addressed to you.", writes=True,
      approval_id=Param("string", "Approval id, e.g. AP-00012"),
      decision=Param("string", "approve or reject", enum=["approve", "reject"]),
      note=Param("string", "Reason for the decision"))
def dms_decide_approval(ctx, approval_id, decision, note):
    a = ctx.row("SELECT * FROM approvals WHERE approval_id = ?", [approval_id])
    if not a:
        raise ToolError(f"no approval {approval_id}")
    if a["status"] != "pending":
        raise ToolError(f"{approval_id} is already {a['status']}")
    if a["requested_by"] == ctx.actor:
        raise ToolError("you cannot approve your own request")
    if decision == "approve" and not rules.can_approve(ctx.actor, a["kind"], a["amount"], a["pct"]):
        raise ToolError(f"{ctx.actor} is not authorised to approve this {a['kind']}; escalate to {rules.GM}")
    status = "approved" if decision == "approve" else "rejected"
    ctx.db.execute("UPDATE approvals SET status=?, decided_at=?, decision_note=?, approver=? WHERE approval_id=?",
                   [status, ctx.now, note, ctx.actor, approval_id])
    if a["kind"] == "discount":
        ctx.db.execute("UPDATE deals SET status=? WHERE deal_id=? AND status='pending_approval'",
                       ["approved" if status == "approved" else "draft", a["ref_id"]])
    elif a["kind"] == "stock_order":
        ctx.db.execute("UPDATE order_requests SET status=? WHERE request_id=? AND status='pending_approval'",
                       ["open" if status == "approved" else "cancelled", a["ref_id"]])
    return {"approval_id": approval_id, "status": status, "kind": a["kind"], "ref_id": a["ref_id"]}


@tool("dms", "Customer signs the order. The deal's price must be within limits or approved.", writes=True,
      deal_id=Param("string", "Deal id"))
def dms_sign_deal(ctx, deal_id):
    d = ctx.row("SELECT * FROM deals WHERE deal_id = ?", [deal_id])
    if not d:
        raise ToolError(f"no deal {deal_id}")
    if d["status"] == "pending_approval":
        raise ToolError(f"deal {deal_id} is waiting for discount approval")
    if d["status"] not in ("draft", "approved"):
        raise ToolError(f"deal {deal_id} is {d['status']}")
    if float(d["discount_pct"]) > rules.DISCOUNT_LIMIT.get(d["salesperson"], 0) and d["status"] != "approved":
        raise ToolError("discount needs approval before signing")
    ctx.db.execute("UPDATE deals SET status='signed', signed_at=? WHERE deal_id=?", [ctx.now, deal_id])
    ctx.db.execute("UPDATE vehicles SET status='sold' WHERE stock_no=?", [d["stock_no"]])
    if d["lead_id"]:
        ctx.db.execute("UPDATE leads SET status='won', updated_at=? WHERE lead_id=?", [ctx.now, d["lead_id"]])
    return {"deal_id": deal_id, "status": "signed"}


@tool("dms", "Hand the car over to the customer. Needs a signed deal, the car on site and PDI done. "
             "Raises the vehicle invoice.", writes=True, deal_id=Param("string", "Deal id"))
def dms_deliver_deal(ctx, deal_id):
    d = ctx.row("SELECT d.*, v.arrived_at, v.pdi_done, v.condition FROM deals d JOIN vehicles v USING (stock_no) "
                "WHERE deal_id = ?", [deal_id])
    if not d:
        raise ToolError(f"no deal {deal_id}")
    if d["status"] != "signed":
        raise ToolError(f"deal {deal_id} is {d['status']}, not signed")
    if not d["arrived_at"]:
        raise ToolError("the car has not arrived at the dealership yet")
    if d["condition"] == "new" and not d["pdi_done"]:
        raise ToolError("pre-delivery inspection not done; ask the workshop (Aisha) to complete the PDI")
    ctx.db.execute("UPDATE deals SET status='delivered', delivered_at=? WHERE deal_id=?", [ctx.now, deal_id])
    ctx.db.execute("UPDATE vehicles SET status='delivered' WHERE stock_no=?", [d["stock_no"]])
    from systems.finance import raise_invoice
    inv = raise_invoice(ctx, "vehicle", deal_id, d["customer_id"], float(d["final_price"]) / (1 + rules.VAT))
    return {"deal_id": deal_id, "status": "delivered", "invoice_no": inv}


@tool("dms", "Request a new car from BMW: a factory order for a customer, or for stock. More than 3 stock "
             "cars in one week needs the General Manager's approval. Once ordered, the car gets an on_order "
             "stock number and a deal can be written on it.", writes=True,
      model_code=Param("string", "BMW model code (see bmw_list_models)"),
      colour=Param("string", "Paint colour"),
      reason=Param("string", "customer or stock", enum=["customer", "stock"]),
      customer_id=Param("string", "Customer id when reason=customer", default=None))
def dms_create_order_request(ctx, model_code, colour, reason, customer_id=None):
    if reason == "customer" and not customer_id:
        raise ToolError("a customer order needs the customer_id")
    rid = ctx.next_id("order_requests", "request_id", "OR-")
    status = "open"
    out = {"request_id": rid}
    if reason == "stock":
        week_start = (ctx.now - dt.timedelta(days=ctx.now.weekday())).date()
        n = ctx.scalar("SELECT count(*) FROM order_requests WHERE reason='stock' AND status <> 'cancelled' "
                       "AND created_at >= ?", [week_start])
        if n + 1 > rules.MAX_STOCK_ORDERS_PER_WEEK and ctx.actor != rules.GM:
            status = "pending_approval"
            out["approval_id"] = _request_approval(ctx, "stock_order", rid, rules.GM, None, None,
                                                   f"stock order #{n + 1} this week: {model_code} {colour}")
            out["message"] = f"this is stock order #{n + 1} this week; sent to {rules.GM} for approval"
    ctx.db.execute("INSERT INTO order_requests VALUES (?,?,?,?,?,?,?,?,?,?)",
                   [rid, model_code, colour, customer_id, reason, ctx.actor, status, None, None, ctx.now])
    out["status"] = status
    return out


@tool("dms", "List car order requests (what still needs ordering from BMW, or is on order).",
      status=Param("string", "Request status", default="open",
                   enum=["pending_approval", "open", "ordered", "cancelled", "any"]))
def dms_list_order_requests(ctx, status="open"):
    if status == "any":
        return ctx.rows("SELECT * FROM order_requests ORDER BY created_at DESC LIMIT 50")
    return ctx.rows("SELECT * FROM order_requests WHERE status = ? ORDER BY created_at DESC LIMIT 50", [status])


@tool("dms", "Record the BMW portal order number against an order request; creates the on-order stock record.",
      writes=True, request_id=Param("string", "Order request id"),
      bmw_order_no=Param("string", "Order number returned by the BMW portal"),
      model=Param("string", "Model name as shown by the portal"),
      list_price=Param("number", "Retail list price GBP"), cost_price=Param("number", "Dealer cost GBP"))
def dms_link_bmw_order(ctx, request_id, bmw_order_no, model, list_price, cost_price):
    r = ctx.row("SELECT * FROM order_requests WHERE request_id = ?", [request_id])
    if not r:
        raise ToolError(f"no order request {request_id}")
    if r["status"] != "open":
        raise ToolError(f"{request_id} is {r['status']}; only open requests can be ordered")
    sno = ctx.next_id("vehicles", "stock_no", "S-", 4)
    fuel = ("electric" if model.lower().startswith("i") or " i" in model.lower()
            else "hybrid" if model.lower().rstrip().endswith("e") else "petrol")
    ctx.db.execute("INSERT INTO vehicles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   [sno, None, r["model_code"], model, model.split()[0], fuel, r["colour"], ctx.now.year, 0,
                    "new", "on_order", list_price, cost_price, bmw_order_no, None, False, None])
    # a customer's factory order is spoken for; the consultant writes the deal on this stock number
    ctx.db.execute("UPDATE order_requests SET status='ordered', bmw_order_no=?, stock_no=? WHERE request_id=?",
                   [bmw_order_no, sno, request_id])
    return {"request_id": request_id, "stock_no": sno, "bmw_order_no": bmw_order_no}


@tool("dms", "Book a delivered car into stock when it arrives from BMW.", writes=True,
      stock_no=Param("string", "Stock number"), vin=Param("string", "VIN from the delivery note"))
def dms_mark_vehicle_arrived(ctx, stock_no, vin):
    v = ctx.row("SELECT * FROM vehicles WHERE stock_no = ?", [stock_no])
    if not v:
        raise ToolError(f"no vehicle {stock_no}")
    if v["arrived_at"]:
        raise ToolError(f"{stock_no} already arrived on {v['arrived_at']}")
    sold = ctx.scalar("SELECT count(*) FROM deals WHERE stock_no=? AND status IN ('signed','approved')", [stock_no])
    ctx.db.execute("UPDATE vehicles SET vin=?, arrived_at=?, status=? WHERE stock_no=?",
                   [vin, ctx.now, "sold" if sold else "in_stock", stock_no])
    return {"stock_no": stock_no, "status": "sold" if sold else "in_stock", "next": "workshop PDI before handover"}


def _request_approval(ctx, kind, ref_id, approver, amount, pct, reason):
    aid = ctx.next_id("approvals", "approval_id", "AP-")
    ctx.db.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   [aid, kind, ref_id, ctx.actor, approver, amount, pct, reason, "pending", ctx.now, None, None])
    return aid
