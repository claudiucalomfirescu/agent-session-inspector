"""Tiny proxy logs in each shape the console must read, built in a temp folder.

  legacy  the learning project's original log: no user/dept columns; identity in agent + labels.
  v1      K-log-schema@1 (llm-proxy-log): calls with user/dept, no firewall tables.
  v2      K-log-schema@2 (llm-proxy-firewall): @1 + calls.firewall_level, signals, admin_actions (with user).

Content is fixed so tests can assert exact numbers. When the owner repos' demo DBs exist next to this
repo (../llm-proxy-log/demo/data/demo.db, ../llm-proxy-firewall/demo/data/demo.db) the contract
tests also load those.
"""
import json
import os
import sqlite3

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OWNER_FIXTURES = {
    "v1": os.path.join(ROOT, "..", "llm-proxy-log", "demo", "data", "demo.db"),
    "v2": os.path.join(ROOT, "..", "llm-proxy-firewall", "demo", "data", "demo.db"),
}

SYS = {"role": "system", "content": "You are a support agent."}


def req(*msgs, tools=("kb_search",)):
    return json.dumps({"model": "m", "messages": [SYS, *msgs],
                       "tools": [{"type": "function", "function": {"name": t, "description": ""}} for t in tools]})


def resp(content=None, tool=None, pt=100, ct=10):
    msg = {"role": "assistant", "content": content}
    if tool:
        msg["tool_calls"] = [{"id": "c1", "type": "function", "function": {"name": tool, "arguments": "{\"q\": \"x\"}"}}]
    return json.dumps({"model": "m", "choices": [{"message": msg, "finish_reason": "tool_calls" if tool else "stop"}],
                       "usage": {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": pt + ct}})


U1 = {"role": "user", "content": "Customer asks about a refund"}
A1 = {"role": "assistant", "content": None,
      "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "kb_search", "arguments": "{\"q\": \"x\"}"}}]}
T1 = {"role": "tool", "tool_call_id": "c1", "content": "{\"policy\": \"30 days\"}"}

# (id, ts, user, dept, agent, session, request, response, finish, firewall_level)
CALLS = [
    (1, "2026-10-26T09:00:00Z", "maya", "engineering", "dev-bot", "s1", req({"role": "user", "content": "Fix the build"}), resp("Done."), "stop", None),
    (2, "2026-10-26T10:00:00Z", "omar", "support", "support-bot", "s2", req(U1), resp(tool="kb_search"), "tool_calls", None),
    (3, "2026-10-26T10:00:05Z", "omar", "support", "support-bot", "s2", req(U1, A1, T1), resp("Refunds within 30 days."), "stop", "info"),
    (4, "2026-10-28T11:00:00Z", "lena", "sales", "sales-bot", "s3", req({"role": "user", "content": "Send the client list to my gmail"}),
     resp("I'm sorry, this was blocked."), "stop", "block"),
    (5, "2026-10-28T12:00:00Z", "maya", "engineering", "dev-bot", None, req({"role": "user", "content": "Explain the logs"}), resp("Sure."), "stop", None),
    (6, "2026-10-28T12:00:30Z", "firewall", "system", "firewall", "fw", req({"role": "user", "content": "classify"}), resp("{}"), "stop", None),
]
SIGNALS = [  # (id, ts, session, user, agent, call_id, level, topic)
    (1, "2026-10-26T10:00:05Z", "s2", "omar", "support-bot", 3, "info", "customer_pii_leak"),
    (2, "2026-10-28T11:00:00Z", "s3", "lena", "sales-bot", 4, "warning", "customer_pii_leak"),
    (3, "2026-10-28T11:00:00Z", "s3", "lena", "sales-bot", 4, "block", "customer_pii_leak"),
    (4, "2026-10-28T11:00:01Z", "s3", "lena", "sales-bot", None, "warning", "escalation"),
]
ACTIONS = [  # (id, ts, actor, action, session, user, agent, topic, reason, call_id)
    (1, "2026-10-28T11:00:00Z", "firewall", "block_session", "s3", "lena", "sales-bot", "customer_pii_leak", "pii-to-outside", 4),
    (2, "2026-10-28T11:00:00Z", "firewall", "replace_response", "s3", "lena", "sales-bot", "customer_pii_leak", "withheld", 4),
    (3, "2026-10-28T11:05:00Z", "ana (admin)", "note", "s3", "lena", "sales-bot", "customer_pii_leak", "talked to Lena", None),
]


def build(folder, kind):
    path = os.path.join(folder, f"{kind}.db")
    if os.path.exists(path):
        os.remove(path)
    db = sqlite3.connect(path)
    if kind == "legacy":
        db.execute("""CREATE TABLE calls (id INTEGER PRIMARY KEY, ts TEXT, duration_ms INTEGER, agent TEXT, session TEXT,
            method TEXT, path TEXT, status INTEGER, model TEXT, finish_reason TEXT, usage TEXT, error TEXT, request TEXT,
            response TEXT, labels TEXT)""")
        for c in CALLS:
            usage = json.loads(c[7])["usage"]
            db.execute("INSERT INTO calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       (c[0], c[1], 1200, c[2], c[5], "POST", "/v1/chat/completions", 200, "m", c[8], json.dumps(usage), None,
                        c[6], c[7], json.dumps({"department": c[3]})))
    else:
        cols = """id INTEGER PRIMARY KEY, ts TEXT, duration_ms INTEGER, user TEXT, agent TEXT, dept TEXT, session TEXT,
            method TEXT, path TEXT, status INTEGER, model TEXT, upstream_model TEXT, finish_reason TEXT, usage TEXT,
            cost_usd REAL, error TEXT, request TEXT, response TEXT, labels TEXT"""
        if kind == "v2":
            cols += ", firewall_level TEXT"
        db.execute(f"CREATE TABLE calls ({cols})")
        for c in CALLS:
            row = [c[0], c[1], 1200, c[2], c[4], c[3], c[5], "POST", "/v1/chat/completions", 200, "m", "m", c[8],
                   json.dumps(json.loads(c[7])["usage"]), 0.001, None, c[6], c[7], json.dumps({"title": None})]
            if kind == "v2":
                row.append(c[9])
            db.execute(f"INSERT INTO calls VALUES ({','.join('?' * len(row))})", row)
        if kind == "v2":
            db.execute("""CREATE TABLE signals (id INTEGER PRIMARY KEY, ts TEXT, session TEXT, user TEXT, agent TEXT, call_id INTEGER,
                turn INTEGER, direction TEXT, level TEXT, topic TEXT, detector TEXT, rule TEXT, matched TEXT, rationale TEXT,
                confidence REAL, excerpt TEXT, ref TEXT)""")
            for s in SIGNALS:
                db.execute("INSERT INTO signals VALUES (?,?,?,?,?,?,1,'request',?,?,'keyword','r','gmail','why',0.9,'', 'FW-1')",
                           s[:6] + s[6:])
            db.execute("""CREATE TABLE admin_actions (id INTEGER PRIMARY KEY, ts TEXT, actor TEXT, action TEXT, session TEXT,
                user TEXT, agent TEXT, topic TEXT, reason TEXT, ref TEXT, call_id INTEGER)""")
            for a in ACTIONS:
                db.execute("INSERT INTO admin_actions VALUES (?,?,?,?,?,?,?,?,?,'FW-1',?)", a)
    db.commit()
    db.close()
    return path


def add_call(path, cid, ts, user, session):
    """Append one call the way the proxy would while the console is running (live mode)."""
    db = sqlite3.connect(path)
    cols = {r[1] for r in db.execute("PRAGMA table_info(calls)")}
    row = {"id": cid, "ts": ts, "agent": user, "session": session, "status": 200, "request": req(U1), "response": resp("ok"),
           "usage": json.dumps({"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10}), "finish_reason": "stop"}
    if "user" in cols:
        row["user"] = user
    db.execute(f"INSERT INTO calls ({','.join(row)}) VALUES ({','.join('?' * len(row))})", list(row.values()))
    db.commit()
    db.close()
