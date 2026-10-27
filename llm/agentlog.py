"""The agent's own log: what the conversation looked like from the agent's side of the proxy.

The proxy log (logs/proxy.db) is the network's view. This one is the client's view, one JSON line per
event in logs/agents/<agent_id>.jsonl, so an agent can be audited even without the proxy's records,
and the two can be compared: when the firewall blocks a session, the proxy log says *why*, while the
agent log shows the block message exactly as the agent received it, looking like any LLM answer.

    log = AgentLog("parts-mark", session, role="parts")
    log.start(goal)
    resp = chat(client, messages, log=log)       # llm.chat records request + answer
    log.tool("get_stock", {"sku": "..."}, result)
    log.end("final answer", status="done")

Events: session_start, request, response, tool, error, session_end. A response the proxy answered
itself carries "firewall": {...} (from the X-Firewall header) and marks the session blocked.

Configuration: AGENT_LOG_DIR (default: logs/agents), AGENT_LOG=off disables writing.
"""
import json
import os
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_lock = threading.Lock()


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def parse_firewall_header(value):
    """'block; topic=credential_sharing; ref=FW-1A2B3C4D' -> {"level": "block", "topic": ..., "ref": ...}"""
    if not value:
        return None
    parts = [p.strip() for p in value.split(";")]
    out = {"level": parts[0]}
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k.strip()] = v.strip()
    return out


class AgentLog:
    def __init__(self, agent_id, session_id, directory=None, **labels):
        self.agent_id, self.session_id, self.labels = agent_id, session_id, labels
        self.enabled = os.environ.get("AGENT_LOG", "on").lower() not in ("off", "0", "false", "no")
        d = directory or os.environ.get("AGENT_LOG_DIR") or os.path.join(ROOT, "logs", "agents")
        self.path = os.path.join(d, f"{agent_id}.jsonl")
        self.turn, self.sent, self.blocked = 0, 0, None

    def write(self, event, **data):
        if not self.enabled:
            return
        row = {"ts": _now(), "agent": self.agent_id, "session": self.session_id, "event": event, **data}
        with _lock:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a") as f:
                f.write(json.dumps(row, default=str) + "\n")

    def start(self, goal=None, model=None):
        self.write("session_start", goal=goal, model=model, labels=self.labels)

    def request(self, messages):
        """Log only the messages that are new since the last request (the history is resent each turn).
        Assistant messages are skipped: they were logged as responses."""
        self.turn += 1
        new = [p for p in (_plain(m) for m in messages[self.sent:]) if p.get("role") != "assistant"]
        self.sent = len(messages)
        self.write("request", turn=self.turn, messages=new)

    def response(self, resp, headers=None):
        """resp: the SDK's ChatCompletion. headers: the HTTP response headers, if available."""
        choice = resp.choices[0]
        msg = choice.message
        fw = parse_firewall_header((headers or {}).get("x-firewall"))
        data = {"turn": self.turn, "finish_reason": choice.finish_reason, "content": msg.content,
                "tool_calls": [{"name": c.function.name, "arguments": c.function.arguments} for c in msg.tool_calls or []],
                "usage": resp.usage.model_dump() if resp.usage else None}
        if fw:
            data["firewall"] = fw
            if fw["level"] == "block":
                self.blocked = fw
        self.write("response", **data)

    def tool(self, name, args, result):
        self.write("tool", turn=self.turn, name=name, args=args, result=str(result)[:2000])

    def error(self, err):
        self.write("error", turn=self.turn, error=f"{type(err).__name__}: {err}"[:1000])

    def end(self, answer=None, status="done"):
        self.write("session_end", turns=self.turn, status="blocked" if self.blocked else status,
                   answer=answer, firewall=self.blocked)


def _plain(m):
    if not isinstance(m, dict):
        m = m.model_dump(exclude_none=True)
    return {k: v for k, v in m.items() if k in ("role", "content", "tool_calls", "tool_call_id", "name")}


def read_log(agent_id, session_id=None, directory=None):
    """All events of one agent (optionally one session), oldest first."""
    d = directory or os.environ.get("AGENT_LOG_DIR") or os.path.join(ROOT, "logs", "agents")
    path = os.path.join(d, f"{agent_id}.jsonl")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    return [r for r in rows if session_id is None or r["session"] == session_id]
