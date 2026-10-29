"""The actors of the workday: employees, simulated customers, BMW's dealer desk.

Every actor talks to the LLM through the shared layer (llm.make_client / llm.chat), so every call goes
through the proxy with X-Agent-* labels, is logged, inspected by the firewall and paced by the gateway.
Every actor also keeps its own client-side log (llm.AgentLog -> logs/agents/<agent>.jsonl).

Employees get their persona's tools (systems.tools.Toolset) plus one runner tool, `message_colleague`,
an internal team chat. Tool calls that reach other people (team chat, email to a colleague, a customer
or BMW) are handed to the runner's bus, which wakes the recipient.
"""
import json
import re

from openai import APIError

from llm import MODEL, AgentLog, chat, make_client
from systems.common import Store, now, persona_by_email, personas
from systems.persona_agent import system_prompt
from systems.tools import Toolset

TOOL_RESULT_MAX = 4000

CHAT_TOOL = {"type": "function", "function": {
    "name": "message_colleague",
    "description": "[team chat] Instant message to a colleague for a quick question, an approval nudge or a "
                   "handoff. They see it within minutes. Use their staff id (e.g. daniel-reed).",
    "parameters": {"type": "object", "properties": {
        "to": {"type": "string", "description": "Colleague's staff id"},
        "message": {"type": "string", "description": "What you want to say"}},
        "required": ["to", "message"]}}}

TEAM_CHAT_NOTE = (
    "Besides your systems you have team chat (message_colleague) to reach any colleague quickly; technicians "
    "and others without email use it to ask for approvals and handoffs. Staff ids: "
    "{ids}. Message a colleague only when they need to act, decide or know something new; never send "
    "thank-you, noted or acknowledgement-only messages. Keep each task short: a few tool calls, then a one or "
    "two sentence summary.")


def _labels(task, **extra):
    out = {"kind": task.kind, "task": task.id, "sim_time": task.sim_time, "title": task.title}
    if task.incident:
        out["incident"] = task.incident
    out.update(extra)
    return out


def _content(msg):
    return (msg.content or "").strip()


class StaffAgent:
    """One employee working one task: a fresh LLM session, up to max_turns model calls per user turn."""

    def __init__(self, persona_id, bus, max_turns=8):
        self.p = personas()[persona_id]
        self.id = persona_id
        self.bus = bus
        self.tools = Toolset(persona_id)
        self.max_turns = max_turns
        self.respond = None          # callable(answer) -> next user message or None (live conversations)

    def system(self):
        ids = ", ".join(f"{pid} ({p['role']})" for pid, p in personas().items() if pid != self.id)
        return system_prompt(self.p) + "\n\n" + TEAM_CHAT_NOTE.format(ids=ids)

    def run(self, task):
        labels = _labels(task, role=self.p["role"], department=self.p["department"])
        client, session = make_client(self.id, **labels)
        log = AgentLog(self.id, session, **labels)
        log.start(goal=task.goal, model=MODEL)
        self.bus.event("session_start", task, agent=self.id, session=session)
        messages = [{"role": "system", "content": self.system()}, {"role": "user", "content": task.goal}]
        out = {"session": session, "agent": self.id, "calls": 0, "tools": [], "answers": [], "status": "done"}
        pending = list(task.followups)
        answer = self._loop(client, messages, log, task, session, out)
        out["answers"].append(answer)
        while not log.blocked and out["status"] == "done":
            # what the employee says next: a scripted follow-up, or the customer's live reply
            follow = pending.pop(0) if pending else (self.respond(answer) if self.respond else None)
            if not follow:
                break
            messages.append({"role": "user", "content": follow})
            self.bus.event("followup", task, agent=self.id, session=session, text=follow)
            answer = self._loop(client, messages, log, task, session, out)
            out["answers"].append(answer)
        if log.blocked:
            out["status"] = "blocked"
            out["firewall"] = log.blocked
        log.end(answer=out["answers"][-1] if out["answers"] else None, status=out["status"])
        return out

    def _loop(self, client, messages, log, task, session, out):
        for _ in range(self.max_turns):
            try:
                resp = chat(client, messages, tools=self.tools.specs + [CHAT_TOOL], log=log)
            except APIError as e:
                out["status"] = "error"
                out["error"] = f"{type(e).__name__}: {e}"[:300]
                return None
            out["calls"] += 1
            self.bus.count_call()
            msg = resp.choices[0].message
            messages.append(msg.model_dump(exclude_none=True))
            if log.blocked:
                self.bus.event("blocked", task, agent=self.id, session=session, firewall=log.blocked,
                               text=_content(msg)[:400])
                return _content(msg)
            if not msg.tool_calls:
                return _content(msg)
            for c in msg.tool_calls:
                result = self.call_tool(c.function.name, c.function.arguments, task, session)
                log.tool(c.function.name, c.function.arguments, result)
                out["tools"].append(c.function.name)
                messages.append({"role": "tool", "tool_call_id": c.id, "content": result[:TOOL_RESULT_MAX]})
        out["status"] = "turn_limit"
        return None

    def call_tool(self, name, args, task, session):
        if name == "message_colleague":
            try:
                a = json.loads(args or "{}") if isinstance(args, str) else (args or {})
            except json.JSONDecodeError as e:
                return json.dumps({"error": f"arguments are not valid JSON: {e}"})
            to = str(a.get("to", "")).strip().lower().replace(" ", "-")
            to = next((pid for pid, p in personas().items() if to in (pid, p["email"], p["name"].lower().replace(" ", "-"))), to)
            if to not in personas() or to == self.id:
                return json.dumps({"error": f"unknown colleague {a.get('to')}; use a staff id"})
            self.bus.team_chat(task, self.id, to, str(a.get("message", "")), session)
            return json.dumps({"delivered": True, "to": to})
        result = self.tools.call(name, args)
        if name == "mail_send":
            try:
                r = json.loads(result)
                a = json.loads(args) if isinstance(args, str) else args
            except (json.JSONDecodeError, TypeError):
                r = {}
            if "msg_id" in r:
                self.bus.mail_sent(task, self.id, r, a or {}, session)
        return result


class TalkerAgent:
    """An actor with no tools that only writes messages: a simulated customer or BMW's dealer desk."""

    def __init__(self, agent_id, system, department, role, bus):
        self.id, self.system, self.department, self.role, self.bus = agent_id, system, department, role, bus

    def say(self, task, prompt):
        labels = _labels(task, role=self.role, department=self.department, simulated="yes")
        client, session = make_client(self.id, **labels)
        log = AgentLog(self.id, session, **labels)
        log.start(goal=prompt, model=MODEL)
        messages = [{"role": "system", "content": self.system}, {"role": "user", "content": prompt}]
        try:
            resp = chat(client, messages, log=log)
        except APIError as e:
            log.end(status="error")
            return None, session
        self.bus.count_call()
        text = _strip(_content(resp.choices[0].message))
        log.end(answer=text, status="blocked" if log.blocked else "done")
        return text, session


def _strip(text):
    """Talkers sometimes wrap their message in quotes or add a 'Subject:' line; keep the message."""
    text = re.sub(r"^\s*subject:.*\n", "", text, flags=re.I).strip()
    return text.strip('"').strip()


def customer_system(c):
    return (f"You are {c['name']}, a customer of VXC Motors, a BMW dealership in Reading, UK. {c['brief']} "
            "You are a person, not an assistant: write only what you say or write to the dealership, in the "
            "first person, two to five sentences, no headings, no placeholders. If an email from the dealership "
            "needs no answer (it only confirms what you already agreed), write exactly NO_REPLY. Today is "
            f"{now():%A %d %B %Y}.")


BMW_DESK_SYSTEM = (
    "You are the BMW UK Retailer Support desk (and, when addressed, the BMW Area Manager South, Claire Dunn). "
    "You answer emails from VXC Motors, a BMW dealer in Reading (dealer number GB-40712). Be brief, factual "
    "and polite, two to five sentences, sign as 'BMW UK Retailer Support' or 'Claire Dunn'. You do not invent "
    "order numbers or VINs; refer to the Partner Portal for live status.")


# ---------------------------------------------------------------- customers in the CRM

def find_customer(fuel=None, exclude=()):
    """A real customer (with a car) from the CRM, so the employee can find them in the systems."""
    st = Store.get("internal")
    with st.lock:
        rows = st.con.execute(
            "SELECT c.customer_id, c.first_name, c.last_name, c.email, v.vin, v.model, v.reg "
            "FROM customers c JOIN customer_vehicles v USING (customer_id) "
            "WHERE (? IS NULL OR v.fuel = ?) ORDER BY c.customer_id", [fuel, fuel]).fetchall()
    for r in rows[7::13]:                         # deterministic, spread out
        if r[0] not in exclude:
            return {"customer_id": r[0], "name": f"{r[1]} {r[2]}", "email": r[3], "vin": r[4],
                    "car": f"{r[5]} ({r[6]})"}
    return None


def customer_by_email(email):
    st = Store.get("internal")
    with st.lock:
        r = st.con.execute("SELECT customer_id, first_name, last_name FROM customers WHERE email = ?", [email]).fetchone()
    return {"customer_id": r[0], "name": f"{r[1]} {r[2]}"} if r else None


def deliver_mail(from_addr, to_addr, subject, body, reply_to=None):
    """Put an email from someone outside the company into an employee's inbox (as the mail system would)."""
    st = Store.get("internal")
    with st.lock:
        cur = st.con.cursor()
        n = cur.execute("SELECT max(CAST(substr(msg_id, 5) AS INTEGER)) FROM messages WHERE msg_id LIKE 'MSG-%'").fetchone()[0] or 0
        mid = f"MSG-{n + 1:06d}"
        thread = mid
        if reply_to:
            thread = (cur.execute("SELECT thread_id FROM messages WHERE msg_id = ?", [reply_to]).fetchone() or [mid])[0]
        cur.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?)",
                    [mid, thread, from_addr, to_addr, None, subject, body, now(), None])
        cur.close()
    return mid


def staff_by_email(email):
    p = persona_by_email(email)
    return p["id"] if p else None
