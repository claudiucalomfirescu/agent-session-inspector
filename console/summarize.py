"""LLM-written summaries for the console, cached so each one is asked for only once.

    python3 console/summarize.py                  # summaries for logs/proxy.db
    python3 console/summarize.py logs/demo.db     # for the demo day
    python3 console/summarize.py --limit 10       # at most 10 LLM requests this run

Bottom up: each session from its transcript, each person from their session summaries, each department
from its people, the company from its departments. Every summary is stored in <log>.summaries.db with
the log position it describes (`version`); the console shows an LLM summary only while it is current,
and falls back to the rule-based one otherwise.

Requests go through the shared llm layer and the proxy (started if needed), so the gateway's rate limit
and budget rules apply. They are sent as agent `console-summarizer`, which the console leaves out of
its own views. About one request per session plus one per person, department and the company.
"""
import argparse
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))
import model  # noqa: E402

SYSTEM = ("You summarise AI agent sessions for the administrator of VXC Motors, a BMW dealership. "
          "Write plain English for a busy manager: what the person asked their agent to do, what got done, "
          "and any policy problem the firewall flagged. No preamble, no bullet points, no markdown.")


def transcript(convo, limit=3500):
    lines = []
    for m in convo:
        if m["role"] == "system" or m["role"] == "marker":
            continue
        if m["role"] == "assistant" and m.get("tool_calls"):
            lines.append("agent calls " + ", ".join(f"{t['function']['name']}({t['function']['arguments'][:120]})"
                                                    for t in m["tool_calls"]))
        elif m["role"] == "assistant" and m.get("route", "").startswith("firewall"):
            lines.append("FIREWALL (answering instead of the LLM): " + (m["content"] or "")[:300])
        else:
            lines.append(f"{m['role']}: {(m['content'] or '')[:400]}")
    text = "\n".join(lines)
    return text if len(text) <= limit else text[:limit] + "\n[…]"


def store(db, kind, key, text, version):
    db.execute("INSERT OR REPLACE INTO summaries (kind, key, text, version) VALUES (?,?,?,?)", (kind, key, text, version))
    db.commit()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", nargs="?", default=os.path.join(model.ROOT, "logs", "proxy.db"))
    ap.add_argument("--limit", type=int, default=80, help="most LLM requests to make in this run")
    args = ap.parse_args()

    import llm
    proxy = llm.start_proxy()  # None if one is already running
    # The transcripts contain the very incidents the firewall blocks. The proxy exempts this agent
    # (FIREWALL_EXEMPT_AGENTS, plus X-Admin-Token when one is set); a fresh session per summary also
    # keeps one flagged transcript from escalating and blocking every summary after it.
    token = {"X-Admin-Token": os.environ["FIREWALL_ADMIN_TOKEN"]} if os.environ.get("FIREWALL_ADMIN_TOKEN") else {}
    budget = [args.limit]

    def ask(prompt, max_tokens=700):
        if budget[0] <= 0:
            return None
        budget[0] -= 1
        # nemotron reasons before it answers; a summary does not need that, and the reasoning would use up
        # max_tokens and leave the answer empty (finish_reason "length", content null)
        client, _ = llm.make_client("console-summarizer", role="Admin console", department="IT")
        r = llm.chat(client, [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
                     max_tokens=max_tokens, temperature=0.2, extra_body={"reasoning": {"enabled": False}},
                     extra_headers=token)
        text = (r.choices[0].message.content or "").strip()
        return " ".join(text.split()) or None

    sdb_path = model.summary_db_for(args.db)
    sdb = sqlite3.connect(sdb_path)
    sdb.execute("CREATE TABLE IF NOT EXISTS summaries (kind TEXT, key TEXT, text TEXT, version TEXT, PRIMARY KEY (kind, key))")
    snap = model.build(args.db)
    have = model.cached_summaries(sdb_path)
    made = 0

    for s in snap["sessions"]:
        if have.get(("session", s["id"]), (None, None))[1] == str(s["last_call"]):
            continue
        text = ask(f"Summarise this session by {s['agent_name']} in one or two sentences (max 45 words).\n\n"
                   + transcript(snap["conversations"][s["id"]]))
        if text:
            store(sdb, "session", s["id"], text, str(s["last_call"]))
            made += 1
            print(f"session {s['id']} {s['agent_name']}: {text}", flush=True)

    snap = model.build(args.db)  # now with the session summaries
    version = str(max([s["last_call"] for s in snap["sessions"]] or [0]))
    for p in snap["people"]:
        mine = [s for s in snap["sessions"] if s["agent"] == p["id"]]
        if not mine or have.get(("person", p["id"]), (None, None))[1] == version:
            continue
        text = ask(f"{p['name']} ({p['role']}) had these agent sessions today. Summarise their day in two sentences "
                   f"(max 55 words), mentioning any firewall alerts.\n\n"
                   + "\n".join(f"- {s['start'][11:16]} [{s['level'] or 'clean'}{', blocked' if s['blocked'] else ''}] {s['summary']}" for s in mine))
        if text:
            store(sdb, "person", p["id"], text, version)
            made += 1
            print(f"person {p['id']}: {text}", flush=True)

    snap = model.build(args.db)
    for d in snap["departments"]:
        if not d["sessions"] or have.get(("department", d["name"]), (None, None))[1] == version:
            continue
        people = [p for p in snap["people"] if p["id"] in d["people"]]
        text = ask(f"Summarise the {d['name']} department's day in two sentences (max 55 words) from its people:\n\n"
                   + "\n".join(f"- {p['name']}, {p['role']}: {p['summary_activity']}" for p in people))
        if text:
            store(sdb, "department", d["name"], text, version)
            made += 1
            print(f"department {d['name']}: {text}", flush=True)

    snap = model.build(args.db)
    if have.get(("company", "VXC Motors"), (None, None))[1] != version:
        t = snap["totals"]
        text = ask(f"Write the administrator's three-sentence brief (max 75 words) of the day at VXC Motors: "
                   f"{t['sessions']} sessions, {t['calls']} LLM calls, {t['blocked_sessions']} blocked sessions. "
                   f"Lead with the firewall events (name every blocked person), then the routine work.\n\nFirewall events:\n"
                   + "\n".join(f"- {s['start'][11:16]} {s['agent_name']}: {'blocked' if s['blocked'] else s['level']}, "
                               f"{', '.join(snap['topics'].get(x, x) for x in s['topics'])}"
                               for s in snap["sessions"] if s["blocked"] or s["level"] == "warning")
                   + "\n\nDepartments:\n" + "\n".join(f"- {d['name']}: {d['summary']}" for d in snap["departments"]),
                   max_tokens=700)
        if text:
            store(sdb, "company", "VXC Motors", text, version)
            made += 1
            print(f"company: {text}", flush=True)
    print(f"{made} summaries written to {sdb_path} ({args.limit - budget[0]} LLM requests)")
    if proxy:
        proxy.terminate()


if __name__ == "__main__":
    main()
