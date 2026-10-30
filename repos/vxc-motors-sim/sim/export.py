"""Snapshot a finished workday into the repo and bake it into the day timeline page (lesson 6).

    python -m sim.export                       # logs/workday -> runs/2026-10-27/ + viz/workday.html
    python -m sim.export --name 2026-10-27-day2 --title "Day 2 · firewall v2" \
        --also day1="Day 1 · firewall v1"=runs/2026-10-27
                                                  # a second run of the same day, both in the timeline page

runs/<date>/ gets everything the console, replay and the timeline need, with no secrets:
  proxy.db        the proxy's log (calls, signals, admin_actions)
  gateway.db      the gateway's answer cache, so GATEWAY_CACHE=replay can re-run the day for free
  agents/*.jsonl  each agent's own client-side log
  runner.jsonl    the director's timeline (tasks, tool calls, who mailed or chatted whom, blocks)
  summary.json    per-task outcome of the run
  systems/        end-of-day Parquet copy of both business databases (internal + BMW portal)

Every text file and database is checked for the provider key (and anything shaped like an OpenRouter
key) and redacted before it is written.
"""
import json
import os
import re
import shutil
import sqlite3
import sys

from sim.run import OUT, ROOT

KEY_RE = re.compile(r"sk-or-v1-[A-Za-z0-9]{8,}")


def redact(text):
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        text = text.replace(key, "[REDACTED]")
    return KEY_RE.sub("[REDACTED]", text)


def copy_db(src, dst):
    shutil.copy(src, dst)
    db = sqlite3.connect(dst)
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        cols = [r[1] for r in db.execute(f"PRAGMA table_info({table})") if r[2].upper() in ("TEXT", "")]
        for c in cols:
            db.execute(f"UPDATE {table} SET {c} = ? WHERE {c} LIKE '%sk-or-v1-%'", ("[REDACTED]",))
    db.commit()
    db.execute("VACUUM")
    db.close()


def snapshot(date, dest):
    os.makedirs(os.path.join(dest, "agents"), exist_ok=True)
    for name in ("proxy.db", "gateway.db"):
        if os.path.exists(os.path.join(OUT, name)):
            copy_db(os.path.join(OUT, name), os.path.join(dest, name))
    for f in sorted(os.listdir(os.path.join(OUT, "agents"))):
        with open(os.path.join(OUT, "agents", f)) as src, open(os.path.join(dest, "agents", f), "w") as dst:
            dst.write(redact(src.read()))
    for name in ("runner.jsonl", "summary.json"):
        with open(os.path.join(OUT, name)) as src, open(os.path.join(dest, name), "w") as dst:
            dst.write(redact(src.read()))
    import duckdb
    from apps.common import DATA, DB_FILES
    for db, f in DB_FILES.items():
        out = os.path.join(dest, "systems", db)
        os.makedirs(out, exist_ok=True)
        con = duckdb.connect(str(DATA / f), read_only=True)
        for (t,) in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall():
            con.execute(f"COPY {t} TO '{out}/{t}.parquet' (FORMAT parquet)")
        con.close()
    # last check: nothing in the snapshot carries a key
    for root, _, files in os.walk(dest):
        for f in files:
            with open(os.path.join(root, f), "rb") as fh:
                assert b"sk-or-v1" not in fh.read(), f"key found in {f}"


# ---------------------------------------------------------------- the timeline page's data

def timeline(dest):
    from apps.common import personas
    rows = [json.loads(line) for line in open(os.path.join(dest, "runner.jsonl"))]
    db = sqlite3.connect(os.path.join(dest, "proxy.db"))
    db.row_factory = sqlite3.Row
    sigs = [dict(r) for r in db.execute("SELECT ts, session, agent, turn, direction, level, topic, detector, rule, "
                                        "matched, excerpt, ref FROM signals ORDER BY id")]
    acts = [dict(r) for r in db.execute("SELECT ts, actor, action, session, agent, topic, reason, ref FROM admin_actions ORDER BY id")]
    calls = [dict(r) for r in db.execute("SELECT agent, session, route, upstream_model, firewall_level, duration_ms FROM calls")]
    db.close()

    tasks, by_session = {}, {}
    for r in rows:
        if r["event"] == "task_start":
            tasks[r["task"]] = {"id": r["task"], "actor": r["actor"], "title": r["title"], "kind": r["task_kind"],
                                "incident": r.get("incident"), "start": r["sim"], "goal": r.get("text", "")}
        elif r["event"] == "session_start" and r["task"] in tasks:
            tasks[r["task"]]["session"] = r["session"]
            by_session[r["session"]] = r["task"]
        elif r["event"] == "task_end" and r["task"] in tasks:
            t = tasks[r["task"]]
            t.update(end=r["sim"], status=r.get("status"), calls=r.get("calls"), tools=r.get("tools") or [],
                     answer=r.get("text", ""), firewall=r.get("firewall"))
            t.setdefault("session", r.get("session"))
            by_session[r.get("session")] = r["task"]
        elif r["event"] == "followup" and r["task"] in tasks:
            tasks[r["task"]].setdefault("followups", []).append(r["text"])
    for s in sigs:
        t = tasks.get(by_session.get(s["session"]))
        if t:
            t.setdefault("signals", []).append({k: s[k] for k in ("level", "topic", "rule", "detector", "direction", "matched", "excerpt", "ref")})
    for a in acts:
        a["task"] = by_session.get(a["session"])

    # the runner only knows who wrote to whom; the text is in the mail and chat applications
    import duckdb
    bodies = {}
    for table, key, col in (("messages", "msg_id", "body"), ("chat_messages", "chat_id", "body")):
        f = os.path.join(dest, "systems", "internal", table + ".parquet")
        if os.path.exists(f):
            bodies.update(dict(duckdb.sql(f"SELECT {key}, {col} FROM '{f}'").fetchall()))
    kinds = {"chat": "chat", "mail": "email", "external_mail": "email out", "customer_says": "customer"}
    msgs = [{"sim": r["sim"], "kind": kinds[r["event"]], "task": r.get("task"),
             "frm": r.get("frm") or r.get("customer") or r.get("actor"), "to": r.get("to") or r.get("actor"),
             "subject": r.get("subject"),
             "text": bodies.get(r.get("msg_id") or r.get("chat_id")) or r.get("text", "")}
            for r in rows if r["event"] in kinds]

    ps = personas()
    people = [{"id": pid, "name": p["name"], "role": p["role"], "department": p["department"],
               "risk": (p.get("risk_profile") or {}).get("topics", [])} for pid, p in ps.items()]
    email_to_id = {p["email"]: pid for pid, p in ps.items()}
    for m in msgs:
        m["frm"] = email_to_id.get(m["frm"], m["frm"])
        m["to"] = email_to_id.get(m["to"], m["to"])
    ext = {}
    for c in calls:
        if c["agent"] not in ps and not (c["agent"] or "").startswith(("firewall", "console-")):
            ext[c["agent"]] = ext.get(c["agent"], 0) + 1
    levels = {lv: sum(1 for s in sigs if s["level"] == lv) for lv in ("info", "warning", "block")}
    summary = json.load(open(os.path.join(dest, "summary.json")))
    stats = {"calls": len(calls), "agent_calls": summary["calls"], "sessions": len({c["session"] for c in calls}),
             "tasks": len(tasks), "minutes": summary["minutes"], "signals": levels,
             "blocked_sessions": sum(1 for a in acts if a["action"] == "block_session"),
             "firewall_intent_calls": sum(1 for c in calls if (c["agent"] or "") == "firewall"),
             "paid_calls": sum(1 for c in calls if c["route"] == "fallback"),
             "external_agents": ext, "stopped": summary.get("stopped"),
             "chats": sum(1 for m in msgs if m["kind"] == "chat"), "emails": sum(1 for m in msgs if m["kind"].startswith("email"))}
    return {"date": summary["date"], "people": people, "tasks": sorted(tasks.values(), key=lambda t: (t["start"], t["id"])),
            "messages": msgs, "admin": acts, "stats": stats}


def bake(data, template, out, days=None):
    """Put the timeline data in the page. With days ({key: {"title", "data"}}) the page gets all of them
    and a Day menu (viz/daypicker.js); `data` is then ignored."""
    html = open(template).read()
    if days:
        blob = redact(json.dumps(days, default=str)).replace("</", "<\\/")
        picker = open(os.path.join(ROOT, "viz", "daypicker.js")).read()
        html = html.replace("/*__DATA__*/null", "window.SNAPSHOT")
        html = html.replace("<script>", f"<script>window.DAYS = {blob};\n{picker}</script>\n<script>", 1)
    else:
        blob = redact(json.dumps(data, default=str)).replace("</", "<\\/")
        html = html.replace("/*__DATA__*/null", blob)
    with open(out, "w") as f:
        f.write(html)


def main():
    import argparse
    from sim.day import DATE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", default=DATE, help="folder under runs/ (default: the simulated date)")
    ap.add_argument("--title", help="this run's name in the page's Day menu")
    ap.add_argument("--also", action="append", default=[], metavar="KEY=TITLE=RUNDIR",
                    help="earlier runs to keep selectable in viz/workday.html")
    ap.add_argument("--no-snapshot", action="store_true", help="only rebuild the page from runs/<name>")
    a = ap.parse_args()
    dest = os.path.join(ROOT, "runs", a.name)
    if not a.no_snapshot:
        if os.path.isdir(dest):
            shutil.rmtree(dest)
        snapshot(DATE, dest)
    data = timeline(dest)
    days = None
    if a.also:
        days = {"latest": {"title": a.title or a.name, "data": data}}
        for spec in a.also:
            key, title, run = spec.split("=", 2)
            days[key] = {"title": title, "data": timeline(os.path.join(ROOT, run) if not os.path.isabs(run) else run)}
    bake(data, os.path.join(ROOT, "viz", "workday_template.html"), os.path.join(ROOT, "viz", "workday.html"), days)
    print(json.dumps(data["stats"], indent=1))


if __name__ == "__main__":
    main()
