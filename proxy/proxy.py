"""Steps 2-3: proxy between the agent and OpenRouter. Pass-through by default; optional logging.

The agent only changes its base URL (and may send a dummy key); this process alone holds the real key.

Configuration (environment variables):
  OPENROUTER_API_KEY  real provider key       (required)
  UPSTREAM_BASE_URL   provider API root       (default: https://openrouter.ai/api/v1)
  PROXY_HOST/PORT     where to listen         (default: 127.0.0.1:8080)
  PROXY_LOGGING       on|off                  (default: off = pure pass-through, nothing recorded)
  PROXY_LOG_DB        SQLite file for the log (default: logs/proxy.db)
The agent names itself with X-Agent-Id / X-Session-Id headers; the proxy removes them before forwarding.
Point the agent at http://127.0.0.1:8080/v1
"""
import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ.get("UPSTREAM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
REAL_KEY = os.environ.get("OPENROUTER_API_KEY")
HOST = os.environ.get("PROXY_HOST", "127.0.0.1")
PORT = int(os.environ.get("PROXY_PORT", "8080"))
LOGGING = os.environ.get("PROXY_LOGGING", "off").lower() in ("on", "1", "true", "yes")
LOG_DB = os.environ.get("PROXY_LOG_DB", "logs/proxy.db")
_db_lock = threading.Lock()
_db = None

# Headers that describe one hop only, or that the agent's own key/transport must not leak upstream.
SKIP_REQUEST = {"host", "authorization", "content-length", "connection", "accept-encoding", "transfer-encoding", "x-agent-id", "x-session-id"}
SKIP_RESPONSE = {"content-length", "content-encoding", "transfer-encoding", "connection"}


def _redact(text):
    """Keep secrets out of the log: the real key, and any bearer token that shows up in a body."""
    if REAL_KEY:
        text = text.replace(REAL_KEY, "[REDACTED]")
    return re.sub(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}", "Bearer [REDACTED]", text)


def _text(raw):
    return _redact(raw.decode("utf-8", "replace")) if raw else ""


def _json(text):
    try:
        return json.loads(text)
    except ValueError:
        return None


def log_call(started, duration_ms, agent, session, method, path, status, req_raw, resp_raw):
    """Write one row. Never raises: a logging failure must not touch the agent's reply."""
    global _db
    try:
        req_text, resp_text = _text(req_raw), _text(resp_raw)
        req, resp = _json(req_text) or {}, _json(resp_text) or {}
        choice = (resp.get("choices") or [{}])[0] if isinstance(resp, dict) else {}
        error = resp.get("error") if isinstance(resp, dict) else None
        if status >= 400 and not error:
            error = {"code": status, "message": resp_text[:500]}
        with _db_lock:
            if _db is None:
                os.makedirs(os.path.dirname(LOG_DB) or ".", exist_ok=True)
                _db = sqlite3.connect(LOG_DB, check_same_thread=False)
                _db.execute("""CREATE TABLE IF NOT EXISTS calls (
                    id INTEGER PRIMARY KEY, ts TEXT, duration_ms INTEGER, agent TEXT, session TEXT,
                    method TEXT, path TEXT, status INTEGER, model TEXT, finish_reason TEXT,
                    usage TEXT, error TEXT, request TEXT, response TEXT)""")
            _db.execute("INSERT INTO calls VALUES (NULL,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(started)) + "Z", duration_ms,
                agent, session, method, path, status, req.get("model") if isinstance(req, dict) else None,
                choice.get("finish_reason"), json.dumps(resp.get("usage")) if isinstance(resp, dict) and resp.get("usage") else None,
                json.dumps(error) if error else None, req_text, resp_text))
            _db.commit()
    except Exception as e:  # noqa: BLE001
        print(f"log write failed: {type(e).__name__}", file=sys.stderr, flush=True)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _forward(self):
        path = self.path[3:] if self.path.startswith("/v1") else self.path
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        headers = {k: v for k, v in self.headers.items() if k.lower() not in SKIP_REQUEST}
        headers["Authorization"] = f"Bearer {REAL_KEY}"
        started = time.time()
        req = urllib.request.Request(UPSTREAM + path, data=body or None, headers=headers, method=self.command)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                status, resp_headers, data = r.status, r.getheaders(), r.read()
        except urllib.error.HTTPError as e:  # provider errors are passed back as they are
            status, resp_headers, data = e.code, e.headers.items(), e.read()
        except OSError as e:
            data = ('{"error": {"code": 502, "message": "proxy could not reach provider: %s"}}'
                    % type(e).__name__).encode()
            status, resp_headers = 502, [("Content-Type", "application/json")]
        if LOGGING:
            log_call(started, int((time.time() - started) * 1000), self.headers.get("X-Agent-Id"),
                     self.headers.get("X-Session-Id"), self.command, self.path, status, body, data)
        self.send_response(status)
        for k, v in resp_headers:
            if k.lower() not in SKIP_RESPONSE:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = _forward

    def log_message(self, *args):  # pass-through mode logs nothing
        pass


if __name__ == "__main__":
    if not REAL_KEY:
        sys.exit("Set OPENROUTER_API_KEY for the proxy.")
    print(f"proxy listening on http://{HOST}:{PORT}/v1 -> {UPSTREAM}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
