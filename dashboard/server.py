"""Session Inspector dashboard: six visual boards over the proxy log.

    python3 dashboard/server.py        -> http://127.0.0.1:8091

Reads the SQLite log that proxy/proxy.py writes (read-only) and serves it as JSON at
/api/calls, next to the board pages in dashboard/static/. No dependencies beyond Python.

Configuration (environment variables):
  PROXY_LOG_DB        SQLite file to read      (default: logs/proxy.db, same as the proxy)
  DASHBOARD_HOST/PORT where to listen          (default: 127.0.0.1:8091)
"""
import json
import mimetypes
import os
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

LOG_DB = os.environ.get("PROXY_LOG_DB", "logs/proxy.db")
HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("DASHBOARD_PORT", "8091"))
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
JSON_COLUMNS = ("usage", "error", "request", "response")


def _json(text):
    try:
        return json.loads(text) if text else None
    except ValueError:
        return text  # e.g. a non-JSON provider error body: show it as it was logged


def load_calls(session=None):
    """Every logged call, oldest first, with the JSON columns decoded."""
    if not os.path.exists(LOG_DB):
        return []
    db = sqlite3.connect(f"file:{LOG_DB}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        sql, args = "SELECT * FROM calls", ()
        if session:
            sql, args = sql + " WHERE session = ?", (session,)
        rows = db.execute(sql + " ORDER BY id", args).fetchall()
    except sqlite3.OperationalError:  # file exists but the proxy has not created the table yet
        return []
    finally:
        db.close()
    calls = []
    for r in rows:
        c = dict(r)
        for k in JSON_COLUMNS:
            c[k] = _json(c[k])
        calls.append(c)
    return calls


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
        if url.path == "/api/calls":
            session = (parse_qs(url.query).get("session") or [None])[0]
            body = json.dumps(load_calls(session), ensure_ascii=False).encode()
            return self._send(200, body, "application/json; charset=utf-8")
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
        print(f"note: {LOG_DB} does not exist yet. Log some runs through the proxy "
              "(PROXY_LOGGING=on) or load the sample: python3 dashboard/seed_sample.py", file=sys.stderr)
    else:
        n = len(load_calls())
        print(f"reading {LOG_DB}: {n} logged calls", flush=True)
    print(f"dashboard on http://{HOST}:{PORT}/", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
