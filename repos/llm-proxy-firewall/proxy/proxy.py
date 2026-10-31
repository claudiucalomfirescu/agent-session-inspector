"""llm-proxy-firewall: a proxy between AI agents and an OpenAI-compatible LLM API that records every call
and inspects every conversation.

The agent changes only its base URL (and may send a dummy key); this process alone holds the real key.
Each request is logged as in llm-proxy-log (who asked, what was sent, what came back, tokens), and the
firewall (firewall.py) reads both directions:
  info     noted in `signals`, forwarded as normal
  warning  noted, forwarded, and the reply carries an X-Firewall: warning header
  block    NOT forwarded: the proxy answers in the LLM's place with a normal chat completion saying the
           session is closed, and keeps answering that way until an administrator unblocks it

    OPENROUTER_API_KEY=sk-... python3 proxy/proxy.py      -> http://127.0.0.1:8080/v1

Configuration (environment variables):
  OPENROUTER_API_KEY  real provider key       (required; any OpenAI-compatible provider's key works)
  UPSTREAM_BASE_URL   provider API root       (default: https://openrouter.ai/api/v1)
  PROXY_HOST/PORT     where to listen         (default: 127.0.0.1:8080)
  PROXY_LOGGING       on|off                  (default: on; off = pure pass-through, nothing recorded)
  PROXY_LOG_DB        SQLite file for the log (default: logs/proxy.db)
  PROXY_GATEWAY       on|off                  (default: on = rate limit, backoff, fallback model, spend cap
                                               and replay cache for chat completions. See gateway.py)
  FIREWALL            on|off                  (default: on. FIREWALL_TOPICS, FIREWALL_INTENT...: see firewall.py)
  FIREWALL_ADMIN_TOKEN  if set, the admin endpoints need header X-Admin-Token with this value
  FIREWALL_EXEMPT_AGENTS  agent ids whose traffic is not inspected (default: none). With FIREWALL_ADMIN_TOKEN
                        set, the exemption also needs X-Admin-Token, so an agent cannot claim it by name.
  FIREWALL_DISCLOSE   on|off  add an X-Firewall header to replies (default: on)
  FIREWALL_INTENT_MODEL  model for the intent check (default: the gateway's free model, else its fallback)

Who is calling (request headers, all optional, all removed before forwarding; see SPEC.md):
  X-Agent-User   the person or persona the agent works for  -> calls.user (else key:<8 hex>, else anonymous)
  X-Agent-Dept   their department or team                   -> calls.dept
  X-Agent-Id     the agent's own name                       -> calls.agent (else the user)
  X-Session-Id   one conversation / task                    -> calls.session (else derived from the first message)
  X-Agent-<Any>  free labels                                -> calls.labels {"<any>": value}
  Authorization  the client's own key is never forwarded; its sha256 prefix -> calls.key_id
GET /healthz answers itself (not forwarded, not logged). GET /v1/gateway/status shows budget and limiter state.
GET /v1/firewall/status shows topics, blocked sessions and counters;
POST /v1/firewall/sessions/<session>/block|unblock|note  {"actor": "...", "reason": "..."} is the admin's lever.
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

from firewall import Firewall
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
ADMIN_TOKEN = os.environ.get("FIREWALL_ADMIN_TOKEN")
EXEMPT_AGENTS = {a.strip() for a in os.environ.get("FIREWALL_EXEMPT_AGENTS", "").split(",") if a.strip()}

# Identity headers with their own column; every other X-Agent-* header becomes a label.
IDENTITY = {"x-agent-id": "agent", "x-agent-user": "user", "x-agent-dept": "dept", "x-session-id": "session"}
# Headers that describe one hop only, or that the agent's own key/transport must not leak upstream.
SKIP_REQUEST = {"x-admin-token", "host", "authorization", "content-length", "connection", "accept-encoding", "transfer-encoding",
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


def _intent_llm(messages):
    """The firewall's classifier call: through the gateway (shared rate limit, budget and cache) and logged
    like any agent's call, as user and agent 'firewall', session 'firewall-intent'. On the free model when it
    has room this minute and enough requests left today, otherwise once on the cheap paid fallback."""
    free = _budget_ok()
    answer = _intent_call(messages, free)
    if answer is None and free:  # the free model failed or was busy: try the paid one once
        answer = _intent_call(messages, False)
    return answer


def _intent_call(messages, free):
    cfg = GATEWAY.cfg if GATEWAY else None
    model = os.environ.get("FIREWALL_INTENT_MODEL") or (
        (cfg.primary_model if cfg else "nvidia/nemotron-3.5-super-vl:free") if free else (cfg and cfg.fallback_model))
    if not model:
        return None
    # a one-line JSON verdict needs little thinking. The free model answers fastest with reasoning off;
    # models that cannot turn reasoning off get the lowest effort
    extra = ({"reasoning": {"enabled": False}} if model.endswith(":free")
             else {"reasoning": {"effort": "low"}, "max_tokens": 800})
    body = json.dumps({"model": model, "messages": messages, "temperature": 0, **extra}).encode()
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {REAL_KEY}"}
    started = time.time()
    if GATEWAY:
        status, _, data, meta = GATEWAY.chat("/chat/completions", body, headers)
    else:
        status, _, data = _upstream("POST", "/chat/completions", body, headers)
        meta = {}
    FIREWALL.stats["intent_free" if free else "intent_paid"] += 1
    if LOGGING:
        who = {"user": "firewall", "agent": "firewall", "dept": None, "session": "firewall-intent", "key_id": None,
               "labels": {"role": "intent-classifier", "tier": "free" if free else "paid"}}
        log_call(started, int((time.time() - started) * 1000), who, "POST", "/v1/chat/completions", status, body, data, meta)
    if status != 200:
        return None
    resp = _json(data.decode("utf-8", "replace")) or {}
    return (((resp.get("choices") or [{}])[0].get("message") or {}).get("content")) if isinstance(resp, dict) else None


def _budget_ok():
    """Whether the intent check may use the free model now: plenty left today and the minute not busy."""
    if not GATEWAY:
        return True
    remaining = GATEWAY.free_remaining()
    if remaining is not None and remaining < FIREWALL.min_free:
        return False
    return GATEWAY.limiters["free"].in_window() < GATEWAY.cfg.free_rpm - 2


FIREWALL = Firewall(STORE, llm=_intent_llm, budget_ok=_budget_ok) if os.environ.get("FIREWALL", "on").lower() in ON else None


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
        if FIREWALL and path.startswith("/firewall/"):
            return self._firewall_admin(path, body)
        headers = {k: v for k, v in self.headers.items()
                   if k.lower() not in SKIP_REQUEST and not k.lower().startswith("x-agent-")}
        headers["Authorization"] = f"Bearer {REAL_KEY}"
        started = time.time()
        meta, decisions = {}, []
        is_chat = self.command == "POST" and path.rstrip("/") == "/chat/completions"
        req = _json(body.decode("utf-8", "replace")) if is_chat else None
        who = identity(self.headers, req)
        exempt = who["agent"] in EXEMPT_AGENTS and (not ADMIN_TOKEN or self.headers.get("X-Admin-Token") == ADMIN_TOKEN)
        inspect = FIREWALL and isinstance(req, dict) and not exempt
        session_key = who["session"] or who["agent"]

        # 1. Inspect what the agent sends. On block, answer in the LLM's place: nothing goes upstream.
        if inspect:
            decisions.append(FIREWALL.inspect_request(who["agent"], session_key, req, user=who["user"]))
        if decisions and decisions[0].blocked:
            status, resp_headers, data = FIREWALL.block_completion(req, decisions[0])
            meta["route"] = "firewall"
        elif GATEWAY and is_chat:
            status, resp_headers, data, meta = GATEWAY.chat(path, body, headers)
        else:
            status, resp_headers, data = _upstream(self.command, path, body, headers)
        # 2. Inspect what the LLM answered. On block, the agent gets the block message instead.
        if inspect and not decisions[0].blocked and status == 200 and not req.get("stream"):
            d = FIREWALL.inspect_response(who["agent"], session_key, req, _json(data.decode("utf-8", "replace")),
                                          user=who["user"])
            decisions.append(d)
            if d.blocked:
                status, resp_headers, data = FIREWALL.block_completion(req, d)
                meta["route"] = "firewall-response"
        level = max((d.level for d in decisions if d.level), key=["info", "warning", "block"].index, default=None)
        if level and level != "block" and os.environ.get("FIREWALL_DISCLOSE", "on").lower() in ON:
            resp_headers = list(resp_headers) + [("X-Firewall", level)]

        call_id = None
        if LOGGING:
            meta["firewall_level"] = level
            call_id = log_call(started, int((time.time() - started) * 1000), who,
                               self.command, self.path, status, body, data, meta)
        for d in decisions:
            FIREWALL.commit(d, call_id)
        self._reply(status, resp_headers, data)

    def _firewall_admin(self, path, body):
        if ADMIN_TOKEN and self.headers.get("X-Admin-Token") != ADMIN_TOKEN:
            return self._json_reply(403, {"error": {"code": 403, "message": "admin token required"}})
        parts = path.strip("/").split("/")  # firewall/status | firewall/sessions/<id>/<action>
        if self.command == "GET" and parts == ["firewall", "status"]:
            return self._json_reply(200, FIREWALL.status())
        if self.command == "POST" and len(parts) == 4 and parts[1] == "sessions" and parts[3] in ("block", "unblock", "note"):
            args = _json(body.decode("utf-8", "replace")) or {}
            row = FIREWALL.admin(parts[3] + ("_session" if parts[3] != "note" else ""), parts[2],
                                 args.get("actor"), args.get("reason"))
            return self._json_reply(200, row)
        return self._json_reply(404, {"error": {"code": 404, "message": "unknown firewall endpoint"}})

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
          f"gateway={'on, cache=' + GATEWAY.cfg.cache if GATEWAY else 'off'}  "
          f"firewall={'on, intent=' + FIREWALL.intent_mode if FIREWALL else 'off'}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    if not REAL_KEY:
        sys.exit("Set OPENROUTER_API_KEY for the proxy (any value works against the offline demo LLM).")
    serve()
