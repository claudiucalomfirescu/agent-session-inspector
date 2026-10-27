"""Finance & Payroll: invoices, payments, the ledger, commission and monthly KPIs."""
import datetime as dt

from systems import rules
from systems.common import Param, ToolError, tool

REVENUE_ACCOUNT = {"vehicle": "sales_vehicles", "service": "sales_service", "parts": "sales_parts"}


def raise_invoice(ctx, kind, ref_id, customer_id, net):
    """Create an invoice and its ledger entries. Used by DMS, workshop and parts."""
    net = round(net, 2)
    vat = round(net * rules.VAT, 2)
    prefix = {"vehicle": "INV-V", "service": "INV-S", "parts": "INV-P"}[kind]
    inv = ctx.next_id("invoices", "invoice_no", prefix + "-")
    ctx.db.execute("INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?,?,?)",
                   [inv, kind, ref_id, customer_id, net, vat, round(net + vat, 2), ctx.now, None, None])
    post(ctx, ctx.now.date(), "receivables", f"{kind} invoice {inv}", net + vat, 0, inv)
    post(ctx, ctx.now.date(), REVENUE_ACCOUNT[kind], f"{kind} invoice {inv}", 0, net, inv)
    post(ctx, ctx.now.date(), "vat_output", f"VAT on {inv}", 0, vat, inv)
    return inv


def post(ctx, date, account, description, debit, credit, ref):
    eid = ctx.next_id("ledger", "entry_id", "GL-", 7)
    ctx.db.execute("INSERT INTO ledger VALUES (?,?,?,?,?,?,?)",
                   [eid, date, account, description, round(debit, 2), round(credit, 2), ref])


@tool("finance", "List invoices.",
      status=Param("string", "unpaid, paid or any", default="unpaid", enum=["unpaid", "paid", "any"]),
      kind=Param("string", "Invoice type", default=None, enum=["vehicle", "service", "parts"]),
      limit=Param("integer", "Max results", default=25))
def finance_list_invoices(ctx, status="unpaid", kind=None, limit=25):
    sql = "SELECT * FROM invoices WHERE TRUE"
    args = []
    if status == "unpaid":
        sql += " AND paid_at IS NULL"
    elif status == "paid":
        sql += " AND paid_at IS NOT NULL"
    if kind:
        sql += " AND kind = ?"; args.append(kind)
    return ctx.rows(sql + " ORDER BY issued_at DESC LIMIT ?", args + [min(int(limit), 100)])


@tool("finance", "Record a customer payment against an invoice.", writes=True,
      invoice_no=Param("string", "Invoice number"), amount=Param("number", "Amount received GBP"),
      method=Param("string", "Payment method", enum=["card", "bank_transfer", "finance_company", "cash"]))
def finance_record_payment(ctx, invoice_no, amount, method):
    i = ctx.row("SELECT * FROM invoices WHERE invoice_no=?", [invoice_no])
    if not i:
        raise ToolError(f"no invoice {invoice_no}")
    if i["paid_at"]:
        raise ToolError(f"{invoice_no} was already paid on {i['paid_at']}")
    if abs(float(amount) - float(i["total"])) > 0.01:
        raise ToolError(f"amount {amount} does not match invoice total {i['total']}; part payments are not supported")
    if method == "cash" and float(amount) > 9000:
        raise ToolError("cash over 9,000 GBP needs anti-money-laundering checks; take a bank transfer")
    ctx.db.execute("UPDATE invoices SET paid_at=?, payment_method=? WHERE invoice_no=?", [ctx.now, method, invoice_no])
    post(ctx, ctx.now.date(), "bank", f"payment {invoice_no} ({method})", float(amount), 0, invoice_no)
    post(ctx, ctx.now.date(), "receivables", f"payment {invoice_no}", 0, float(amount), invoice_no)
    return {"invoice_no": invoice_no, "paid": True}


@tool("finance", "Ledger entries, optionally for one account and/or a date range.",
      account=Param("string", "Account", default=None,
                    enum=["bank", "receivables", "sales_vehicles", "sales_service", "sales_parts", "vat_output",
                          "bmw_payables", "cost_of_sales", "warranty_receivable"]),
      date_from=Param("string", "ISO date", default=None), date_to=Param("string", "ISO date", default=None),
      limit=Param("integer", "Max rows", default=30))
def finance_ledger(ctx, account=None, date_from=None, date_to=None, limit=30):
    sql, args = "SELECT * FROM ledger WHERE TRUE", []
    if account:
        sql += " AND account=?"; args.append(account)
    if date_from:
        sql += " AND date >= ?"; args.append(dt.date.fromisoformat(date_from))
    if date_to:
        sql += " AND date <= ?"; args.append(dt.date.fromisoformat(date_to))
    rows = ctx.rows(sql + " ORDER BY date DESC, entry_id DESC LIMIT ?", args + [min(int(limit), 200)])
    bal = ctx.rows("SELECT account, sum(debit) - sum(credit) AS balance FROM ledger GROUP BY 1 ORDER BY 1"
                   ) if not account else None
    return {"entries": rows, "balances": bal}


@tool("finance", "Record a payment to BMW for a car or parts invoice.", writes=True,
      reference=Param("string", "BMW order or invoice number"), amount=Param("number", "GBP"),
      what=Param("string", "car or parts", enum=["car", "parts"]))
def finance_pay_bmw(ctx, reference, amount, what):
    post(ctx, ctx.now.date(), "bmw_payables", f"pay BMW {what} {reference}", float(amount), 0, reference)
    post(ctx, ctx.now.date(), "bank", f"pay BMW {what} {reference}", 0, float(amount), reference)
    return {"reference": reference, "paid": float(amount)}


@tool("finance", "Sales commission per consultant for a month: 150 GBP per car delivered plus 8% of gross "
                 "profit (price less cost less discount).",
      month=Param("string", "YYYY-MM", default=None), staff_id=Param("string", "Staff id", default=None))
def finance_commission(ctx, month=None, staff_id=None):
    month = month or ctx.now.strftime("%Y-%m")
    sql = ("SELECT d.salesperson, count(*) AS units, round(sum(d.final_price / 1.2 - v.cost_price), 2) AS gross_profit, "
           "round(count(*) * 150 + greatest(sum(d.final_price / 1.2 - v.cost_price), 0) * 0.08, 2) AS commission "
           "FROM deals d JOIN vehicles v USING (stock_no) WHERE d.status='delivered' "
           "AND strftime(d.delivered_at, '%Y-%m') = ?")
    args = [month]
    if staff_id:
        sql += " AND d.salesperson = ?"; args.append(staff_id)
    return {"month": month, "rows": ctx.rows(sql + " GROUP BY 1 ORDER BY 1", args)}


@tool("finance", "Monthly KPIs: cars delivered, revenue by area, workshop jobs, unpaid invoices.",
      month=Param("string", "YYYY-MM", default=None))
def finance_kpis(ctx, month=None):
    month = month or ctx.now.strftime("%Y-%m")
    rev = ctx.rows("SELECT kind, count(*) n, round(sum(net), 2) net FROM invoices "
                   "WHERE strftime(issued_at, '%Y-%m') = ? GROUP BY 1 ORDER BY 1", [month])
    return {
        "month": month,
        "revenue_by_kind": rev,
        "cars_delivered": ctx.scalar("SELECT count(*) FROM deals WHERE status='delivered' "
                                     "AND strftime(delivered_at, '%Y-%m') = ?", [month]),
        "new_leads": ctx.scalar("SELECT count(*) FROM leads WHERE strftime(created_at, '%Y-%m') = ?", [month]),
        "jobs_completed": ctx.scalar("SELECT count(*) FROM job_cards WHERE strftime(closed_at, '%Y-%m') = ?", [month]),
        "unpaid_invoices": ctx.scalar("SELECT count(*) FROM invoices WHERE paid_at IS NULL"),
        "unpaid_total": ctx.scalar("SELECT coalesce(round(sum(total),2),0) FROM invoices WHERE paid_at IS NULL"),
    }
