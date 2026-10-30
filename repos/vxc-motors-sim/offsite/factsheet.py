"""The General Manager's business-review fact sheet, computed from the dealership's own data.

Reads data/parquet/internal/*.parquet (the seed data the tool services load) with DuckDB and returns a
small dict of figures. The off-site gives it to Victor so his review quotes real numbers, and the runner
saves it next to the transcript so the review can be checked.

    python3 -m offsite.factsheet            # print the figures as JSON
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTERNAL = os.path.join(ROOT, "data", "parquet", "internal")


def _q(con, sql):
    return con.execute(sql).fetchall()


def build(internal=INTERNAL):
    import duckdb
    con = duckdb.connect()
    for t in ("deals", "invoices", "job_cards", "leads", "vehicles"):
        con.execute(f"CREATE VIEW {t} AS SELECT * FROM read_parquet('{os.path.join(internal, t + '.parquet')}')")
    as_of = _q(con, "SELECT max(created_at)::DATE FROM deals")[0][0]
    sold = "status IN ('signed','delivered','invoiced')"
    by_person = _q(con, f"""SELECT salesperson, count(*), round(avg(discount_pct),1), round(sum(final_price))
                           FROM deals WHERE {sold} GROUP BY 1 ORDER BY 2 DESC""")
    monthly = _q(con, f"""SELECT strftime(signed_at, '%Y-%m') m, count(*) FROM deals
                         WHERE {sold} AND signed_at IS NOT NULL GROUP BY 1 ORDER BY 1""")
    revenue = _q(con, "SELECT kind, round(sum(net)) FROM invoices GROUP BY 1 ORDER BY 2 DESC")
    unpaid = _q(con, "SELECT count(*), round(sum(total)) FROM invoices WHERE paid_at IS NULL")[0]
    jobs = _q(con, "SELECT count(*), round(100.0*avg(CASE WHEN warranty THEN 1 ELSE 0 END),1) FROM job_cards")[0]
    by_tech = _q(con, "SELECT technician, count(*) FROM job_cards WHERE technician IS NOT NULL GROUP BY 1 ORDER BY 2 DESC")
    leads = _q(con, "SELECT status, count(*) FROM leads GROUP BY 1 ORDER BY 2 DESC")
    lost = _q(con, """SELECT lost_reason, count(*) FROM leads WHERE lost_reason IS NOT NULL
                      GROUP BY 1 ORDER BY 2 DESC LIMIT 4""")
    sources = _q(con, "SELECT source, count(*) FROM leads GROUP BY 1 ORDER BY 2 DESC LIMIT 5")
    stock = _q(con, "SELECT condition, fuel, count(*) FROM vehicles WHERE status = 'in_stock' GROUP BY 1, 2 ORDER BY 3 DESC")
    over8 = _q(con, f"SELECT count(*) FROM deals WHERE {sold} AND discount_pct > 8")[0][0]
    return {
        "as_of": str(as_of),
        "cars_sold_total": sum(r[1] for r in by_person),
        "cars_sold_by_salesperson": [{"who": r[0], "units": r[1], "avg_discount_pct": float(r[2]),
                                      "revenue_gbp": float(r[3])} for r in by_person],
        "cars_sold_by_month": [{"month": m, "units": n} for m, n in monthly],
        "deals_over_8pct_discount": over8,
        "invoiced_net_gbp_by_kind": {k: float(v) for k, v in revenue},
        "unpaid_invoices": {"count": unpaid[0], "total_gbp": float(unpaid[1] or 0)},
        "workshop_job_cards": jobs[0],
        "warranty_share_pct": float(jobs[1]),
        "job_cards_by_technician": dict(by_tech),
        "leads_by_status": dict(leads),
        "top_lost_reasons": dict(lost),
        "top_lead_sources": dict(sources),
        "stock_in_hand": [{"condition": c, "fuel": fu, "units": n} for c, fu, n in stock],
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, default=str))
