"""The enterprise applications as small HTTP services. Agents reach them ONLY through these endpoints.

    python -m apps.server                 # both services in one process (what the simulation starts)
    python -m apps.server internal        # VXC internal apps: CRM, DMS, Workshop, Parts, Finance, Mail, Chat  :8100
    python -m apps.server bmw_portal      # the external BMW Partner Portal                                    :8200

Endpoints (JSON):
    GET  /health
    GET  /apps                            the applications this service hosts and their tools
    GET  /tools?actor=<id>                tool specs (OpenAI format) that actor may use here
    POST /call  {"actor", "tool", "args"} run one tool as that actor -> result, or {"error": ...}
    GET  /events?mail_after=N&chat_after=M
                                          (internal only) new emails and chat messages since those
                                          sequence numbers: who sent what to whom, never the text.
                                          The simulation uses it as the "new message" notification.
    POST /clock {"now": "2026-10-27T09:10:00"}
                                          set the simulated time (the simulation owns the clock)
    GET  /sim/customer?fuel=diesel&pick=7 (internal only, simulation director) a real CRM customer with a
                                          car, so a simulated caller is someone the staff can find

An actor is a staff persona id (tom-becker) or an outside party "ext:<email>" (customers, BMW staff),
who may only use the mail tools. There is no real authentication: local, simulated systems.
Each service owns one DuckDB file (one writer process per file), and every call is written to its
audit table (audit_log / portal_access_log).
"""
import argparse
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from apps import tools  # noqa: F401  (registers the tools)
from apps.common import EXTERNAL_TOOLS, REGISTRY, SYSTEM_DB, Store, call_json, profile

def _port(env, default):
    return urlparse(os.environ[env]).port if os.environ.get(env) else default


# The same variables tell agents where to call (agents/toolclient.py) and services where to listen.
PORTS = {"internal": _port("VXC_INTERNAL_URL", 8100), "bmw_portal": _port("VXC_PORTAL_URL", 8200)}

APP_NAMES = {"crm": "VXC CRM", "dms": "Dealer Management System", "workshop": "Workshop Planner",
             "parts": "Parts Inventory", "finance": "Finance & Payroll", "mail": "Email", "chat": "Team chat",
             "bmw_portal": "BMW Partner Portal"}


def tools_for(service, actor):
    p = profile(actor)
    if not p:
        return None
    return [t.spec() for t in REGISTRY.values()
            if SYSTEM_DB[t.system] == service and t.system in p.get("systems", [])
            and (not p.get("external") or t.name in EXTERNAL_TOOLS)]


def events(mail_after=0, chat_after=0):
    """New mail and chat deliveries after the given sequence numbers (the numeric part of the ids)."""
    st = Store.get("internal")
    with st.lock:
        cur = st.con.cursor()
        mail = cur.execute(
            "SELECT CAST(substr(msg_id, 5) AS INTEGER) AS seq, msg_id, from_addr, to_addr, cc, subject, sent_at, "
            "(SELECT first_name || ' ' || last_name FROM customers c WHERE c.email = m.to_addr LIMIT 1) "
            "FROM messages m WHERE msg_id LIKE 'MSG-%' AND CAST(substr(msg_id, 5) AS INTEGER) > ? ORDER BY seq",
            [int(mail_after)]).fetchall()
        chat = cur.execute(
            "SELECT CAST(substr(chat_id, 4) AS INTEGER) AS seq, chat_id, from_staff, to_staff, sent_at "
            "FROM chat_messages WHERE CAST(substr(chat_id, 4) AS INTEGER) > ? ORDER BY seq",
            [int(chat_after)]).fetchall()
        cur.close()
    return {"mail": [{"seq": r[0], "msg_id": r[1], "from": r[2], "to": r[3], "cc": r[4], "subject": r[5],
                      "sent_at": str(r[6]), "to_customer": r[7]} for r in mail],
            "chat": [{"seq": r[0], "chat_id": r[1], "from": r[2], "to": r[3], "sent_at": str(r[4])} for r in chat]}


def sim_customer(fuel=None, pick=7):
    """A real customer with a car from the CRM (deterministic pick), for the simulation director."""
    st = Store.get("internal")
    with st.lock:
        rows = st.con.cursor().execute(
            "SELECT c.customer_id, c.first_name, c.last_name, c.email, v.vin, v.model, v.reg "
            "FROM customers c JOIN customer_vehicles v USING (customer_id) "
            "WHERE (? IS NULL OR v.fuel = ?) ORDER BY c.customer_id", [fuel, fuel]).fetchall()
    rows = rows[int(pick)::13] or rows
    if not rows:
        return None
    r = rows[0]
    return {"customer_id": r[0], "name": f"{r[1]} {r[2]}", "email": r[3], "vin": r[4], "car": f"{r[5]} ({r[6]})"}


def make_handler(service):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code, payload):
            body = (payload if isinstance(payload, str) else json.dumps(payload, default=str)).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/health":
                return self._send(200, {"ok": True, "service": service})
            if u.path == "/apps":
                apps = {}
                for t in REGISTRY.values():
                    if SYSTEM_DB[t.system] == service:
                        apps.setdefault(t.system, {"name": APP_NAMES[t.system], "tools": []})["tools"].append(t.name)
                return self._send(200, apps)
            if u.path == "/tools":
                actor = (q.get("actor") or [""])[0]
                specs = tools_for(service, actor)
                if specs is None:
                    return self._send(404, {"error": f"unknown actor {actor}"})
                return self._send(200, specs)
            if u.path == "/sim/customer" and service == "internal":
                return self._send(200, sim_customer((q.get("fuel") or [None])[0], (q.get("pick") or [7])[0]))
            if u.path == "/events" and service == "internal":
                return self._send(200, events((q.get("mail_after") or [0])[0], (q.get("chat_after") or [0])[0]))
            self._send(404, {"error": "not found"})

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "body must be JSON"})
            if path == "/clock":
                os.environ["VXC_NOW"] = str(req["now"])
                return self._send(200, {"now": os.environ["VXC_NOW"]})
            if path != "/call":
                return self._send(404, {"error": "not found"})
            name = req.get("tool", "")
            if name not in REGISTRY or SYSTEM_DB[REGISTRY[name].system] != service:
                return self._send(404, {"error": f"tool {name} is not served by {service}"})
            self._send(200, call_json(req.get("actor", ""), name, req.get("args") or {}))

        def log_message(self, fmt, *args):
            pass

    return Handler


def serve(service, host="127.0.0.1", port=None):
    """Start one service in a background thread; returns the server (call .shutdown() to stop)."""
    Store.get(service)   # open (and seed if needed) before taking requests
    srv = ThreadingHTTPServer((host, port or PORTS[service]), make_handler(service))
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True, name=f"apps-{service}").start()
    return srv


def main():
    ap = argparse.ArgumentParser(description="Serve the VXC Motors applications over HTTP")
    ap.add_argument("service", nargs="?", choices=list(PORTS) + ["all"], default="all")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, help="only with a single service")
    a = ap.parse_args()
    services = list(PORTS) if a.service == "all" else [a.service]
    # Seeding writes both databases, so a fresh start must seed before the services open their files.
    from apps.common import DATA, DB_FILES
    if not all((DATA / f).exists() for f in DB_FILES.values()):
        from apps import seed
        seed.build(parquet=False)
    servers = [serve(s, a.host, a.port if len(services) == 1 else None) for s in services]
    for s, srv in zip(services, servers):
        print(f"{s:<10} http://{a.host}:{srv.server_address[1]}", flush=True)
    threading.Event().wait()


if __name__ == "__main__":
    main()
