"""A small dashboard over the proxy log: who used the LLM, when, how much, and what was said.

    python3 dashboard/server.py           -> http://127.0.0.1:8091   (reads logs/proxy.db)
    python3 dashboard/server.py --demo    -> the recorded demo log, demo/data/demo.db, no setup

Reads the SQLite log that proxy/proxy.py writes (read-only, never locks the proxy out) and serves:
  /                      the dashboard page (dashboard/static/index.html)
  /api/calls             every call without its bodies (for charts and lists)
  /api/session/<id>      every call of one session, bodies decoded (for the transcript)
  /api/signals           every firewall finding (K-log-schema@2 `signals`)
  /api/actions           every block / unblock / note (K-log-schema@2 `admin_actions`)
The richer drill-down console is a separate project (llm-session-console) that reads the same file.
No dependencies beyond Python.

Configuration (environment variables):
  PROXY_LOG_DB         SQLite file to read (default: logs/proxy.db, same as the proxy)
  DASHBOARD_HOST/PORT  where to listen     (default: 127.0.0.1:8091)
"""
import json
import mimetypes
import os
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO_DB = os.path.join(os.path.dirname(HERE), "demo", "data", "demo.db")
LOG_DB = DEMO_DB if "--demo" in sys.argv[1:] else os.environ.get("PROXY_LOG_DB", "logs/proxy.db")
HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("DASHBOARD_PORT", "8091"))
STATIC = os.path.join(HERE, "static")
LIGHT = ("id", "ts", "duration_ms", "agent", "session", "user", "dept", "key_id", "status", "model",
         "finish_reason", "prompt_tokens", "completion_tokens", "total_tokens", "route", "cost_usd", "labels",
         "error", "firewall_level")
JSON_COLUMNS = ("usage", "error", "request", "response", "labels")


def _json(text):
    try:
        return json.loads(text) if text else None
    except ValueError:
        return text  # e.g. a non-JSON provider error body: show it as it was logged


def query(sql, args=()):
    """Rows as dicts with the JSON columns decoded; [] if there is no log yet."""
    if not os.path.exists(LOG_DB):
        return []
    db = sqlite3.connect(f"file:{LOG_DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        rows = db.execute(sql, args).fetchall()
    except sqlite3.OperationalError:  # file exists but the proxy has not created the table yet
        return []
    finally:
        db.close()
    return [{k: _json(r[k]) if k in JSON_COLUMNS else r[k] for k in r.keys()} for r in rows]


def columns():
    rows = query("SELECT name FROM pragma_table_info('calls')")
    return {r["name"] for r in rows}


def load_calls():
    have = columns()
    cols = ", ".join(f'"{c}"' if c in have else f'NULL AS "{c}"' for c in LIGHT)
    return query(f"SELECT {cols} FROM calls ORDER BY ts, id")


def load_session(session):
    return query("SELECT * FROM calls WHERE session = ? ORDER BY id", (session,))


ROUTES = {"/api/calls": lambda rest: load_calls(), "/api/session/": load_session,
          "/api/signals": lambda rest: query("SELECT * FROM signals ORDER BY id"),
          "/api/actions": lambda rest: query("SELECT * FROM admin_actions ORDER BY id")}


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, ctype):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        for prefix, fn in ROUTES.items():
            if url.path == prefix or (prefix.endswith("/") and url.path.startswith(prefix)):
                data = fn(unquote(url.path[len(prefix):]))
                return self._send(200, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")
        name = "index.html" if url.path in ("", "/") else url.path.lstrip("/")
        path = os.path.realpath(os.path.join(STATIC, name))
        if not path.startswith(STATIC + os.sep) or not os.path.isfile(path):
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    if not os.path.exists(LOG_DB):
        print(f"note: {LOG_DB} does not exist yet. Run the demo (python3 demo/run.py --offline) or load the "
              "recorded one (python3 demo/recording.py load)", file=sys.stderr)
    else:
        print(f"reading {LOG_DB}: {len(load_calls())} logged calls", flush=True)
    print(f"dashboard on http://{HOST}:{PORT}/", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
