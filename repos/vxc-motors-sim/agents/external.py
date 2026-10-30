"""People outside the company, as agents: customers and BMW UK.

Two kinds:
  MailAgent  has an email address and the three mail tools (mail_inbox, mail_read, mail_send). It is
             told "you have a new email MSG-…" and reads, then answers, by tool calls, like staff do.
  Talker     no tools: a customer at the reception desk or on the phone. What it says is its output;
             the simulation carries the words to the employee they are talking to (the "room").

Both go through the proxy with X-Agent-User (customer-<name>, bmw-retailer-support) and
X-Agent-Dept ("Customers", "BMW UK"), so the console sees them as users like any employee.
"""
import re

from openai import APIError

from agents.toolclient import ToolClient
from apps.common import external_actor
from llm import MODEL, AgentLog, chat, make_client

TOOL_RESULT_MAX = 4000


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


class MailAgent:
    def __init__(self, user, dept, email, system, labels=None, max_turns=5, on_event=None):
        self.user, self.dept, self.email, self.system = user, dept, email, system
        self.labels = {"org": "external", **(labels or {})}
        self.max_turns = max_turns
        self.on_event = on_event or (lambda kind, **data: None)

    def run(self, goal):
        tools = ToolClient(external_actor(self.email))
        client, session = make_client(self.user, dept=self.dept, **self.labels)
        log = AgentLog(self.user, session, dept=self.dept, **self.labels)
        log.start(goal=goal, model=MODEL)
        self.on_event("session_start", session=session)
        messages = [{"role": "system", "content": self.system}, {"role": "user", "content": goal}]
        out = {"session": session, "agent": self.user, "calls": 0, "tools": [], "status": "done", "answer": None}
        for _ in range(self.max_turns):
            try:
                resp = chat(client, messages, tools=tools.specs, log=log)
            except APIError as e:
                out.update(status="error", error=str(e)[:300])
                break
            out["calls"] += 1
            self.on_event("llm_call", session=session)
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            if log.blocked or not msg.tool_calls:
                out["answer"] = (msg.content or "").strip()
                break
            for c in msg.tool_calls:
                result = tools.call(c.function.name, c.function.arguments)
                log.tool(c.function.name, c.function.arguments, result)
                out["tools"].append(c.function.name)
                self.on_event("tool", session=session, tool=c.function.name, args=c.function.arguments,
                              result=result[:300])
                messages.append({"role": "tool", "tool_call_id": c.id, "content": result[:TOOL_RESULT_MAX]})
        else:
            out["status"] = "turn_limit"
        if log.blocked:
            out["status"], out["firewall"] = "blocked", log.blocked
        log.end(answer=out["answer"], status=out["status"])
        return out


class Talker:
    """A person speaking face to face or on the phone. One LLM call per thing they say."""

    def __init__(self, user, dept, system, labels=None, on_event=None):
        self.user, self.dept, self.system = user, dept, system
        self.labels = {"org": "external", **(labels or {})}
        self.on_event = on_event or (lambda kind, **data: None)
        self.session = None

    def say(self, prompt):
        client, self.session = make_client(self.user, session_id=self.session, dept=self.dept, **self.labels)
        log = AgentLog(self.user, self.session, dept=self.dept, **self.labels)
        log.start(goal=prompt, model=MODEL)
        try:
            resp = chat(client, [{"role": "system", "content": self.system}, {"role": "user", "content": prompt}],
                        log=log)
        except APIError:
            log.end(status="error")
            return None
        self.on_event("llm_call", session=self.session)
        text = (resp.choices[0].message.content or "").strip()
        text = re.sub(r"^\s*subject:.*\n", "", text, flags=re.I).strip().strip('"').strip()
        log.end(answer=text, status="blocked" if log.blocked else "done")
        return text
