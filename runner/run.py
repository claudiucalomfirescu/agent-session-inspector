"""Run the VXC Motors workday: every employee as an agent, customers, BMW, staged incidents (lesson 6).

    python -m runner.run --plan                 # print the timeline, no LLM calls
    python -m runner.run                        # the whole day, live, through the proxy
    python -m runner.run --until 10:00 --workers 3 --max-calls 120

How it works
  * runner/day.py lists the day's events at simulated times. Each becomes a Task in a time-ordered queue.
  * A small pool of worker threads takes tasks in time order. The simulation clock (VXC_NOW, read by
    the systems) moves forward to each task's time; it never runs more than SPREAD minutes ahead of
    the oldest task still being worked, so the day unfolds roughly in order. One person works one
    task at a time.
  * Agents reach each other through the Bus: team chat or email to a colleague wakes the colleague a
    few simulated minutes later (several messages waiting for the same person are merged into one
    task); email to a customer or to BMW wakes their agent, whose reply lands in the inbox and wakes
    the employee again. Chains stop after MAX_DEPTH hops; later messages wait for the person's next task.
  * Pacing is the gateway's job (<= 16 requests/min across all agents, in the proxy). The runner only
    keeps the total in check: it stops starting new tasks when --max-calls is reached or the free
    daily allowance (GET /api/v1/key via the gateway) drops below --reserve.
  * Output: logs/workday/ (proxy.db, gateway.db, agents/*.jsonl) and logs/workday/runner.jsonl, the
    runner's own timeline (task start/end, messages, wakes, blocks). runner/export.py snapshots it.
"""
import argparse
import heapq
import itertools
import json
import os
import sqlite3
import sys
import threading
import time
import traceback
import urllib.request
from dataclasses import dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "logs", "workday")

SPREAD = 25          # minutes the clock may run ahead of the oldest running task
WAKE_DELAY = 6       # minutes before a colleague reacts to a message
REPLY_DELAY = 20     # minutes before a customer or BMW answers an email
MAX_DEPTH = 3        # hops in one chain of messages before wakes stop
MAX_CUSTOMER_REPLIES = 2


def hm(minutes):
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def mins(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


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

    def __init__(self, date, max_calls, reserve, workers):
        self.date, self.max_calls, self.reserve, self.workers = date, max_calls, reserve, workers
        self.cv = threading.Condition()
        self.queue, self.seq = [], itertools.count(1)
        self.clock = 0
        self.running = {}            # task id -> Task
        self.busy = set()            # actors working right now
        self.notes = {}              # actor -> messages waiting for their next task
        self.calls = 0
        self.stopped = None
        self.customer_replies = {}
        self.results = []
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
        brief = data.get("text") or data.get("status") or ""
        print(f"[{hm(self.clock)}] {kind:<14} {(task.actor if task else '') or '':<16} "
              f"{(task.title if task else '')[:40]:<40} {str(brief)[:90]}", flush=True)

    def count_call(self):
        with self.cv:
            self.calls += 1

    # ---- queue --------------------------------------------------------------------------------
    def add(self, task):
        with self.cv:
            task.id = task.id or f"T{next(self.seq):03d}"
            task.sim_time = hm(task.at)
            heapq.heappush(self.queue, (task.at, next(self.seq), task))
            self.cv.notify_all()

    def wake(self, origin, actor, note, delay=WAKE_DELAY, title=None):
        """Give `actor` something to react to. Merged into a pending wake if there is one."""
        depth = origin.depth + 1
        if depth > MAX_DEPTH:
            self.notes.setdefault(actor, []).append(note)
            self.event("deferred", origin, to=actor, text=note[:200])
            return
        with self.cv:
            for _, _, t in self.queue:
                if t.actor == actor and t.kind == "staff" and t.data.get("wake"):
                    t.goal += "\n\n" + note
                    t.depth = min(t.depth, depth)
                    return
        self.add(Task(id=None, kind="staff", at=self.clock + delay, actor=actor, depth=depth,
                      title=title or "Reacts to a message", goal=note, data={"wake": True, "origin": origin.id}))

    # ---- what agents do to each other ---------------------------------------------------------
    def team_chat(self, task, frm, to, text, session):
        from systems.common import personas
        self.event("team_chat", task, frm=frm, to=to, session=session, text=text)
        name = personas()[frm]["name"]
        self.wake(task, to, f"Team chat from {name} ({frm}): \"{text}\"\nReply or act on it as needed.",
                  title=f"Chat from {name.split()[0]}")

    def mail_sent(self, task, frm, result, args, session):
        from runner.actors import customer_by_email, staff_by_email
        from systems.common import personas
        to = result.get("to", "")
        self.event("mail", task, frm=frm, to=to, session=session, msg_id=result.get("msg_id"),
                   subject=args.get("subject"), text=(args.get("body") or "")[:300])
        name = personas()[frm]["name"]
        staff = staff_by_email(to)
        if staff and staff != frm:
            self.wake(task, staff, f"New email {result['msg_id']} from {name}: \"{args.get('subject', '')}\". "
                                   "Read it and act on it.", title=f"Email from {name.split()[0]}")
            return
        if to.endswith("@bmw.example"):
            self._reply_task(task, "bmw", to, frm, result, args)
            return
        cust = customer_by_email(to) or next(({"name": c["name"]} for c in _day().CUSTOMERS.values()
                                             if c.get("email") == to), None)
        if cust:
            n = self.customer_replies.get(to, 0)
            if n < MAX_CUSTOMER_REPLIES:
                self.customer_replies[to] = n + 1
                self._reply_task(task, "customer", to, frm, result, args, name=cust["name"])
            return
        self.event("external_mail", task, frm=frm, to=to, text=(args.get("body") or "")[:300])

    def _reply_task(self, origin, who, addr, staff, result, args, name=None):
        if origin.depth + 1 > MAX_DEPTH:
            return
        self.add(Task(id=None, kind="reply", at=self.clock + REPLY_DELAY, actor=staff, depth=origin.depth + 1,
                      title=f"{'BMW' if who == 'bmw' else name} replies",
                      data={"who": who, "addr": addr, "name": name, "msg_id": result.get("msg_id"),
                            "subject": args.get("subject", ""), "body": args.get("body", "")}))

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
                    for i, (at, _, t) in enumerate(sorted(self.queue)):
                        if oldest is not None and at > max(oldest, self.clock) + SPREAD:
                            break
                        if t.actor and t.actor in self.busy:
                            continue
                        pick = t
                        break
                if pick:
                    self.queue = [q for q in self.queue if q[2] is not pick]
                    heapq.heapify(self.queue)
                    self.clock = max(self.clock, pick.at)
                    os.environ["VXC_NOW"] = f"{self.date}T{hm(self.clock)}:00"
                    self.running[pick.id] = pick
                    if pick.actor:
                        self.busy.add(pick.actor)
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


def _day():
    from runner import day
    return day


# ---------------------------------------------------------------- task execution

def run_task(bus, task):
    from runner import actors
    from systems.common import personas
    kind = task.kind
    if kind == "admin":
        return run_admin(bus, task)
    if kind == "inbound":
        to = personas()[task.actor]["email"]
        mid = actors.deliver_mail(task.data["from"], to, task.data["subject"], task.data["body"])
        bus.event("inbound_mail", task, frm=task.data["from"], to=to, msg_id=mid, subject=task.data["subject"],
                  text=task.data["body"][:300])
        task.goal = f"{task.data['wake']} (email {mid} from {task.data['from']})"
        return run_staff(bus, task)
    if kind == "customer":
        return run_customer(bus, task)
    if kind == "reply":
        return run_reply(bus, task)
    return run_staff(bus, task)


def run_staff(bus, task, respond=None):
    from runner.actors import StaffAgent
    notes = bus.take_notes(task.actor)
    if notes:
        task.goal += "\n\nAlso waiting for you:\n" + "\n".join(f"- {n}" for n in notes)
    agent = StaffAgent(task.actor, bus)
    if respond:
        agent.respond = respond
    bus.event("task_start", task, text=task.goal[:300])
    out = agent.run(task)
    bus.event("task_end", task, session=out["session"], status=out["status"], calls=out["calls"],
              tools=out["tools"], text=(out["answers"][-1] or "") if out["answers"] else "",
              firewall=out.get("firewall"), error=out.get("error"))
    return out


def run_customer(bus, task):
    from runner import actors
    from systems.common import personas
    day = _day()
    spec = dict(day.CUSTOMERS[task.data["customer"]])
    if spec.get("db"):
        found = actors.find_customer(spec.get("fuel"))
        spec.update(found or {})
    staff = personas()[task.actor]
    talker = actors.TalkerAgent(f"customer-{task.data['customer']}", actors.customer_system(spec),
                                "Customers", "customer", bus)
    car = f" Your car: {spec['car']}." if spec.get("car") else ""
    opening, _ = talker.say(task, f"You are making contact by {task.data['channel']} with {staff['name']}, "
                                  f"{staff['role']}.{car} Say what you want.")
    if not opening:
        bus.event("task_end", task, status="error", text="customer agent got no answer")
        return {"status": "error"}
    who = f"{spec['name']} ({spec.get('email', 'no email yet')}{', ' + spec['phone'] if spec.get('phone') else ''})"
    bus.event("customer_says", task, customer=spec["name"], text=opening)
    if task.data["channel"].startswith("email"):
        mid = actors.deliver_mail(spec["email"], staff["email"], "Your service - not happy", opening)
        task.goal = (f"New email {mid} from customer {who}. Read it, look them up, and reply to them by email.")
        return run_staff(bus, task)
    task.goal = (f"{task.data['channel'].capitalize()}: {who} says:\n\"{opening}\"\n\nHelp them. Use your "
                 "systems as needed (find or create them in the CRM, check stock or bookings, book what is agreed). "
                 "Your final answer is what you say back to them.")
    rounds = [task.data.get("rounds", 1) - 1]
    transcript = [f"You: {opening}"]

    def respond(answer):
        if rounds[0] <= 0 or not answer:
            return None
        rounds[0] -= 1
        transcript.append(f"{staff['name']}: {answer}")
        text, _ = talker.say(task, "The conversation so far:\n" + "\n".join(transcript) +
                             "\n\nReply to them (or wrap up politely if you have what you need).")
        if not text:
            return None
        transcript.append(f"You: {text}")
        bus.event("customer_says", task, customer=spec["name"], text=text)
        return f"{spec['name']} replies: \"{text}\""

    return run_staff(bus, task, respond=respond)


def run_reply(bus, task):
    from runner import actors
    from systems.common import personas
    d = task.data
    staff = personas()[task.actor]
    if d["who"] == "bmw":
        talker = actors.TalkerAgent("bmw-dealer-desk", actors.BMW_DESK_SYSTEM, "BMW UK", "manufacturer", bus)
    else:
        spec = next((c for c in _day().CUSTOMERS.values() if c.get("email") == d["addr"]), None) or \
            {"name": d["name"], "brief": "An existing customer of the dealership; reasonable, wants clear answers."}
        talker = actors.TalkerAgent("customer-" + d["addr"].split("@")[0].replace(".", "-"),
                                    actors.customer_system(spec), "Customers", "customer", bus)
    text, _ = talker.say(task, f"You received this email from {staff['name']} ({staff['role']}, VXC Motors):\n"
                               f"Subject: {d['subject']}\n\n{d['body']}\n\nWrite your reply.")
    if not text:
        bus.event("task_end", task, status="error", text="no reply generated")
        return {"status": "error"}
    if "NO_REPLY" in text:
        bus.event("task_end", task, status="no_reply", text=f"{d['addr']} did not need to answer")
        return {"status": "no_reply"}
    mid = actors.deliver_mail(d["addr"], staff["email"], "Re: " + d["subject"], text, reply_to=d["msg_id"])
    bus.event("reply_mail", task, frm=d["addr"], to=staff["email"], msg_id=mid, text=text[:300])
    bus.wake(task, task.actor, f"New email {mid} from {d['addr']}: \"Re: {d['subject']}\". Read it and act on it.",
             delay=1, title=task.title)
    return {"status": "done"}


def run_admin(bus, task):
    """The IT administrator: a note on every blocked session, a manual block on one warned session."""
    from llm import BASE_URL
    db = sqlite3.connect(os.environ["PROXY_LOG_DB"])
    blocked = db.execute("SELECT session, agent, topic, ref FROM admin_actions WHERE action='block_session' "
                         "AND actor='firewall'").fetchall()
    warned = db.execute("SELECT session, agent, topic FROM signals WHERE level='warning' AND session NOT IN "
                        "(SELECT session FROM admin_actions WHERE action='block_session') ORDER BY id").fetchall()
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
    req = urllib.request.Request(f"{base.rstrip('/')}/firewall/sessions/{session}/{action}",
                                 data=json.dumps({"actor": actor, "reason": reason}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except OSError as e:
        return {"error": str(e)}


# ---------------------------------------------------------------- main

def load_tasks(until=None, only=None):
    day = _day()
    tasks = []
    for i, e in enumerate(day.EVENTS, 1):
        at = mins(e["at"])
        if until and at > mins(until):
            continue
        if only and e.get("actor") not in only and e["kind"] != "admin":
            continue
        data = {k: e[k] for k in ("customer", "channel", "rounds", "from", "subject", "body", "wake", "actions") if k in e}
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
            bus.done(task)
            bus.check_budget()


def main():
    ap = argparse.ArgumentParser(description="Run the VXC Motors multi-agent workday")
    ap.add_argument("--plan", action="store_true", help="print the timeline and exit")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-calls", type=int, default=650, help="stop starting tasks after this many agent LLM calls")
    ap.add_argument("--reserve", type=int, default=0,
                    help="stop when fewer free requests are left today (default 0: keep going on the paid fallback)")
    ap.add_argument("--until", help="only events up to HH:MM")
    ap.add_argument("--only", nargs="*", help="only these persona ids (plus the admin)")
    ap.add_argument("--keep", action="store_true", help="keep the systems' state and logs from a previous run")
    a = ap.parse_args()
    day = _day()
    tasks = load_tasks(a.until, a.only)
    if a.plan:
        for t in tasks:
            print(f"{hm(t.at)}  {t.kind:<8} {t.actor or '':<15} {t.incident or '':<6} {t.title}")
        return

    os.environ.setdefault("PROXY_LOG_DB", os.path.join(OUT, "proxy.db"))
    os.environ.setdefault("AGENT_LOG_DIR", os.path.join(OUT, "agents"))
    if not a.keep:
        reset()
    from llm import start_proxy
    proxy = start_proxy(PROXY_LOG_DB=os.environ["PROXY_LOG_DB"], GATEWAY_DB=os.path.join(OUT, "gateway.db"),
                        GATEWAY_SPEND_CAP_USD=os.environ.get("GATEWAY_SPEND_CAP_USD", "6"))
    bus = Bus(day.DATE, a.max_calls, a.reserve, a.workers)
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
    except KeyboardInterrupt:
        bus.stop("interrupted")
        for th in threads:
            th.join(timeout=600)
    left = [t.title for _, _, t in bus.queue]
    summary = {"date": day.DATE, "calls": bus.calls, "minutes": round((time.time() - started) / 60, 1),
               "stopped": bus.stopped, "tasks": bus.results, "not_started": left}
    bus.event("day_end", text=f"{bus.calls} agent LLM calls in {summary['minutes']} min", not_started=len(left))
    with open(os.path.join(OUT, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2, default=str)
    from systems.common import Store
    Store.close_all()
    if proxy:
        proxy.terminate()


def reset():
    """Fresh systems (reseeded to the 07:45 morning) and empty workday logs."""
    import shutil
    from systems.common import DATA, DB_FILES, Store
    Store.close_all()
    for f in DB_FILES.values():
        for suffix in ("", ".wal"):
            p = DATA / (f + suffix)
            if p.exists():
                p.unlink()
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT, exist_ok=True)
    from systems import seed
    seed.build(parquet=False)


if __name__ == "__main__":
    sys.exit(main())
