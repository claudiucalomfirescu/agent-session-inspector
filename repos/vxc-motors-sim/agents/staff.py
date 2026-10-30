"""An employee of VXC Motors as an AI agent.

The loop is the standard tool-calling loop: send the conversation and the tool list to the LLM (through
the proxy), run the tool calls it asks for against the applications (over HTTP), append the results,
repeat until it answers in words. Everything the agent does to the world (a CRM update, an email, a
chat message, a BMW order) is a tool call the LLM asked for, so it is in the proxy log.

    agent = StaffAgent("tom-becker", labels={"task": "E06"})
    out = agent.run("Start your day. ...")       # {"session", "calls", "tools", "answers", "status"}
"""
from openai import APIError

from agents.prompts import staff_prompt
from agents.toolclient import ToolClient
from apps.common import personas
from llm import MODEL, AgentLog, chat, make_client

TOOL_RESULT_MAX = 4000


def _content(msg):
    return (msg.content or "").strip()


class StaffAgent:
    """One employee working one task: a fresh LLM session, up to max_turns model calls per user turn."""

    def __init__(self, persona_id, labels=None, max_turns=8, on_event=None):
        self.p = personas()[persona_id]
        self.id = persona_id
        self.labels = {"role": self.p["role"], "org": "vxc-motors", **(labels or {})}
        self.max_turns = max_turns
        self.on_event = on_event or (lambda kind, **data: None)   # the simulation's hook (counting, timeline)
        self.respond = None   # callable(answer) -> next user message or None (a live conversation)

    def run(self, goal, followups=()):
        tools = ToolClient(self.id)
        client, session = make_client(self.id, dept=self.p["department"], **self.labels)
        log = AgentLog(self.id, session, dept=self.p["department"], **self.labels)
        log.start(goal=goal, model=MODEL)
        self.on_event("session_start", session=session)
        messages = [{"role": "system", "content": staff_prompt(self.id)}, {"role": "user", "content": goal}]
        out = {"session": session, "agent": self.id, "calls": 0, "tools": [], "answers": [], "status": "done"}
        pending = list(followups)
        answer = self._loop(client, tools, messages, log, out)
        out["answers"].append(answer)
        while not log.blocked and out["status"] == "done":
            # what the employee says next: a scripted follow-up, or the other person's live reply
            follow = pending.pop(0) if pending else (self.respond(answer) if self.respond else None)
            if not follow:
                break
            messages.append({"role": "user", "content": follow})
            self.on_event("followup", session=session, text=follow)
            answer = self._loop(client, tools, messages, log, out)
            out["answers"].append(answer)
        if log.blocked:
            out["status"] = "blocked"
            out["firewall"] = log.blocked
        log.end(answer=out["answers"][-1] if out["answers"] else None, status=out["status"])
        return out

    def _loop(self, client, tools, messages, log, out):
        for _ in range(self.max_turns):
            try:
                resp = chat(client, messages, tools=tools.specs, log=log)
            except APIError as e:
                out["status"] = "error"
                out["error"] = f"{type(e).__name__}: {e}"[:300]
                return None
            out["calls"] += 1
            self.on_event("llm_call", session=out["session"])
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            if log.blocked:
                self.on_event("blocked", session=out["session"], firewall=log.blocked, text=_content(msg)[:400])
                return _content(msg)
            if not msg.tool_calls:
                return _content(msg)
            for c in msg.tool_calls:
                result = tools.call(c.function.name, c.function.arguments)
                log.tool(c.function.name, c.function.arguments, result)
                out["tools"].append(c.function.name)
                self.on_event("tool", session=out["session"], tool=c.function.name, args=c.function.arguments,
                              result=result[:300])
                messages.append({"role": "tool", "tool_call_id": c.id, "content": result[:TOOL_RESULT_MAX]})
        out["status"] = "turn_limit"
        return None
