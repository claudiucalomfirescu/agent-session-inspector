"""Read the proxy log.   python3 proxy/view_log.py            -> list sessions
                         python3 proxy/view_log.py <session>  -> conversation, turn by turn
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


if len(sys.argv) < 2:
    print(f"{'session':18} {'user':10} {'agent':16} {'calls':>5} {'errors':>6} {'tokens':>7}  started")
    for r in db.execute("SELECT session, user, agent, COUNT(*) n, MIN(ts) t, SUM(error IS NOT NULL) e, "
                        "SUM(total_tokens) tok FROM calls GROUP BY session ORDER BY t"):
        print(f"{r['session'] or '-':18} {r['user'] or '-':10} {r['agent'] or '-':16} {r['n']:>5} {r['e']:>6} "
              f"{r['tok'] or 0:>7}  {r['t']}")
    sys.exit()

rows = db.execute("SELECT * FROM calls WHERE session = ? ORDER BY id", (sys.argv[1],)).fetchall()
if not rows:
    sys.exit("no such session")
first = json.loads(rows[0]["request"] or "{}")
print(f"session {sys.argv[1]}  user={rows[0]['user']}  agent={rows[0]['agent']}  model={first.get('model')}")
for m in first.get("messages", []):
    if m["role"] in ("system", "user"):
        print(f"  [{m['role']}] {short(m.get('content'))}")
for i, r in enumerate(rows, 1):
    print(f"\n--- turn {i}  {r['ts']}  {r['duration_ms']}ms  status={r['status']}  "
          f"finish={r['finish_reason']}  usage={r['usage']}")
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
