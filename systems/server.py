"""Serve the systems over HTTP so several agent processes can share them.

    python -m systems.server internal     # CRM, DMS, workshop, parts, finance, mail  on :8100
    python -m systems.server bmw_portal   # the external BMW Partner Portal          on :8200

Endpoints (JSON):
    GET  /health
    GET  /tools?actor=<persona id>        tool specs that persona may use on this service
    POST /call  {"actor", "tool", "args"} run one tool as that persona -> result or {"error": ...}

There is no real authentication: the caller names itself with "actor" (mock systems, local only).
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from systems import tools  # noqa: F401  (registers the tools)
from systems.common import REGISTRY, SYSTEM_DB, Store, call_json, personas

PORTS = {"internal": 8100, "bmw_portal": 8200}


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
            if u.path == "/health":
                return self._send(200, {"ok": True, "service": service})
            if u.path == "/tools":
                actor = (parse_qs(u.query).get("actor") or [""])[0]
                p = personas().get(actor)
                if not p:
                    return self._send(404, {"error": f"unknown actor {actor}"})
                return self._send(200, [t.spec() for t in REGISTRY.values()
                                        if SYSTEM_DB[t.system] == service and t.system in p.get("systems", [])])
            self._send(404, {"error": "not found"})

        def do_POST(self):
            if urlparse(self.path).path != "/call":
                return self._send(404, {"error": "not found"})
            try:
                req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            except json.JSONDecodeError:
                return self._send(400, {"error": "body must be JSON"})
            name = req.get("tool", "")
            if name not in REGISTRY or SYSTEM_DB[REGISTRY[name].system] != service:
                return self._send(404, {"error": f"tool {name} is not served by {service}"})
            self._send(200, call_json(req.get("actor", ""), name, req.get("args") or {}))

        def log_message(self, fmt, *args):
            pass

    return Handler


def main():
    ap = argparse.ArgumentParser(description="Serve VXC Motors systems over HTTP")
    ap.add_argument("service", choices=list(PORTS))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int)
    a = ap.parse_args()
    Store.get(a.service)   # open (and seed if needed) before taking requests
    port = a.port or PORTS[a.service]
    print(f"{a.service} systems on http://{a.host}:{port}")
    ThreadingHTTPServer((a.host, port), make_handler(a.service)).serve_forever()


if __name__ == "__main__":
    main()
