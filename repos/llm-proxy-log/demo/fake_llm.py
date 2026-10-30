"""An offline stand-in for the LLM provider: an OpenAI-compatible /v1/chat/completions that needs no key,
no network and no money. It is not clever; it is predictable, so the demo and the tests run anywhere.

    python3 demo/fake_llm.py            -> http://127.0.0.1:8099/v1

How it answers a chat completion:
  - tools offered, and the person's last message not yet answered with a tool result:
      call the tool whose name and description share the most words with that message, filling each
      parameter with an id-looking token from the message (T-311, 1042, L-77, INC-19, export/csv.py...)
  - otherwise: a short answer that quotes the last tool result or repeats the request
  - a request that asks for "JSON only" (a classifier prompt) gets {"topic": "none", ...}
Usage is estimated as characters / 4. Answers are deterministic for the same request.

Configuration: FAKE_LLM_HOST / FAKE_LLM_PORT (default 127.0.0.1:8099), FAKE_LLM_LATENCY_MS (default 300).
"""
import hashlib
import json
import os
import re
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("FAKE_LLM_HOST", "127.0.0.1")
PORT = int(os.environ.get("FAKE_LLM_PORT", "8099"))
LATENCY = int(os.environ.get("FAKE_LLM_LATENCY_MS", "300"))
TOKEN = re.compile(r"\b(?:[A-Z]{1,4}-\d+|\d{3,}|[\w-]+/[\w./-]+\.\w+|api|web|email-import|export|billing|import|refunds|seats|failed_payment)\b")
WORD = re.compile(r"[a-z]{3,}")


def _text(content):
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


def _pick_tool(tools, text):
    words = set(WORD.findall(text.lower()))
    def score(t):
        fn = t["function"]
        return len(words & set(WORD.findall((fn["name"].replace("_", " ") + " " + fn.get("description", "")).lower())))
    return max(tools, key=score)


def _args(tool, text):
    params = list(((tool["function"].get("parameters") or {}).get("properties") or {}))
    found = TOKEN.findall(text)
    args = {}
    for i, p in enumerate(params):
        hint = json.dumps(tool["function"]["parameters"]["properties"][p]).lower()
        choice = next((f for f in found if f.lower() in hint), None) or (found[i] if i < len(found) else (found[0] if found else ""))
        args[p] = choice
    return args


def answer(req):
    msgs = req.get("messages") or []
    tools = req.get("tools") or []
    last_user = max((i for i, m in enumerate(msgs) if m.get("role") == "user"), default=-1)
    after = msgs[last_user + 1:]
    user_text = _text(msgs[last_user].get("content")) if last_user >= 0 else ""
    system = " ".join(_text(m.get("content")) for m in msgs if m.get("role") == "system")
    if "json only" in system.lower():
        return {"role": "assistant", "content": json.dumps({"topic": "none", "level": "none", "stance": "neutral",
                                                            "confidence": 0.5, "rationale": "offline stand-in, no judgement"})}, "stop"
    tool_results = [m for m in after if m.get("role") == "tool"]
    tool = _pick_tool(tools, user_text) if tools and not tool_results else None
    needs = tool and ((tool["function"].get("parameters") or {}).get("properties"))
    if tool and (not needs or TOKEN.search(user_text)):
        call = {"id": "call_" + hashlib.sha256(json.dumps(msgs).encode()).hexdigest()[:16], "type": "function",
                "function": {"name": tool["function"]["name"], "arguments": json.dumps(_args(tool, user_text))}}
        return {"role": "assistant", "content": "", "tool_calls": [call]}, "tool_calls"
    if tool_results:
        facts = " ".join(_text(m.get("content")) for m in tool_results)
        return {"role": "assistant", "content": f"Here is what I found: {facts[:300]}"}, "stop"
    return {"role": "assistant", "content": f"Sure. On \"{user_text[:120]}\": here is a short draft based on what we have so far."}, "stop"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, status, obj):
        data = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if not self.path.rstrip("/").endswith("/chat/completions"):
            return self._send(404, {"error": {"code": 404, "message": "fake LLM: only /chat/completions"}})
        try:
            req = json.loads(body)
        except ValueError:
            return self._send(400, {"error": {"code": 400, "message": "invalid JSON"}})
        time.sleep(LATENCY / 1000)
        msg, finish = answer(req)
        p = sum(len(json.dumps(m)) for m in req.get("messages") or []) // 4
        c = len(json.dumps(msg)) // 4
        self._send(200, {"id": "gen-" + uuid.uuid4().hex[:24], "object": "chat.completion", "created": int(time.time()),
                         "model": req.get("model", "fake"), "provider": "fake-llm",
                         "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
                         "usage": {"prompt_tokens": p, "completion_tokens": c, "total_tokens": p + c}})

    def do_GET(self):
        self._send(404, {"error": {"code": 404, "message": "fake LLM: no such endpoint"}})

    def log_message(self, *args):
        pass


def start(port=PORT):
    """Run in a background thread (for tests and demo/run.py); returns the server."""
    import threading
    srv = ThreadingHTTPServer((HOST, port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    print(f"fake LLM on http://{HOST}:{PORT}/v1", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
