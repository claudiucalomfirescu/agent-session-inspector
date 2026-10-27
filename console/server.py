"""Lesson 7: the admin console, served live over the proxy log.

    python3 console/server.py                  # reads logs/proxy.db, http://127.0.0.1:8090/
    python3 console/server.py --demo           # reads logs/demo.db (seeded by console/seed_demo.py if missing)
    python3 console/server.py --db path.db --port 8090

Pages:   /            admin console (company -> department -> person -> session -> conversation)
         /mission     mission control (live flow of agent traffic, replay with speed control)
API:     GET  /api/snapshot                     the whole model (see console/model.py), rebuilt when the log changes
         GET  /api/live?call=N&signal=N&action=N   rows newer than those ids, for live views
         POST /api/sessions/<session>/block|unblock|note   {"actor": "...", "reason": "..."}

Admin actions go to the proxy's firewall endpoint (PROXY_ADMIN_URL, default http://127.0.0.1:8080/v1/firewall),
which enforces them. If the proxy is not running they are written straight into admin_actions, and the
proxy applies them the next time it reads that table. The console never talks to the LLM provider.
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import model  # noqa: E402

PROXY_ADMIN_URL = os.environ.get("PROXY_ADMIN_URL", "http://127.0.0.1:8080/v1/firewall").rstrip("/")
ADMIN_TOKEN = os.environ.get("FIREWALL_ADMIN_TOKEN")
# The pages are written as artifact bodies (the artifact host adds the document skeleton); served locally they get this one.
SKELETON = (b'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            b'<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"></head>')
ACTIONS = {"block": "block_session", "unblock": "unblock_session", "note": "note"}


class Snapshot:
    """The model, rebuilt only when the log's fingerprint changes."""

    def __init__(self, path):
        self.path, self.version, self.data, self.body = path, None, None, None
        self.lock = threading.Lock()

    def get(self):
        with self.lock:
            v = model.log_version(self.path)
            if self.data is None or v != self.version:
                self.data = model.build(self.path)
                self.body = json.dumps(self.data, separators=(",", ":")).encode()
                self.version = v
            return self.data, self.body


def record_locally(path, session, action, actor, reason):
    """Proxy is down: write the action where the firewall reads it."""
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE IF NOT EXISTS admin_actions (
        id INTEGER PRIMARY KEY, ts TEXT, actor TEXT, action TEXT, session TEXT, agent TEXT, topic TEXT,
        reason TEXT, ref TEXT, call_id INTEGER)""")
    row = db.execute("SELECT agent FROM calls WHERE session = ? ORDER BY id DESC LIMIT 1", (session,)).fetchone()
    db.execute("INSERT INTO admin_actions (ts, actor, action, session, agent, reason) VALUES (?,?,?,?,?,?)",
               (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), actor, action, session, row[0] if row else None, reason))
    db.commit()
    db.close()


def make_handler(snap):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, status, body, ctype="application/json"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path, _, query = self.path.partition("?")
            params = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
            if path in ("/", "/console", "/mission"):
                name = "mission.html" if path == "/mission" else "console.html"
                with open(os.path.join(HERE, "web", name), "rb") as f:
                    return self._send(200, SKELETON + f.read(), "text/html; charset=utf-8")
            if path == "/api/snapshot":
                return self._send(200, snap.get()[1])
            if path == "/api/live":
                data, _ = snap.get()

                def after(rows, key):
                    n = int(params.get(key, 0) or 0)
                    return [r for r in rows if (r.get("id") or 0) > n]
                sessions = {s["id"]: s for s in data["sessions"]}
                calls = after(data["calls"], "call")
                return self._send(200, json.dumps({
                    "calls": calls, "signals": after(data["signals"], "signal"), "actions": after(data["actions"], "action"),
                    "sessions": [sessions[c] for c in {c["session"] for c in calls} if c in sessions],
                    "totals": data["totals"]}).encode())
            self._send(404, b'{"error": "not found"}')

        def do_POST(self):
            parts = self.path.strip("/").split("/")
            if len(parts) != 4 or parts[:2] != ["api", "sessions"] or parts[3] not in ACTIONS:
                return self._send(404, b'{"error": "not found"}')
            session, verb = parts[2], parts[3]
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            except ValueError:
                return self._send(400, b'{"error": "body must be JSON"}')
            actor, reason = (body.get("actor") or "admin")[:80], (body.get("reason") or "")[:1000]
            headers = {"Content-Type": "application/json"}
            if ADMIN_TOKEN:
                headers["X-Admin-Token"] = ADMIN_TOKEN
            req = urllib.request.Request(f"{PROXY_ADMIN_URL}/sessions/{session}/{verb}", method="POST", headers=headers,
                                         data=json.dumps({"actor": actor, "reason": reason}).encode())
            try:
                with urllib.request.urlopen(req, timeout=10) as r:
                    return self._send(200, json.dumps({"ok": True, "via": "proxy", "proxy": json.loads(r.read() or b"{}")}).encode())
            except urllib.error.HTTPError as e:
                if e.code != 404:  # the proxy answered and refused (bad token, unknown session): say so
                    return self._send(e.code, json.dumps({"ok": False, "via": "proxy", "error": e.read().decode()[:300]}).encode())
            except (OSError, ValueError):
                pass
            record_locally(snap.path, session, ACTIONS[verb], actor, reason)
            self._send(200, json.dumps({"ok": True, "via": "log",
                                        "note": "proxy firewall not reachable; recorded in admin_actions"}).encode())

        def log_message(self, *args):
            pass

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.environ.get("PROXY_LOG_DB", os.path.join(model.ROOT, "logs", "proxy.db")))
    ap.add_argument("--demo", action="store_true", help="use logs/demo.db, seeding it if missing")
    ap.add_argument("--host", default=os.environ.get("CONSOLE_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("CONSOLE_PORT", "8090")))
    args = ap.parse_args()
    if args.demo:
        args.db = os.path.join(model.ROOT, "logs", "demo.db")
        if not os.path.exists(args.db):
            subprocess.run([sys.executable, os.path.join(HERE, "seed_demo.py"), "--out", args.db], check=True)
    if not os.path.exists(args.db):
        sys.exit(f"{args.db} not found. Run the proxy with PROXY_LOGGING=on first, or use --demo.")
    snap = Snapshot(args.db)
    print(f"console on http://{args.host}:{args.port}/  ·  mission control on /mission  ·  log {args.db}", flush=True)
    ThreadingHTTPServer((args.host, args.port), make_handler(snap)).serve_forever()


if __name__ == "__main__":
    main()
