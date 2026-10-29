"""Load VXC Motors personas into DuckDB and Parquet.

The Markdown files in company/personas/ are the source of truth. This script
parses their YAML frontmatter and body and (re)builds:

    company/data/company.duckdb   tables: departments, systems, personas,
                                  persona_systems, persona_risk_topics
    company/data/personas.parquet a flat copy of the personas table

Usage:
    python company/tools/load_personas.py [--db PATH]
"""

import argparse
import json
from pathlib import Path

import duckdb
import yaml

COMPANY = Path(__file__).resolve().parent.parent
PERSONAS = COMPANY / "personas"
DATA = COMPANY / "data"

DEPARTMENTS = [
    ("Management", "Management", "General management, P&L and the BMW relationship"),
    ("Admin", "Admin", "Reception, finance, payroll"),
    ("Sales", "Sales", "New and used car sales; orders cars from BMW"),
    ("Service", "Aftersales", "Service advisors, bookings, warranty"),
    ("Workshop", "Aftersales", "Technicians: mechanical, electrical, EV"),
    ("Parts", "Aftersales", "Parts stock; orders parts from BMW"),
]

SYSTEMS = [
    ("crm", "VXC CRM", False, "Customers, leads, test drives, follow-ups"),
    ("dms", "Dealer Management System", False, "Vehicle stock, sales deals, discounts, invoices"),
    ("workshop", "Workshop Planner", False, "Service bookings, job cards, technician time"),
    ("parts", "Parts Inventory", False, "Parts stock, bin locations, parts requests"),
    ("finance", "Finance & Payroll", False, "Ledgers, payments, commission"),
    ("mail", "Email & chat", False, "Messages between staff and to customers"),
    ("bmw_portal", "BMW Partner Portal", True, "Car orders, parts orders, warranty, recalls"),
]


def parse(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise ValueError(f"{path.name}: missing YAML frontmatter")
    _, front, body = text.split("---", 2)
    meta = yaml.safe_load(front)
    meta["profile_md"] = body.strip()
    if meta["id"] != path.stem:
        raise ValueError(f"{path.name}: id '{meta['id']}' does not match file name")
    return meta


def load_all() -> list[dict]:
    people = [parse(p) for p in sorted(PERSONAS.glob("*.md"))]
    ids = {p["id"] for p in people}
    known_systems = {s[0] for s in SYSTEMS}
    for p in people:
        if p.get("reports_to") and p["reports_to"] not in ids:
            raise ValueError(f"{p['id']}: reports_to '{p['reports_to']}' is not a persona")
        unknown = set(p.get("systems", [])) - known_systems
        if unknown:
            raise ValueError(f"{p['id']}: unknown systems {sorted(unknown)}")
    return people


def build(db_path: Path) -> None:
    people = load_all()
    DATA.mkdir(parents=True, exist_ok=True)
    db_path.unlink(missing_ok=True)
    con = duckdb.connect(str(db_path))
    con.execute("""
        CREATE TABLE departments (name VARCHAR PRIMARY KEY, business_area VARCHAR, description VARCHAR);
        CREATE TABLE systems (id VARCHAR PRIMARY KEY, name VARCHAR, external BOOLEAN, description VARCHAR);
        CREATE TABLE personas (
            id VARCHAR PRIMARY KEY, name VARCHAR, role VARCHAR, department VARCHAR,
            reports_to VARCHAR, email VARCHAR, phone_ext INTEGER, workspace VARCHAR,
            avatar VARCHAR, gender VARCHAR, age INTEGER, nationality VARCHAR,
            joined DATE, years_experience INTEGER, summary VARCHAR,
            traits VARCHAR[], communication_style VARCHAR, "values" VARCHAR,
            responsibilities VARCHAR[], kpis VARCHAR[],
            risk_level VARCHAR, risk_topics VARCHAR[], drift_scenario VARCHAR,
            frontmatter JSON, profile_md VARCHAR
        );
        CREATE TABLE persona_systems (persona_id VARCHAR, system_id VARCHAR);
        CREATE TABLE persona_risk_topics (persona_id VARCHAR, topic VARCHAR);
    """)
    con.executemany("INSERT INTO departments VALUES (?, ?, ?)", DEPARTMENTS)
    con.executemany("INSERT INTO systems VALUES (?, ?, ?, ?)", SYSTEMS)
    for p in people:
        pers = p.get("personality") or {}
        risk = p.get("risk_profile") or {}
        front = {k: v for k, v in p.items() if k != "profile_md"}
        con.execute(
            "INSERT INTO personas VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                p["id"], p["name"], p["role"], p["department"], p.get("reports_to"),
                p.get("email"), p.get("phone_ext"), p.get("workspace"), p.get("avatar"),
                p.get("gender"), p.get("age"), p.get("nationality"), p.get("joined"),
                p.get("years_experience"), p.get("summary"),
                pers.get("traits", []), pers.get("communication_style"), pers.get("values"),
                p.get("responsibilities", []), p.get("kpis", []),
                risk.get("level", "none"), risk.get("topics", []),
                (risk.get("drift_scenario") or "").strip() or None,
                json.dumps(front, default=str), p["profile_md"],
            ],
        )
        for s in p.get("systems", []):
            con.execute("INSERT INTO persona_systems VALUES (?, ?)", [p["id"], s])
        for t in risk.get("topics", []):
            con.execute("INSERT INTO persona_risk_topics VALUES (?, ?)", [p["id"], t])
    parquet = DATA / "personas.parquet"
    con.execute(f"COPY (SELECT * EXCLUDE (frontmatter) FROM personas) TO '{parquet}' (FORMAT PARQUET)")
    n = con.execute("SELECT count(*) FROM personas").fetchone()[0]
    con.close()
    print(f"loaded {n} personas into {db_path} and {parquet}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=DATA / "company.duckdb")
    build(ap.parse_args().db)
