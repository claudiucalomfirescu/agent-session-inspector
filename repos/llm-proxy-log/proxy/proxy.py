"""llm-proxy-log: a proxy between AI agents and an OpenAI-compatible LLM API that records every call.

The agent changes only its base URL (and may send a dummy key); this process alone holds the real key.
Each request is forwarded, the answer returned unchanged, and one row written to a SQLite log saying who
asked (user, department, agent, session), what was sent, what came back, how long it took and how many
tokens it used.

    OPENROUTER_API_KEY=sk-... python3 proxy/proxy.py      -> http://127.0.0.1:8080/v1

Configuration (environment variables):
  OPENROUTER_API_KEY  real provider key       (required; any OpenAI-compatible provider's key works)
  UPSTREAM_BASE_URL   provider API root       (default: https://openrouter.ai/api/v1)
  PROXY_HOST/PORT     where to listen         (default: 127.0.0.1:8080)
  PROXY_LOGGING       on|off                  (default: on; off = pure pass-through, nothing recorded)
  PROXY_LOG_DB        SQLite file for the log (default: logs/proxy.db)
  PROXY_GATEWAY       on|off                  (default: on = rate limit, backoff, fallback model, spend cap
                                               and replay cache for chat completions. See gateway.py)

Who is calling (request headers, all optional, all removed before forwarding; see SPEC.md):
  X-Agent-User   the person or persona the agent works for  -> calls.user (else key:<8 hex>, else anonymous)
  X-Agent-Dept   their department or team                   -> calls.dept
  X-Agent-Id     the agent's own name                       -> calls.agent (else the user)
  X-Session-Id   one conversation / task                    -> calls.session (else derived from the first message)
  X-Agent-<Any>  free labels                                -> calls.labels {"<any>": value}
  Authorization  the client's own key is never forwarded; its sha256 prefix -> calls.key_id
GET /healthz answers itself (not forwarded, not logged). GET /v1/gateway/status shows budget and limiter state.
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from gateway import Gateway
from logstore import LogStore

ON = ("on", "1", "true", "yes")
UPSTREAM = os.environ.get("UPSTREAM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
REAL_KEY = os.environ.get("OPENROUTER_API_KEY")
HOST = os.environ.get("PROXY_HOST", "127.0.0.1")
PORT = int(os.environ.get("PROXY_PORT", "8080"))
LOGGING = os.environ.get("PROXY_LOGGING", "on").lower() in ON
LOG_DB = os.environ.get("PROXY_LOG_DB", "logs/proxy.db")
GATEWAY = Gateway(UPSTREAM, REAL_KEY) if os.environ.get("PROXY_GATEWAY", "on").lower() in ON else None
STORE = LogStore(LOG_DB)

# Identity headers with their own column; every other X-Agent-* header becomes a label.
IDENTITY = {"x-agent-id": "agent", "x-agent-user": "user", "x-agent-dept": "dept", "x-session-id": "session"}
# Headers that describe one hop only, or that the agent's own key/transport must not leak upstream.
SKIP_REQUEST = {"host", "authorization", "content-length", "connection", "accept-encoding", "transfer-encoding",
                "x-session-id"}
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


def identity(headers, req=None):
    """Who is calling (K-agent-headers@1): {user, agent, dept, session, key_id, labels}.

    user    X-Agent-User, else "key:" + key_id, else "anonymous"
    agent   X-Agent-Id, else the user
    session X-Session-Id, else a stable id derived from (agent, first user message), so every turn
            of one conversation lands in the same session
    key_id  first 8 hex of sha256 of the client's own bearer key (never the key itself)
    """
    out = {col: headers.get(h) for h, col in IDENTITY.items()}
    auth = headers.get("Authorization") or ""
    key = auth[7:].strip() if auth.lower().startswith("bearer ") else auth.strip()
    out["key_id"] = hashlib.sha256(key.encode()).hexdigest()[:8] if key else None
    out["user"] = out["user"] or (f"key:{out['key_id']}" if key else "anonymous")
    out["agent"] = out["agent"] or out["user"]
    if not out["session"]:
        msgs = (req or {}).get("messages") if isinstance(req, dict) else None
        first = next((m.get("content") for m in msgs or [] if isinstance(m, dict) and m.get("role") == "user"), None)
        if first is not None:
            seed = out["agent"] + "\0" + json.dumps(first, sort_keys=True)
            out["session"] = "auto-" + hashlib.sha256(seed.encode()).hexdigest()[:12]
    # X-Agent-Role: support -> {"role": "support"}
    out["labels"] = {k[8:].lower(): v for k, v in headers.items()
                     if k.lower().startswith("x-agent-") and k.lower() not in IDENTITY} or None
    return out


def log_call(started, duration_ms, who, method, path, status, req_raw, resp_raw, meta=None):
    """Write one row to `calls` and return its id. Never raises: a logging failure must not touch the reply."""
    try:
        req_text, resp_text = _text(req_raw), _text(resp_raw)
        req, resp = _json(req_text) or {}, _json(resp_text) or {}
        if not isinstance(resp, dict):
            resp = {}
        choice = (resp.get("choices") or [{}])[0]
        usage = resp.get("usage") if isinstance(resp.get("usage"), dict) else None
        error = resp.get("error")
        if status >= 400 and not error:
            error = {"code": status, "message": resp_text[:500]}
        meta = meta or {}
        return STORE.insert("calls", {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(started)) + "Z", "duration_ms": duration_ms,
            "agent": who["agent"], "session": who["session"], "user": who["user"], "dept": who["dept"],
            "key_id": who["key_id"], "labels": json.dumps(who["labels"]) if who["labels"] else None,
            "method": method, "path": path, "status": status,
            "model": req.get("model") if isinstance(req, dict) else None, "finish_reason": choice.get("finish_reason"),
            "usage": json.dumps(usage) if usage else None,
            "prompt_tokens": (usage or {}).get("prompt_tokens"), "completion_tokens": (usage or {}).get("completion_tokens"),
            "total_tokens": (usage or {}).get("total_tokens"),
            "error": json.dumps(error) if error else None, "request": req_text, "response": resp_text,
            "route": meta.get("route"), "upstream_model": meta.get("upstream_model"), "attempts": meta.get("attempts"),
            "cost_usd": meta.get("cost_usd"), "firewall_level": meta.get("firewall_level")})
    except Exception as e:  # noqa: BLE001
        print(f"log write failed: {type(e).__name__}", file=sys.stderr, flush=True)
        return None


def _upstream(method, path, body, headers):
    req = urllib.request.Request(UPSTREAM + path, data=body or None, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, r.getheaders(), r.read()
    except urllib.error.HTTPError as e:  # provider errors are passed back as they are
        return e.code, e.headers.items(), e.read()
    except OSError as e:
        data = ('{"error": {"code": 502, "message": "proxy could not reach provider: %s"}}'
                % type(e).__name__).encode()
        return 502, [("Content-Type", "application/json")], data


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _forward(self):
        path = self.path[3:] if self.path.startswith("/v1") else self.path
        if self.command == "GET" and self.path.rstrip("/") == "/healthz":  # the proxy's own; not forwarded, not logged
            return self._json_reply(200, {"ok": True, "logging": LOGGING, "gateway": bool(GATEWAY)})
        if GATEWAY and self.command == "GET" and path.rstrip("/") == "/gateway/status":
            return self._json_reply(200, GATEWAY.status())
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in SKIP_REQUEST and not k.lower().startswith("x-agent-")}
        headers["Authorization"] = f"Bearer {REAL_KEY}"
        started = time.time()
        meta = {}
        if GATEWAY and self.command == "POST" and path.rstrip("/") == "/chat/completions":
            status, resp_headers, data, meta = GATEWAY.chat(path, body, headers)
        else:
            status, resp_headers, data = _upstream(self.command, path, body, headers)
        if LOGGING:
            log_call(started, int((time.time() - started) * 1000), identity(self.headers, _json(body.decode("utf-8", "replace"))),
                     self.command, self.path, status, body, data, meta)
        self._reply(status, resp_headers, data)

    def _json_reply(self, status, obj):
        self._reply(status, [("Content-Type", "application/json")], json.dumps(obj, indent=1).encode())

    def _reply(self, status, resp_headers, data):
        self.send_response(status)
        for k, v in resp_headers:
            if k.lower() not in SKIP_RESPONSE:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = _forward

    def log_message(self, *args):  # the log is the database, not stderr
        pass


def serve():
    print(f"proxy listening on http://{HOST}:{PORT}/v1 -> {UPSTREAM}  logging={'on -> ' + LOG_DB if LOGGING else 'off'}  "
          f"gateway={'on, cache=' + GATEWAY.cfg.cache if GATEWAY else 'off'}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    if not REAL_KEY:
        sys.exit("Set OPENROUTER_API_KEY for the proxy (any value works against the offline demo LLM).")
    serve()
