"""Turn a session's raw calls into a readable conversation.

Each chat-completions request carries the WHOLE conversation so far, so reading the calls one after the
other repeats everything. Here each call contributes only what is new: the messages appended since the
previous call (the user's next message, tool results), then the LLM's answer. Firewall findings and
admin actions are attached to the call they belong to.
"""
import json


def _j(text):
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text.strip())
    except ValueError:
        return text


def parse_response(raw):
    """{message, finish_reason, usage, model} from a stored response (plain JSON or an SSE stream)."""
    if raw is None:
        return {}
    text = raw.strip() if isinstance(raw, str) else raw
    if isinstance(text, str) and text.startswith("data:"):
        content, calls, finish, usage, model = [], {}, None, None, None
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            chunk = _j(line[5:])
            if not isinstance(chunk, dict):
                continue
            model = chunk.get("model") or model
            usage = chunk.get("usage") or usage
            for ch in chunk.get("choices") or []:
                d = ch.get("delta") or {}
                if d.get("content"):
                    content.append(d["content"])
                for tc in d.get("tool_calls") or []:
                    slot = calls.setdefault(tc.get("index", 0), {"id": tc.get("id"), "function": {"name": "", "arguments": ""}})
                    fn = tc.get("function") or {}
                    slot["function"]["name"] += fn.get("name") or ""
                    slot["function"]["arguments"] += fn.get("arguments") or ""
                finish = ch.get("finish_reason") or finish
        msg = {"role": "assistant", "content": "".join(content) or None}
        if calls:
            msg["tool_calls"] = [calls[k] for k in sorted(calls)]
        return {"message": msg, "finish_reason": finish, "usage": usage, "model": model}
    data = _j(text)
    if not isinstance(data, dict):
        return {"raw": text}
    if "error" in data and not data.get("choices"):
        return {"error": data["error"]}
    ch = (data.get("choices") or [{}])[0]
    return {"message": ch.get("message"), "finish_reason": ch.get("finish_reason"), "usage": data.get("usage"),
            "model": data.get("model")}


def _text(content):
    """OpenAI content can be a string or a list of parts; the console shows text."""
    if isinstance(content, list):
        return "\n".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return content


def _same(a, b):
    return a.get("role") == b.get("role") and _text(a.get("content")) == _text(b.get("content"))


def new_messages(prev, cur):
    """The messages `cur` adds to the conversation `prev` (prev = previous request + its answer)."""
    n = 0
    while n < len(prev) and n < len(cur) and _same(prev[n], cur[n]):
        n += 1
    if n == 0 and prev:  # the client rewrote history (e.g. trimmed it): show everything but the system prompt
        return [m for m in cur if m.get("role") != "system"]
    return cur[n:]


def build_session(session, calls, signals, actions):
    steps, seen, system_prompt, tools = [], [], None, set()
    by_call_sig, by_call_act = {}, {}
    for s in signals:
        by_call_sig.setdefault(s.get("call_id"), []).append(s)
    for a in actions:
        by_call_act.setdefault(a.get("call_id"), []).append(a)
    for c in calls:
        req = _j(c.get("request")) or {}
        msgs = req.get("messages") if isinstance(req, dict) else None
        msgs = msgs or []
        for t in (req.get("tools") if isinstance(req, dict) else None) or []:
            tools.add(((t or {}).get("function") or {}).get("name"))
        if msgs and msgs[0].get("role") == "system" and system_prompt is None:
            system_prompt = _text(msgs[0].get("content"))
        added = new_messages(seen, msgs) if seen else [m for m in msgs if m.get("role") != "system"]
        res = parse_response(c.get("response"))
        answer = res.get("message")
        steps.append({
            "call_id": c["id"], "ts": c.get("ts"), "status": c.get("status"), "model": c.get("model"),
            "upstream_model": c.get("upstream_model"), "route": c.get("route"), "duration_ms": c.get("duration_ms"),
            "finish_reason": c.get("finish_reason") or res.get("finish_reason"),
            "prompt_tokens": c.get("prompt_tokens"), "completion_tokens": c.get("completion_tokens"),
            "total_tokens": c.get("total_tokens"), "cost": c.get("cost"), "firewall_level": c.get("firewall_level"),
            "input": [{"role": m.get("role"), "content": _text(m.get("content")), "name": m.get("name"),
                       "tool_call_id": m.get("tool_call_id"), "tool_calls": m.get("tool_calls")} for m in added],
            "output": answer, "error": _j(c.get("error")) or res.get("error"),
            "signals": by_call_sig.pop(c["id"], []), "actions": by_call_act.pop(c["id"], []),
        })
        seen = msgs + ([answer] if answer else [])
    first = calls[0]
    labels = _j(first.get("labels")) if isinstance(first.get("labels"), str) else first.get("labels")
    return {
        "session": session, "user": first.get("user"), "dept": first.get("dept"), "agent": first.get("agent"),
        "labels": labels if isinstance(labels, dict) else {}, "started": first.get("ts"), "ended": calls[-1].get("ts"),
        "system_prompt": system_prompt, "tools": sorted(t for t in tools if t), "steps": steps,
        # findings and actions not tied to one call (session-level escalation, an admin's note)
        "loose_signals": [s for v in by_call_sig.values() for s in v],
        "loose_actions": [a for v in by_call_act.values() for a in v],
        "totals": {"calls": len(calls), "tokens": sum(c.get("total_tokens") or 0 for c in calls),
                   "cost": sum(c.get("cost") or 0 for c in calls)},
    }
