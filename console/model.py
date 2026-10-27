"""The console's data model: one JSON snapshot built from the proxy log and the company personas.

    company -> department -> person -> session -> conversation (messages, tool calls, signals)

The same snapshot feeds the live server (console/server.py) and the static export (console/export.py),
so a published page shows exactly what the live console showed.

Inputs, all optional except the log:
  logs/proxy.db (or any file with the same `calls` table; `signals` and `admin_actions` are read when
  the firewall has created them), company/personas/*.md (source of truth, with avatars), and cached
  LLM summaries in logs/summaries.db (written by console/summarize.py). Anything missing falls back to
  heuristics, so the console never needs the network to render.
"""
import base64
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPANY = os.path.join(ROOT, "company")
SUMMARY_DB = os.environ.get("CONSOLE_SUMMARY_DB", os.path.join(ROOT, "logs", "summaries.db"))

TOPICS = {  # fallback titles; proxy/firewall_topics.yaml wins when present
    "customer_pii_leak": "Customer PII leak",
    "discount_fraud": "Discount fraud",
    "competitor_poaching": "Competitor poaching",
    "harassment": "Harassment",
    "credential_sharing": "Credential sharing",
}
DEPARTMENTS = [  # as in company/tools/load_personas.py, which needs duckdb; the console does not
    ("Management", "Management", "General management, P&L and the BMW relationship"),
    ("Admin", "Admin", "Reception, finance, payroll"),
    ("Sales", "Sales", "New and used car sales; orders cars from BMW"),
    ("Service", "Aftersales", "Service advisors, bookings, warranty"),
    ("Workshop", "Aftersales", "Technicians: mechanical, electrical, EV"),
    ("Parts", "Aftersales", "Parts stock; orders parts from BMW"),
]
LEVELS = ["info", "warning", "block"]
SYSTEM_IDS = ["bmw_portal", "workshop", "finance", "parts", "crm", "dms", "mail"]
SYSTEM_NAMES = {"crm": "VXC CRM", "dms": "Dealer Management", "workshop": "Workshop Planner", "parts": "Parts Inventory",
                "finance": "Finance & Payroll", "mail": "Email & chat", "bmw_portal": "BMW Partner Portal",
                "console": "Admin console", "other": "Other tools"}


def tool_system(name):
    """crm_find_customer -> crm, bmw_portal_order_parts -> bmw_portal. Agents name tools <system>_<verb>."""
    for s in SYSTEM_IDS:
        if name == s or name.startswith(s + "_"):
            return s
    return name.split("_")[0] if name.startswith("console_") else "other"


def _j(text):
    if text is None or not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except ValueError:
        return text


def level_rank(level):
    return LEVELS.index(level) + 1 if level in LEVELS else 0


def max_level(levels):
    best = None
    for lv in levels:
        if level_rank(lv) > level_rank(best):
            best = lv
    return best


# --- personas -----------------------------------------------------------------------------------
def load_people():
    try:
        import yaml
        people = []
        for name in sorted(os.listdir(os.path.join(COMPANY, "personas"))):
            if name.endswith(".md"):
                with open(os.path.join(COMPANY, "personas", name), encoding="utf-8") as f:
                    people.append(yaml.safe_load(f.read().split("---", 2)[1]))
        depts = DEPARTMENTS
    except Exception as e:  # noqa: BLE001  (no yaml, or no company folder: the console still works)
        print(f"personas not loaded ({type(e).__name__}: {e}); using agent ids only", file=sys.stderr)
        return [], []
    out = []
    for p in people:
        avatar = None
        path = os.path.join(COMPANY, p.get("avatar") or "")
        if p.get("avatar") and os.path.exists(path):
            with open(path, "rb") as f:
                avatar = "data:image/svg+xml;base64," + base64.b64encode(f.read()).decode()
        risk = p.get("risk_profile") or {}
        persona = p.get("personality") or {}
        out.append({
            "id": p["id"], "name": p["name"], "role": p["role"], "department": p["department"],
            "reports_to": p.get("reports_to"), "email": p.get("email"), "phone_ext": p.get("phone_ext"),
            "workspace": p.get("workspace"), "joined": str(p.get("joined") or ""), "age": p.get("age"),
            "years_experience": p.get("years_experience"), "nationality": p.get("nationality"),
            "summary": p.get("summary"), "systems": p.get("systems") or [],
            "responsibilities": p.get("responsibilities") or [], "kpis": p.get("kpis") or [],
            "traits": persona.get("traits") or [], "style": persona.get("communication_style"),
            "risk_level": risk.get("level"), "risk_topics": risk.get("topics") or [],
            "avatar": avatar,
        })
    return out, [{"name": d[0], "area": d[1], "description": d[2]} for d in depts]


def load_topics():
    path = os.path.join(ROOT, "proxy", "firewall_topics.yaml")
    topics = dict(TOPICS)
    try:
        import yaml
        with open(path) as f:
            data = yaml.safe_load(f) or {}
        items = data.get("topics", data)
        if isinstance(items, dict):
            items = [dict(v, id=k) if isinstance(v, dict) else {"id": k, "title": str(v)} for k, v in items.items()]
        for t in items or []:
            if isinstance(t, dict) and t.get("id"):
                topics[t["id"]] = t.get("title") or t.get("name") or topics.get(t["id"], t["id"])
    except (OSError, ImportError, ValueError, AttributeError):
        pass
    return topics


# --- the log ------------------------------------------------------------------------------------
def read_log(path):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    calls = [dict(r) for r in db.execute("SELECT * FROM calls ORDER BY id")] if "calls" in tables else []
    signals = [dict(r) for r in db.execute("SELECT * FROM signals ORDER BY id")] if "signals" in tables else []
    actions = [dict(r) for r in db.execute("SELECT * FROM admin_actions ORDER BY id")] if "admin_actions" in tables else []
    db.close()
    return calls, signals, actions


def log_version(path):
    """Cheap fingerprint of the log, so the server rebuilds the snapshot only when something new was written."""
    try:
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        v = tuple(db.execute(f"SELECT COALESCE(MAX(id),0), COUNT(*) FROM {t}").fetchone() if t in tables else (0, 0)
                  for t in ("calls", "signals", "admin_actions"))
        db.close()
        return v + (os.path.getmtime(SUMMARY_DB) if os.path.exists(SUMMARY_DB) else 0,)
    except sqlite3.Error:
        return None


def content_text(content):
    if isinstance(content, list):  # multimodal parts
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


def light_call(c):
    """What mission control needs per call: who, when, how long, what happened, which tools."""
    req, resp = c["request"], c["response"]
    msg = ((resp.get("choices") or [{}])[0].get("message") or {}) if isinstance(resp, dict) else {}
    tools = [t["function"]["name"] for t in msg.get("tool_calls") or [] if t.get("function")]
    usage = c["usage"] if isinstance(c["usage"], dict) else {}
    labels = c["labels"] if isinstance(c["labels"], dict) else {}
    return {"id": c["id"], "ts": c["ts"], "agent": c["agent"] or "unknown", "session": c["session"] or c["agent"] or "-",
            "ms": c.get("duration_ms") or 0, "status": c.get("status"), "route": c.get("route"),
            "level": c.get("firewall_level"), "finish": c.get("finish_reason"),
            "tools": tools, "systems": sorted({tool_system(t) for t in tools}),
            "tokens": usage.get("total_tokens") or 0, "cost": c.get("cost_usd") or 0,
            "model": c.get("upstream_model") or c.get("model"), "error": bool(c.get("error")),
            "department": labels.get("department"), "role": labels.get("role"),
            "n_messages": len(req.get("messages") or []) if isinstance(req, dict) else 0}


def conversation(calls, signals):
    """Rebuild one session's transcript from its calls.

    Each request carries the whole history, so only the messages beyond what the previous call already
    showed are new. Each message is tagged with the call that first carried it; signals are pinned to
    the request side (last new message) or the response side (the reply) of their call."""
    out, seen = [], 0
    by_call = {}
    for s in signals:
        by_call.setdefault(s.get("call_id"), []).append(s)
    for c in calls:
        req = c["request"] if isinstance(c["request"], dict) else {}
        msgs = req.get("messages") or []
        if len(msgs) < seen:  # the agent started a fresh context in the same session
            out.append({"role": "marker", "content": "New context"})
            seen = 0
        new = msgs[seen:]
        for m in new:
            out.append({"role": m.get("role"), "content": content_text(m.get("content")), "call": c["id"],
                        "tool_calls": m.get("tool_calls"), "tool_call_id": m.get("tool_call_id")})
        req_idx = len(out) - 1
        resp = c["response"] if isinstance(c["response"], dict) else {}
        msg = ((resp.get("choices") or [{}])[0].get("message")) if resp.get("choices") else None
        if msg:
            out.append({"role": "assistant", "content": content_text(msg.get("content")), "call": c["id"],
                        "tool_calls": msg.get("tool_calls"), "route": c.get("route"), "level": c.get("firewall_level"),
                        "ts": c["ts"], "ms": c.get("duration_ms")})
        elif c.get("error") or (c.get("status") or 200) >= 400:
            err = c["error"] if isinstance(c["error"], dict) else {"message": str(c.get("error") or c.get("response"))[:300]}
            out.append({"role": "error", "content": f"{c.get('status')}: {err.get('message', '')}", "call": c["id"], "ts": c["ts"]})
        resp_idx = len(out) - 1
        for s in by_call.get(c["id"], []):
            idx = resp_idx if s.get("direction") == "response" and msg else req_idx
            if 0 <= idx < len(out):
                out[idx].setdefault("signals", []).append(s["id"])
        seen = len(msgs) + (1 if msg else 0)
    return out


# --- summaries ----------------------------------------------------------------------------------
def cached_summaries():
    if not os.path.exists(SUMMARY_DB):
        return {}
    db = sqlite3.connect(SUMMARY_DB)
    try:
        return {(k, key): (text, version) for k, key, text, version in
                db.execute("SELECT kind, key, text, version FROM summaries")}
    except sqlite3.Error:
        return {}
    finally:
        db.close()


def first_sentence(text, n=160):
    text = " ".join((text or "").split())
    m = re.match(r"(.+?[a-z0-9)%'\"][.!?])(\s+[A-Z\"]|$)", text)
    s = m.group(1) if m else text
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def heuristic_session_summary(s, convo, topics):
    asks = [m["content"] for m in convo if m["role"] == "user"]
    replies = [m for m in convo if m["role"] == "assistant" and m.get("content")]
    parts = [first_sentence(asks[0]) if asks else "Session without a user message."]
    if s["tools"]:
        parts.append("Used " + ", ".join(s["tools"][:4]) + ("…" if len(s["tools"]) > 4 else "") + ".")
    if s["blocked"]:
        parts.append(f"Blocked by the firewall ({', '.join(topics.get(t, t) for t in s['topics'])}).")
    elif replies:
        parts.append("Outcome: " + first_sentence(replies[-1]["content"]))
    if s["level"] in ("warning", "info") and s["topics"]:
        parts.append(f"{s['level'].title()} on {', '.join(topics.get(t, t) for t in s['topics'])}.")
    return " ".join(parts)


def heuristic_person_summary(p, sessions, topics):
    if not sessions:
        return "No agent activity in this window."
    systems = {}
    for s in sessions:
        for x in s["systems"]:
            systems[x] = systems.get(x, 0) + 1
    top = sorted(systems, key=lambda x: -systems[x])[:3]
    text = (f"{len(sessions)} session{'s' * (len(sessions) != 1)}, {sum(s['calls'] for s in sessions)} LLM calls"
            + (f", mostly in {', '.join(SYSTEM_NAMES.get(t, t) for t in top)}" if top else "") + ". ")
    tasks = [first_sentence(s["title"], 70).rstrip(".") for s in sessions[:3]]
    text += "Work: " + "; ".join(tasks) + ". "
    blocked = [s for s in sessions if s["blocked"]]
    flagged = [s for s in sessions if s["level"] in ("warning",) and not s["blocked"]]
    if blocked:
        text += f"{len(blocked)} session{'s' * (len(blocked) != 1)} blocked ({', '.join(sorted({topics.get(t, t) for s in blocked for t in s['topics']}))}). "
    if flagged:
        text += f"{len(flagged)} with warnings. "
    return text.strip()


def heuristic_group_summary(name, people, sessions, topics):
    if not sessions:
        return f"No agent activity in {name} in this window."
    blocked = [s for s in sessions if s["blocked"]]
    text = (f"{len({s['agent'] for s in sessions})} of {len(people)} people active, {len(sessions)} sessions, "
            f"{sum(s['calls'] for s in sessions)} LLM calls.")
    if blocked:
        who = sorted({s["agent_name"] for s in blocked})
        text += f" Firewall blocks: {len(blocked)} ({', '.join(who)})."
    else:
        text += " No blocks."
    return text


# --- the snapshot -------------------------------------------------------------------------------
def build(log_path, include_conversations=True, source_label=None):
    calls, signals, actions = read_log(log_path)
    for c in calls:
        for k in ("request", "response", "usage", "error", "labels"):
            c[k] = _j(c.get(k))
    people, departments = load_people()
    topics = load_topics()
    cache = cached_summaries()
    pmap = {p["id"]: p for p in people}

    light = [light_call(c) for c in calls]
    for s in signals:
        s["session"] = s.get("session") or s.get("agent")
    # Agents in the log that are not personas still get a place in the tree.
    for lc in light:
        if lc["agent"] not in pmap:
            p = {"id": lc["agent"], "name": lc["agent"], "role": lc.get("role") or "Agent",
                 "department": lc.get("department") or "Unassigned", "systems": [], "risk_topics": [], "avatar": None}
            pmap[p["id"]] = p
            people.append(p)
    known = {d["name"] for d in departments}
    for p in people:
        if p["department"] not in known:
            departments.append({"name": p["department"], "area": "Other", "description": ""})
            known.add(p["department"])

    by_session = {}
    for c, lc in zip(calls, light):
        by_session.setdefault(lc["session"], []).append((c, lc))
    sig_by_session, act_by_session = {}, {}
    for s in signals:
        sig_by_session.setdefault(s["session"], []).append(s)
    for a in actions:
        act_by_session.setdefault(a.get("session"), []).append(a)

    sessions, conversations = [], {}
    for sid, items in by_session.items():
        raw = [c for c, _ in items]
        lcs = [lc for _, lc in items]
        sigs = sig_by_session.get(sid, [])
        acts = act_by_session.get(sid, [])
        convo = conversation(raw, sigs)
        first_user = next((m["content"] for m in convo if m["role"] == "user"), "")
        tools = [t for lc in lcs for t in lc["tools"]]
        state = None
        for a in acts:
            if a.get("action") in ("block_session", "unblock_session"):
                state = a["action"]
        blocked = state == "block_session" or any(lc["route"] in ("firewall", "firewall-response") for lc in lcs) and state != "unblock_session"
        agent = lcs[0]["agent"]
        s = {"id": sid, "agent": agent, "agent_name": pmap.get(agent, {}).get("name", agent),
             "department": pmap.get(agent, {}).get("department"),
             "start": lcs[0]["ts"], "end": lcs[-1]["ts"], "calls": len(lcs),
             "tokens": sum(lc["tokens"] for lc in lcs), "cost": round(sum(lc["cost"] for lc in lcs), 5),
             "errors": sum(lc["error"] for lc in lcs), "title": first_user or "(no user message)",
             "tools": list(dict.fromkeys(tools)), "systems": sorted({tool_system(t) for t in tools}),
             "level": max_level([x["level"] for x in sigs] + [lc["level"] for lc in lcs]),
             "topics": sorted({x["topic"] for x in sigs if x.get("topic")}), "signals": len(sigs),
             "blocked": bool(blocked), "actions": len(acts),
             "last_call": lcs[-1]["id"]}
        cached = cache.get(("session", sid))
        if cached and cached[1] == str(s["last_call"]):
            s["summary"], s["summary_source"] = cached[0], "llm"
        else:
            s["summary"], s["summary_source"] = heuristic_session_summary(s, convo, topics), "heuristic"
        sessions.append(s)
        if include_conversations:
            conversations[sid] = convo
    sessions.sort(key=lambda s: s["start"])

    def summarise(kind, key, version, fallback):
        cached = cache.get((kind, key))
        if cached and cached[1] == version:
            return cached[0], "llm"
        return fallback, "heuristic"

    version = str(max([s["last_call"] for s in sessions] or [0]))
    for p in people:
        mine = [s for s in sessions if s["agent"] == p["id"]]
        p["sessions"] = len(mine)
        p["calls"] = sum(s["calls"] for s in mine)
        p["level"] = max_level([s["level"] for s in mine])
        p["blocked"] = sum(s["blocked"] for s in mine)
        p["summary_activity"], p["summary_source"] = summarise(
            "person", p["id"], version, heuristic_person_summary(p, mine, topics))
    for d in departments:
        members = [p for p in people if p["department"] == d["name"]]
        mine = [s for s in sessions if s["agent"] in {p["id"] for p in members}]
        d["people"] = [p["id"] for p in members]
        d["sessions"] = len(mine)
        d["calls"] = sum(s["calls"] for s in mine)
        d["level"] = max_level([s["level"] for s in mine])
        d["summary"], d["summary_source"] = summarise("department", d["name"], version,
                                                      heuristic_group_summary(d["name"], members, mine, topics))
    departments = [d for d in departments if d["people"]]
    company_summary, company_source = summarise("company", "VXC Motors", version,
                                                heuristic_group_summary("VXC Motors", people, sessions, topics))

    for a in actions:
        a["agent_name"] = pmap.get(a.get("agent"), {}).get("name", a.get("agent"))
    for s in signals:
        s["agent_name"] = pmap.get(s.get("agent"), {}).get("name", s.get("agent"))
        s["topic_title"] = topics.get(s.get("topic"), s.get("topic"))

    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": source_label or os.path.relpath(log_path, ROOT),
        "window": {"start": light[0]["ts"] if light else None, "end": light[-1]["ts"] if light else None},
        "company": {"name": "VXC Motors", "summary": company_summary, "summary_source": company_source},
        "departments": departments, "people": people, "topics": topics, "levels": LEVELS,
        "systems": SYSTEM_NAMES, "sessions": sessions, "calls": light,
        "signals": signals, "actions": actions, "conversations": conversations,
        "totals": {"calls": len(light), "sessions": len(sessions), "tokens": sum(x["tokens"] for x in light),
                   "cost": round(sum(x["cost"] for x in light), 4),
                   "signals": {lv: sum(1 for s in signals if s.get("level") == lv) for lv in LEVELS},
                   "blocked_sessions": sum(s["blocked"] for s in sessions), "actions": len(actions)},
    }


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "logs", "proxy.db")
    snap = build(path)
    print(json.dumps({k: snap[k] for k in ("source", "window", "company", "totals")}, indent=1))
