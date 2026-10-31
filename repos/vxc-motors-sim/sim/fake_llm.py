"""A scripted stand-in for OpenRouter, so the whole workday can run offline (tests, demos without a key).

    python -m sim.fake_llm --port 9099
    UPSTREAM_BASE_URL=http://127.0.0.1:9099/api/v1 OPENROUTER_API_KEY=sk-fake python -m sim.run

It answers like a very literal assistant, which is enough to drive every channel of the simulation:
  * a doorbell naming an email (MSG-…)       -> call mail_read on it, then answer it with mail_send
  * a doorbell about a team chat message     -> call chat_unread
  * a goal mentioning "team chat"            -> chat_send to the first colleague id in the goal
  * "Write an email to … (address)"          -> mail_send to that address
  * a goal asking for a technical support case -> bmw_open_tech_case
  * the firewall's intent classifier         -> {"level": "info"}
  * anything else                            -> "Done."
"""
import argparse
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STAFF_ID = re.compile(r"\b(victor-hale|maria-santos|priya-nair|daniel-reed|sofia-marin|tom-becker|elena-popescu|"
                      r"james-okafor|nina-kovac|lucas-meyer|aisha-rahman|mark-doyle)\b")
_n = [0]
_lock = threading.Lock()


def _call(name, args):
    with _lock:
        _n[0] += 1
        cid = f"call_{_n[0]}"
    return {"role": "assistant", "content": None,
            "tool_calls": [{"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def _say(text):
    return {"role": "assistant", "content": text}


def answer(req):
    msgs = req["messages"]
    system = msgs[0].get("content") or ""
    if "classifier" in system.lower():
        return _say(json.dumps({"topic": "none", "level": "info", "confidence": 0.5, "rationale": "fake"}))
    tools = {t["function"]["name"] for t in req.get("tools") or []}
    used = [c["function"]["name"] for m in msgs if m.get("role") == "assistant" for c in m.get("tool_calls") or []]
    last = msgs[-1]
    goal = next((m.get("content") or "" for m in reversed(msgs) if m.get("role") == "user"), "")
    if last.get("role") == "tool":
        prev = used[-1] if used else ""
        if prev == "mail_read" and "mail_send" in tools and "mail_send" not in used:
            try:
                m = json.loads(last["content"])
                return _call("mail_send", {"to": m["from_addr"], "subject": "Re: " + (m.get("subject") or ""),
                                           "body": "Thank you for your message, noted.", "reply_to": m["msg_id"]})
            except (ValueError, KeyError):
                pass
        return _say("Done.")
    if not used:
        mid = re.search(r"\bMSG-\d+\b", goal)
        if mid and "mail_read" in tools:
            return _call("mail_read", {"msg_id": mid.group(0)})
        if "chat message" in goal and "chat_unread" in tools:
            return _call("chat_unread", {})
        to = re.search(r"Write an email to .*?\(([^)]+@[^)]+)\)", goal)
        if to and "mail_send" in tools:
            return _call("mail_send", {"to": to.group(1), "subject": "About my car", "body": "Please call me back."})
        if "technical support case" in goal and "bmw_open_tech_case" in tools:
            return _call("bmw_open_tech_case", {"vin": "WBA00000000000000", "symptom": "HV system warning"})
        if "team chat" in goal and "chat_send" in tools:
            who = STAFF_ID.findall(goal) or ["sofia-marin"]
            return _call("chat_send", {"to": who[0], "message": "Heads up: " + goal[:80]})
    return _say("Done.")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._send({"data": {"usage": 0, "limit": None,
                             "free_model_daily_requests": {"used": 0, "limit": 1000, "remaining": 1000}}})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        msg = answer(req)
        self._send({"id": "gen-fake", "model": req.get("model"), "provider": "fake",
                    "choices": [{"index": 0, "message": msg,
                                 "finish_reason": "tool_calls" if msg.get("tool_calls") else "stop"}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}})

    def _send(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


def serve(port=0):
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9099)
    srv = serve(ap.parse_args().port)
    print(f"fake LLM on http://127.0.0.1:{srv.server_port}/api/v1", flush=True)
    threading.Event().wait()
