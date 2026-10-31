"""Read the proxy log.   python3 proxy/view_log.py            -> list sessions
                         python3 proxy/view_log.py <session>  -> conversation, turn by turn
                         python3 proxy/view_log.py --signals  -> firewall signals and admin actions
Set PROXY_LOG_DB if the log is not at logs/proxy.db."""
import json
import os
import sqlite3
import sys

db = sqlite3.connect(os.environ.get("PROXY_LOG_DB", "logs/proxy.db"))
db.row_factory = sqlite3.Row


def short(s, n=300):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n] + "..."


if sys.argv[1:] == ["--signals"]:
    print(f"{'session':14} {'turn':>4} {'dir':8} {'level':7} {'topic':20} {'detector':16} what")
    for r in db.execute("SELECT * FROM signals ORDER BY id"):
        what = r["matched"] or r["rationale"] or ""
        print(f"{r['session'] or '-':14} {r['turn'] or 0:>4} {r['direction']:8} {r['level']:7} {r['topic']:20} "
              f"{r['detector']:16} {short(what, 70)}{'  ' + r['ref'] if r['ref'] else ''}")
    print("\nadmin actions")
    for r in db.execute("SELECT * FROM admin_actions ORDER BY id"):
        print(f"  {r['ts']}  {r['actor']:10} {r['action']:16} {r['session'] or '-':14} {r['topic'] or '-':20} "
              f"{r['ref'] or ''}  {short(r['reason'] or '', 60)}")
    sys.exit()

if len(sys.argv) < 2:
    print(f"{'session':14} {'agent':12} {'calls':>5} {'errors':>6} {'tokens':>7}  started")
    for r in db.execute("SELECT session, agent, COUNT(*) n, MIN(ts) t, "
                        "SUM(error IS NOT NULL) e FROM calls GROUP BY session, agent ORDER BY t"):
        tok = sum((json.loads(u[0]).get("total_tokens") or 0) for u in
                  db.execute("SELECT usage FROM calls WHERE session IS ? AND usage IS NOT NULL", (r["session"],)))
        print(f"{r['session'] or '-':14} {r['agent'] or '-':12} {r['n']:>5} {r['e']:>6} {tok:>7}  {r['t']}")
    sys.exit()

rows = db.execute("SELECT * FROM calls WHERE session = ? ORDER BY id", (sys.argv[1],)).fetchall()
if not rows:
    sys.exit("no such session")
first = json.loads(rows[0]["request"] or "{}")
print(f"session {sys.argv[1]}  agent={rows[0]['agent']}  model={first.get('model')}")
for m in first.get("messages", []):
    if m["role"] in ("system", "user"):
        print(f"  [{m['role']}] {short(m.get('content'))}")
for i, r in enumerate(rows, 1):
    print(f"\n--- turn {i}  {r['ts']}  {r['duration_ms']}ms  status={r['status']}  "
          f"finish={r['finish_reason']}  usage={r['usage']}")
    if r["firewall_level"] if "firewall_level" in r.keys() else None:
        print(f"  firewall: {r['firewall_level']}  route={r['route']}")
    if r["error"]:
        print(f"  ERROR: {short(r['error'])}")
        continue
    msg = json.loads(r["response"])["choices"][0]["message"]
    if msg.get("content"):
        print(f"  assistant: {short(msg['content'])}")
    for c in msg.get("tool_calls") or []:
        print(f"  tool call: {c['function']['name']}({c['function']['arguments']})")
    nxt = json.loads(rows[i]["request"]) if i < len(rows) else None
    if nxt:
        for m in nxt["messages"][-len(msg.get("tool_calls") or []):] if msg.get("tool_calls") else []:
            if m["role"] == "tool":
                print(f"  tool result: {short(m['content'])}")
