"""Shared test fixtures: a recording fake upstream, and the proxy / dashboard started as real processes.

The tests are black-box on purpose (HTTP in, HTTP and SQLite out): they prove the contracts in SPEC.md,
so a rebuild in another language can keep them."""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_KEY = "sk-real-provider-key-0123456789"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Upstream(BaseHTTPRequestHandler):
    """Records what reached the provider; answers with a fixed completion, or a scripted error."""
    seen = []          # (method, path, headers dict, body)
    script = []        # (status, body) to answer next, instead of the normal answer

    def _send(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        Upstream.seen.append(("POST", self.path, dict(self.headers.items()), body))
        if Upstream.script:
            return self._send(*Upstream.script.pop(0))
        req = json.loads(body)
        self._send(200, {"id": "gen-1", "object": "chat.completion", "model": req.get("model"),
                         "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14}})

    def do_GET(self):
        Upstream.seen.append(("GET", self.path, dict(self.headers.items()), b""))
        if self.path.endswith("/key"):
            return self._send(200, {"data": {"usage": 0, "free_model_daily_requests": {"used": 0, "limit": 1000, "remaining": 1000}}})
        self._send(200, {"data": [{"id": "fake-model"}]})

    def log_message(self, *a):
        pass


def start_upstream():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}/v1"


def wait_http(url, proc, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except urllib.error.HTTPError:
            return
        except OSError:
            if proc.poll() is not None:
                raise RuntimeError(f"process exited: {proc.args}")
            time.sleep(0.05)
    raise RuntimeError(f"{url} did not come up")


def start_proxy(upstream_url, db, **env):
    port = free_port()
    e = {**os.environ, "OPENROUTER_API_KEY": REAL_KEY, "UPSTREAM_BASE_URL": upstream_url, "PROXY_PORT": str(port),
         "PROXY_LOG_DB": db, "PROXY_LOGGING": "on", "GATEWAY_DB": db + ".gateway", "GATEWAY_BACKOFF_S": "0.01",
         "GATEWAY_KEY_REFRESH_S": "0", **{k: str(v) for k, v in env.items()}}
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "proxy", "proxy.py")], env=e,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    wait_http(f"http://127.0.0.1:{port}/healthz", proc)
    return proc, f"http://127.0.0.1:{port}/v1"


def start_dashboard(db):
    port = free_port()
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "dashboard", "server.py")],
                            env={**os.environ, "PROXY_LOG_DB": db, "DASHBOARD_PORT": str(port)},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    wait_http(f"http://127.0.0.1:{port}/", proc)
    return proc, f"http://127.0.0.1:{port}"


def post(url, body, headers=None):
    data = json.dumps(body).encode() if not isinstance(body, bytes) else body
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, dict(r.headers.items()), json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers.items()), json.loads(e.read() or b"null")


def get_json(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


def rows(db, sql="SELECT * FROM calls ORDER BY id", args=()):
    if not os.path.exists(db):
        return []
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, args)]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def chat_body(content="ping", model="test-model", **extra):
    return {"model": model, "messages": [{"role": "user", "content": content}], **extra}
