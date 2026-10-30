"""Load the recorded sample sessions into the proxy log, so the dashboard has data without an API key.

    python3 dashboard/seed_sample.py

dashboard/sample/proxy-sample.json holds eight calls logged by proxy/proxy.py on 2026-10-27:
  support-bot  c5300e26f24a  5 turns: get_order -> get_customer -> get_shipping -> calculator -> answer
  clock-bot    69be7a2d77aa  2 turns: current_time + calculator -> answer
  support-bot  c111c24538be  1 call rejected by the provider (unknown model, HTTP 400)
Rows are appended to PROXY_LOG_DB (default logs/proxy.db) with the proxy's own schema;
sessions already in the log are skipped, so running it twice is harmless.
"""
import json
import os
import sqlite3

LOG_DB = os.environ.get("PROXY_LOG_DB", "logs/proxy.db")
SAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample", "proxy-sample.json")
COLUMNS = ("ts", "duration_ms", "agent", "session", "method", "path", "status", "model",
           "finish_reason", "usage", "error", "request", "response")
JSON_COLUMNS = ("usage", "error", "request", "response")

os.makedirs(os.path.dirname(LOG_DB) or ".", exist_ok=True)
db = sqlite3.connect(LOG_DB)
db.execute("""CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY, ts TEXT, duration_ms INTEGER, agent TEXT, session TEXT,
    method TEXT, path TEXT, status INTEGER, model TEXT, finish_reason TEXT,
    usage TEXT, error TEXT, request TEXT, response TEXT)""")
present = {r[0] for r in db.execute("SELECT DISTINCT session FROM calls")}
added = 0
with open(SAMPLE, encoding="utf-8") as f:
    for c in json.load(f):
        if c["session"] in present:
            continue
        row = [json.dumps(c[k]) if k in JSON_COLUMNS and c[k] is not None else c[k] for k in COLUMNS]
        db.execute(f"INSERT INTO calls ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})", row)
        added += 1
db.commit()
print(f"{LOG_DB}: added {added} sample calls" + (" (sample sessions already present)" if not added else ""))
