"""Run the VXC Motors workday: every employee, customer and BMW contact is an agent.

    python -m sim.run --plan                     # print the timeline, no LLM calls
    python -m sim.run                            # the whole day, live, through the proxy
    python -m sim.run --until 10:00 --max-calls 120

What runs
  * the proxy (proxy/proxy.py) on :8080: logging, firewall, gateway (rate limit, fallback, spend cap);
  * the applications (apps/server.py) on :8100 (VXC internal) and :8200 (BMW portal), a separate process;
  * this process: the "director". It owns the simulated clock and the day's script, starts agents,
    and rings the doorbell when mail or chat arrives. It never reads or writes business data itself.

How a day unfolds
  * sim/day.py lists the day's events at simulated times. Each becomes a Task in a time-ordered queue.
  * A few worker threads take tasks in time order. The clock (POST /clock on the services) moves to
    each task's time; it never runs more than SPREAD minutes ahead of the oldest running task.
    One person works one task at a time.
  * Agents reach each other only through the applications: an agent's LLM asks for mail_send or
    chat_send, the agent runs that tool call, the message is stored in the mail or chat service.
  * The Watcher polls GET /events (who sent what to whom, never the text). For each new message it
    wakes the recipient a few simulated minutes later with "you have a new email / chat message";
    the recipient reads it with a tool call, so the text reaches the recipient's LLM through the proxy.
    Email to a customer or to BMW wakes that outside party's agent, who answers by mail_send too.
    Chains stop after MAX_DEPTH hops; later messages wait for the person's next task.
  * Output: logs/workday/ (proxy.db, gateway.db, agents/*.jsonl, runner.jsonl). sim/export.py
    snapshots it into runs/<name>/ and demo/data/.
"""
import argparse
import heapq
import itertools
import json
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from dataclasses import dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.environ.get("VXC_RUN_DIR") or os.path.join(ROOT, "logs", "workday")

SPREAD = 25          # minutes the clock may run ahead of the oldest running task
WAKE_DELAY = 6       # minutes before a colleague reacts to a message
REPLY_DELAY = 20     # minutes before a customer or BMW answers an email
MAX_DEPTH = 3        # hops in one chain of messages before wakes stop
MAX_EXTERNAL_REPLIES = 2


def hm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def mins(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _http(url, payload=None, timeout=30):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"},
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


@dataclass
class Task:
    id: str
    kind: str                     # staff | customer | inbound | reply | admin
    at: int                       # simulated minutes since midnight
    actor: str = None
    title: str = ""
    goal: str = ""
    followups: list = field(default_factory=list)
    incident: str = None
    depth: int = 0
    data: dict = field(default_factory=dict)
    sim_time: str = ""

    def __lt__(self, other):
        return self.at < other.at


class Bus:
    """Shared state of the run: the clock, the queue, who is busy, the runner log, the call counter."""

    def __init__(self, date, max_calls, reserve):
        from agents.toolclient import services
        self.date, self.max_calls, self.reserve = date, max_calls, reserve
        self.urls = services()
        self.cv = threading.Condition()
        self.queue, self.seq = [], itertools.count(1)
        self.clock = 0
        self.running = {}            # task id -> Task
        self.busy = set()            # actors working right now
        self.last_task = {}          # actor -> their latest task (depth of message chains)
        self.notes = {}              # actor -> doorbells waiting for their next task
        self.inbound = {}            # msg_id -> scripted inbound email's labels (incident, title)
        self.calls = 0
        self.stopped = None
        self.external_replies = {}
        self.results = []
        self.watcher = None
        os.makedirs(OUT, exist_ok=True)
        self.log_path = os.path.join(OUT, "runner.jsonl")
        self.log_lock = threading.Lock()

    # ---- runner log ---------------------------------------------------------------------------
    def event(self, kind, task=None, **data):
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z", "sim": hm(self.clock),
               "event": kind}
        if task:
            row.update(task=task.id, task_kind=task.kind, actor=task.actor, title=task.title)
            if task.incident:
                row["incident"] = task.incident
        row.update(data)
        with self.log_lock, open(self.log_path, "a") as f:
            f.write(json.dumps(row, default=str) + "\n")
        brief = data.get("text") or data.get("status") or data.get("tool") or ""
        if not brief and data.get("to"):
            brief = f"{data.get('frm')} -> {data['to']} {data.get('subject') or data.get('chat_id') or ''}"
        print(f"[{hm(self.clock)}] {kind:<14} {(task.actor if task else '') or '':<22} "
              f"{(task.title if task else '')[:36]:<36} {str(brief)[:90]}", flush=True)

    def hook(self, task):
        """What an agent reports back while it works (for counting and for the timeline)."""
        def on_event(kind, **data):
            if kind == "llm_call":
                with self.cv:
                    self.calls += 1
                return
            if kind == "tool":
                self.event("tool", task, **data)
            elif kind in ("session_start", "blocked", "followup"):
                self.event(kind, task, **data)
        return on_event

    # ---- clock ---------------------------------------------------------------------------------
    def set_clock(self, minutes):
        self.clock = max(self.clock, minutes)
        now = f"{self.date}T{hm(self.clock)}:00"
        os.environ["VXC_NOW"] = now
        for url in self.urls.values():
            _http(url.rstrip("/") + "/clock", {"now": now})

    # ---- queue --------------------------------------------------------------------------------
    def add(self, task):
        with self.cv:
            task.id = task.id or f"T{next(self.seq):03d}"
            task.sim_time = hm(task.at)
            heapq.heappush(self.queue, (task.at, next(self.seq), task))
            self.cv.notify_all()

    def wake(self, actor, note, depth, delay=WAKE_DELAY, title=None, labels=None, sent=None):
        """Ring `actor`'s doorbell `delay` minutes after the message was sent. Merged into a pending wake."""
        labels = labels or {}
        if depth > MAX_DEPTH and not labels.get("incident"):
            self.notes.setdefault(actor, []).append(note)
            self.event("deferred", None, to=actor, text=note[:200])
            return
        with self.cv:
            for _, _, t in self.queue:
                if t.actor == actor and t.kind == "staff" and t.data.get("wake") and not labels.get("incident"):
                    t.goal += "\n" + note
                    t.depth = min(t.depth, depth)
                    return
        self.add(Task(id=None, kind="staff", at=(sent if sent is not None else self.clock) + delay, actor=actor,
                      depth=depth,
                      title=labels.get("title") or title or "Reacts to a message", goal=note,
                      incident=labels.get("incident"), data={"wake": True, "expect": labels.get("expect")}))

    def origin_depth(self, actor):
        t = self.last_task.get(actor)
        return (t.depth if t else 0) + 1

    def take_notes(self, actor):
        return self.notes.pop(actor, [])

    # ---- scheduling ---------------------------------------------------------------------------
    def next_task(self):
        with self.cv:
            while True:
                if self.stopped and not self.running:
                    return None
                if not self.queue and not self.running:
                    return None
                oldest = min((t.at for t in self.running.values()), default=None)
                pick = None
                if not self.stopped:
                    for at, _, t in sorted(self.queue):
                        if oldest is not None and at > max(oldest, self.clock) + SPREAD:
                            break
                        if t.actor and t.actor in self.busy:
                            continue
                        pick = t
                        break
                if pick:
                    self.queue = [q for q in self.queue if q[2] is not pick]
                    heapq.heapify(self.queue)
                    self.set_clock(pick.at)
                    self.running[pick.id] = pick
                    if pick.actor:
                        self.busy.add(pick.actor)
                        self.last_task[pick.actor] = pick
                    return pick
                self.cv.wait(timeout=2)

    def done(self, task):
        with self.cv:
            self.running.pop(task.id, None)
            self.busy.discard(task.actor)
            self.cv.notify_all()

    def check_budget(self):
        if self.stopped:
            return
        if self.calls >= self.max_calls:
            self.stop(f"max calls reached ({self.calls})")
            return
        try:
            from llm import gateway_status
            st = gateway_status()
            daily = (st.get("free") or {}).get("daily") or {}
            left = (daily.get("remaining") or 0) - ((st.get("free") or {}).get("since_last_read") or 0)
            if daily and self.reserve and left < self.reserve:
                self.stop(f"free daily requests low ({left} left, reserve {self.reserve})")
        except OSError:
            pass

    def stop(self, why):
        with self.cv:
            if not self.stopped:
                self.stopped = why
                self.event("stopped", text=why)
                self.cv.notify_all()


# ---------------------------------------------------------------- the doorbell

class Watcher(threading.Thread):
    """Polls the mail and chat services for new messages and wakes whoever they are for.

    It sees who wrote to whom and the subject line, never the body: the recipient's agent reads that
    with a tool call. This is the only way agents learn about each other's actions."""

    def __init__(self, bus):
        super().__init__(daemon=True, name="watcher")
        self.bus = bus
        self.url = bus.urls["internal"].rstrip("/") + "/events"
        start = _http(self.url + "?mail_after=0&chat_after=0")
        self.mail_after = max((m["seq"] for m in start["mail"]), default=0)
        self.chat_after = max((c["seq"] for c in start["chat"]), default=0)
        self.stop_flag = threading.Event()
        self.lock = threading.Lock()

    def run(self):
        while not self.stop_flag.wait(1.0):
            self.poll()

    def poll(self):
        """Also called by a worker right after each task, so a message is never noticed late."""
        with self.lock:
            try:
                ev = _http(f"{self.url}?mail_after={self.mail_after}&chat_after={self.chat_after}")
            except OSError:
                return
            for m in ev["mail"]:
                self.mail_after = max(self.mail_after, m["seq"])
                try:
                    self.on_mail(m)
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
            for c in ev["chat"]:
                self.chat_after = max(self.chat_after, c["seq"])
                self.on_chat(c)

    @staticmethod
    def sent_minute(row):
        t = row.get("sent_at") or ""
        return mins(t[11:16]) if len(t) >= 16 else None

    def on_chat(self, c):
        from apps.common import personas
        name = personas()[c["from"]]["name"]
        self.bus.event("chat", None, frm=c["from"], to=c["to"], chat_id=c["chat_id"])
        self.bus.wake(c["to"], f"New team chat message {c['chat_id']} from {name} ({c['from']}). "
                               "Read it with chat_unread and act on it.",
                      self.bus.origin_depth(c["from"]), title=f"Chat from {name.split()[0]}", sent=self.sent_minute(c))

    def on_mail(self, m):
        from apps.common import persona_by_email
        bus = self.bus
        sender = persona_by_email(m["from"])
        recipient = persona_by_email(m["to"])
        frm_actor = sender["id"] if sender else external_user(m["from"])
        depth = bus.origin_depth(frm_actor)
        labels = bus.inbound.pop(m["msg_id"], None)
        bus.event("mail", None, frm=m["from"], to=m["to"], msg_id=m["msg_id"], subject=m["subject"])
        who = sender["name"] if sender else m["from"]
        doorbell = (f"New email {m['msg_id']} from {who} ({m['from']}), subject \"{m['subject']}\". "
                    "Read it with mail_read and act on it.")
        if recipient:
            if not sender or sender["id"] != recipient["id"]:
                bus.wake(recipient["id"], doorbell, 0 if labels else depth, title=f"Email from {who.split()[0]}",
                         labels=labels, sent=self.sent_minute(m))
            return
        # an outside address: a customer, BMW, or someone with no agent (e.g. Gary, a recruiter)
        party = external_party(m["to"], m.get("to_customer"))
        if not party or not sender:
            bus.event("external_mail", None, frm=m["from"], to=m["to"], subject=m["subject"])
            return
        n = bus.external_replies.get(m["to"], 0)
        if n >= MAX_EXTERNAL_REPLIES or depth > MAX_DEPTH:
            return
        bus.external_replies[m["to"]] = n + 1
        sent = self.sent_minute(m)
        bus.add(Task(id=None, kind="reply", at=(bus.clock if sent is None else sent) + REPLY_DELAY,
                     actor=party["user"], depth=depth,
                     title=f"{party['name']} answers {sender['name'].split()[0]}",
                     goal=doorbell, data={"party": party}))


def external_user(addr):
    from agents.external import slug
    if addr.endswith("@bmw.example"):
        return "bmw-retailer-support"
    return "customer-" + slug(addr.split("@")[0])


def external_party(addr, crm_name=None):
    """The outside agent behind an address, or None if nobody answers there."""
    from agents.prompts import BMW_DESK, customer_prompt
    from sim import day
    if addr.endswith("@bmw.example"):
        return {"user": "bmw-retailer-support", "name": "BMW UK", "dept": "BMW UK", "email": addr,
                "system": BMW_DESK}
    spec = next((c for c in day.CUSTOMERS.values() if c.get("email") == addr), None)
    if not spec and crm_name:
        spec = {"name": crm_name, "email": addr,
                "brief": "An existing customer of the dealership; reasonable, wants clear answers."}
    if not spec:
        return None
    return {"user": external_user(addr), "name": spec["name"], "dept": "Customers", "email": addr,
            "system": customer_prompt(spec)}


# ---------------------------------------------------------------- task execution

def labels_for(task, **extra):
    out = {"kind": task.kind, "task": task.id, "sim_time": task.sim_time, "title": task.title}
    if task.incident:
        out["incident"] = task.incident
    out.update(extra)
    return out


def run_task(bus, task):
    if task.kind == "admin":
        return run_admin(bus, task)
    if task.kind == "inbound":
        return run_inbound(bus, task)
    if task.kind == "customer":
        return run_customer(bus, task)
    if task.kind == "reply":
        return run_reply(bus, task)
    return run_staff(bus, task)


def run_staff(bus, task, respond=None):
    from agents.staff import StaffAgent
    notes = bus.take_notes(task.actor)
    if notes:
        task.goal += "\n\nAlso waiting for you:\n" + "\n".join(f"- {n}" for n in notes)
    agent = StaffAgent(task.actor, labels=labels_for(task), on_event=bus.hook(task))
    agent.respond = respond
    bus.event("task_start", task, text=task.goal[:300])
    out = agent.run(task.goal, task.followups)
    bus.event("task_end", task, session=out["session"], status=out["status"], calls=out["calls"],
              tools=out["tools"], text=(out["answers"][-1] or "") if out["answers"] else "",
              firewall=out.get("firewall"), error=out.get("error"))
    return out


def run_inbound(bus, task):
    """A scripted email from outside (a recruiter, BMW's area manager) lands in the mailbox: it is sent
    through the mail service as that outside address. The Watcher then rings the recipient's doorbell."""
    from apps.common import external_actor, personas
    d = task.data
    to = personas()[task.actor]["email"]
    res = _http(bus.urls["internal"].rstrip("/") + "/call",
                {"actor": external_actor(d["from"]), "tool": "mail_send",
                 "args": {"to": to, "subject": d["subject"], "body": d["body"]}})
    if "msg_id" in res:
        bus.inbound[res["msg_id"]] = {"incident": task.incident, "title": task.title, "expect": d.get("expect")}
    bus.event("inbound_mail", task, frm=d["from"], to=to, msg_id=res.get("msg_id"), subject=d["subject"])
    return {"status": "done" if "msg_id" in res else "error"}


def run_customer(bus, task):
    """A customer starts a conversation: in person / on the phone (a Talker), or by email (a MailAgent)."""
    from agents.external import MailAgent, Talker, slug
    from agents.prompts import customer_prompt, customer_talk_prompt
    from apps.common import personas
    from sim import day
    spec = dict(day.CUSTOMERS[task.data["customer"]])
    if spec.get("db"):
        spec.update(_http(f"{bus.urls['internal'].rstrip('/')}/sim/customer?fuel={spec.get('fuel', '')}") or {})
    staff = personas()[task.actor]
    user = "customer-" + slug(spec["name"])
    car = f" Your car: {spec['car']}." if spec.get("car") else ""
    if task.data["channel"] == "email":
        agent = MailAgent(user, "Customers", spec["email"], customer_prompt(spec),
                          labels=labels_for(task, role="customer"), on_event=bus.hook(task))
        bus.event("task_start", task, text=f"{spec['name']} writes to {staff['name']}")
        out = agent.run(f"Write an email to {staff['name']} ({staff['email']}), {staff['role']} at VXC Motors.{car} "
                        f"{spec.get('ask', '')}")
        bus.event("task_end", task, session=out["session"], status=out["status"], calls=out["calls"],
                  tools=out["tools"], text=out.get("answer") or "")
        return out
    talker = Talker(user, "Customers", customer_talk_prompt(spec), labels=labels_for(task, role="customer"),
                    on_event=bus.hook(task))
    opening = talker.say(f"You are making contact by {task.data['channel']} with {staff['name']}, "
                         f"{staff['role']}.{car} Say what you want.")
    if not opening:
        bus.event("task_end", task, status="error", text="customer agent got no answer")
        return {"status": "error"}
    who = f"{spec['name']} ({spec.get('email', 'no email yet')}{', ' + spec['phone'] if spec.get('phone') else ''})"
    bus.event("customer_says", task, customer=spec["name"], text=opening)
    task.goal = (f"{task.data['channel'].capitalize()}: {who} says:\n\"{opening}\"\n\nHelp them. Use your "
                 "applications as needed (find or create them in the CRM, check stock or bookings, book what is "
                 "agreed). Your final answer is what you say back to them.")
    rounds = [task.data.get("rounds", 1) - 1]
    transcript = [f"You: {opening}"]

    def respond(answer):
        if rounds[0] <= 0 or not answer:
            return None
        rounds[0] -= 1
        transcript.append(f"{staff['name']}: {answer}")
        text = talker.say("The conversation so far:\n" + "\n".join(transcript) +
                          "\n\nReply to them (or wrap up politely if you have what you need).")
        if not text:
            return None
        transcript.append(f"You: {text}")
        bus.event("customer_says", task, customer=spec["name"], text=text)
        return f"{spec['name']} replies: \"{text}\""

    return run_staff(bus, task, respond=respond)


def run_reply(bus, task):
    """An outside party (customer or BMW) got an email: their agent reads it and answers by mail_send."""
    from agents.external import MailAgent
    p = task.data["party"]
    agent = MailAgent(p["user"], p["dept"], p["email"], p["system"],
                      labels=labels_for(task, role="customer" if p["dept"] == "Customers" else "manufacturer"),
                      on_event=bus.hook(task))
    bus.event("task_start", task, text=task.goal[:300])
    out = agent.run(task.goal)
    bus.event("task_end", task, session=out["session"], status=out["status"], calls=out["calls"],
              tools=out["tools"], text=out.get("answer") or "")
    return out


def run_admin(bus, task):
    """The IT administrator: a note on every blocked session, a manual block on one warned session."""
    from llm import BASE_URL
    db = sqlite3.connect(os.environ["PROXY_LOG_DB"])
    try:
        blocked = db.execute("SELECT session, agent, topic, ref FROM admin_actions WHERE action='block_session' "
                             "AND actor='firewall'").fetchall()
        warned = db.execute("SELECT session, agent, topic FROM signals WHERE level='warning' AND session NOT IN "
                            "(SELECT session FROM admin_actions WHERE action='block_session') ORDER BY id").fetchall()
    finally:
        db.close()
    actor = "it-admin (simulated)"
    for session, agent, topic, ref in blocked:
        _admin(BASE_URL, session, "note", actor, f"Reviewed {ref}: {topic} by {agent}. Escalated to line manager "
                                                  "and Victor Hale; session stays closed.")
    if warned:
        session, agent, topic = warned[0]
        _admin(BASE_URL, session, "block", actor, f"Manual block after review: {topic} warning for {agent}, "
                                                   "pending a conversation with their manager.")
    bus.event("admin", task, text=f"{len(blocked)} notes on blocked sessions, "
                                  f"{1 if warned else 0} manual block", blocked=len(blocked))
    return {"status": "done"}


def _admin(base, session, action, actor, reason):
    try:
        return _http(f"{base.rstrip('/')}/firewall/sessions/{session}/{action}", {"actor": actor, "reason": reason})
    except OSError as e:
        return {"error": str(e)}


# ---------------------------------------------------------------- main

def load_tasks(until=None, only=None):
    from sim import day
    tasks = []
    for i, e in enumerate(day.EVENTS, 1):
        at = mins(e["at"])
        if until and at > mins(until):
            continue
        if only and e.get("actor") not in only and e["kind"] != "admin":
            continue
        data = {k: e[k] for k in ("customer", "channel", "rounds", "from", "subject", "body", "expect") if k in e}
        tasks.append(Task(id=f"E{i:02d}", kind=e["kind"], at=at, actor=e.get("actor"), title=e["title"],
                          goal=e.get("goal", ""), followups=e.get("followups", []), incident=e.get("incident"),
                          data=data))
    return tasks


def worker(bus):
    while True:
        task = bus.next_task()
        if task is None:
            return
        try:
            out = run_task(bus, task)
            bus.results.append({"task": task.id, "actor": task.actor, "title": task.title, "sim": task.sim_time,
                                "incident": task.incident, **{k: v for k, v in (out or {}).items()
                                                              if k in ("session", "status", "calls", "firewall")}})
        except Exception as e:  # noqa: BLE001  (one broken task must not stop the day)
            bus.event("task_error", task, text=f"{type(e).__name__}: {e}")
            traceback.print_exc()
        finally:
            if bus.watcher:
                bus.watcher.poll()
            bus.done(task)
            bus.check_budget()


def start_apps():
    """The applications run as their own process, like real services would."""
    from agents.toolclient import wait_ready
    env = {**os.environ, "AGENT_LOG_DIR": os.environ["AGENT_LOG_DIR"]}
    proc = subprocess.Popen([sys.executable, "-m", "apps.server"], cwd=ROOT, env=env,
                            stdout=open(os.path.join(OUT, "apps.log"), "a"), stderr=subprocess.STDOUT)
    wait_ready(120)
    return proc


def _sigterm(*_):
    raise KeyboardInterrupt   # `timeout` / kill: stop like Ctrl-C, so summary.json and day_end are still written


def main():
    signal.signal(signal.SIGTERM, _sigterm)
    ap = argparse.ArgumentParser(description="Run the VXC Motors multi-agent workday")
    ap.add_argument("--plan", action="store_true", help="print the timeline and exit")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-calls", type=int, default=650, help="stop starting tasks after this many agent LLM calls")
    ap.add_argument("--reserve", type=int, default=0,
                    help="stop when fewer free requests are left today (default 0: keep going on the paid fallback)")
    ap.add_argument("--until", help="only events up to HH:MM")
    ap.add_argument("--only", nargs="*", help="only these persona ids (plus the admin)")
    ap.add_argument("--keep", action="store_true", help="keep the applications' state and logs from a previous run")
    a = ap.parse_args()
    from sim import day
    tasks = load_tasks(a.until, a.only)
    if a.plan:
        for t in tasks:
            print(f"{hm(t.at)}  {t.kind:<8} {t.actor or '':<15} {t.incident or '':<6} {t.title}")
        return

    os.environ.setdefault("PROXY_LOG_DB", os.path.join(OUT, "proxy.db"))
    os.environ.setdefault("AGENT_LOG_DIR", os.path.join(OUT, "agents"))
    os.environ.setdefault("FIREWALL_TOPICS", os.path.join(ROOT, "proxy", "firewall_topics.yaml"))
    if not a.keep:
        reset()
    os.makedirs(OUT, exist_ok=True)
    os.environ["VXC_NOW"] = f"{day.DATE}T07:45:00"
    apps = start_apps()
    from llm import start_proxy
    proxy = start_proxy(PROXY_LOG_DB=os.environ["PROXY_LOG_DB"], GATEWAY_DB=os.path.join(OUT, "gateway.db"),
                        GATEWAY_SPEND_CAP_USD=os.environ.get("GATEWAY_SPEND_CAP_USD", "4"))
    bus = Bus(day.DATE, a.max_calls, a.reserve)
    watcher = bus.watcher = Watcher(bus)
    watcher.start()
    bus.event("day_start", text=f"{len(tasks)} scripted events, {a.workers} workers")
    for t in tasks:
        bus.add(t)
    bus.check_budget()
    started = time.time()
    threads = [threading.Thread(target=worker, args=(bus,), daemon=True) for _ in range(a.workers)]
    for th in threads:
        th.start()
    try:
        for th in threads:
            th.join()
        time.sleep(2)   # let the watcher log the last messages
    except KeyboardInterrupt:
        bus.stop("interrupted")
        for th in threads:
            th.join(timeout=600)
    watcher.stop_flag.set()
    left = [t.title for _, _, t in bus.queue]
    summary = {"date": day.DATE, "calls": bus.calls, "minutes": round((time.time() - started) / 60, 1),
               "stopped": bus.stopped, "tasks": bus.results, "not_started": left}
    bus.event("day_end", text=f"{bus.calls} agent LLM calls in {summary['minutes']} min", not_started=len(left))
    with open(os.path.join(OUT, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)
    apps.terminate()
    apps.wait(timeout=30)
    if proxy:
        proxy.terminate()


def reset():
    """Fresh applications (reseeded to the 07:45 morning) and empty workday logs."""
    import shutil
    from apps.common import DATA, DB_FILES
    for f in DB_FILES.values():
        for suffix in ("", ".wal"):
            p = DATA / (f + suffix)
            if p.exists():
                p.unlink()
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)
    from apps import seed
    seed.build(parquet=False)


if __name__ == "__main__":
    sys.exit(main())
