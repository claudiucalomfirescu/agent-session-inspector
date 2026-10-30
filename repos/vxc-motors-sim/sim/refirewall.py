"""Replay a recorded workday's traffic through the current firewall (lesson 9, addendum).

    python -m sim.refirewall runs/2026-10-27                 # live intent check (paid model, ~$0.01)
    python -m sim.refirewall runs/2026-10-27 --offline       # recorded verdicts only (no network)

Every agent call of the day is fed, in the order it happened, to a fresh Firewall: the request, then
the LLM's answer. The answer is the one the agent got; where the firewall withheld it on the day
(route firewall-response) the original answer is read back from the day's gateway cache. A call the
day's firewall blocked before forwarding has no LLM answer at all, so only its request is replayed:
the replay can judge what was said, not what the model would have said next.

Output: <run>/refirewall.db with the new firewall's `signals` and `admin_actions`, the same tables the
proxy writes, so runner/evaluate.py scores both the same way.

The intent check's answers are kept in a cassette (tests/fixtures/day1_intent_verdicts.json by default),
keyed by a hash of the classifier prompt. --offline answers from it only; the regression tests in
tests/test_firewall_day1.py use it the same way, so they run on the real classifier's verdicts with no
network.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "proxy"))
from firewall import Firewall  # noqa: E402
from gateway import Gateway  # noqa: E402
from logstore import LogStore  # noqa: E402

CASSETTE = os.path.join(ROOT, "tests", "fixtures", "day1_intent_verdicts.json")
MODEL = os.environ.get("GATEWAY_FALLBACK_MODEL", "z-ai/glm-5.3-flash")
SKIP_AGENTS = ("firewall", "console-")


class CassetteLLM:
    """The classifier's way to the model, with every answer recorded by prompt hash."""

    def __init__(self, path, offline=False):
        self.path, self.offline = path, offline
        self.tape = json.load(open(path)) if os.path.exists(path) else {}
        self.new = 0

    @staticmethod
    def key(messages):
        return hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()[:24]

    def __call__(self, messages):
        k = self.key(messages)
        if k in self.tape:
            return self.tape[k]
        if self.offline:
            return None
        body = json.dumps({"model": MODEL, "messages": messages, "temperature": 0,
                           "reasoning": {"effort": "low"}, "max_tokens": 800}).encode()
        req = urllib.request.Request("https://openrouter.ai/api/v1/chat/completions", data=body, method="POST",
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                answer = json.loads(r.read())["choices"][0]["message"]["content"]
        except (OSError, KeyError, ValueError):
            return None
        self.tape[k] = answer
        self.new += 1
        return answer

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w") as f:
            json.dump(self.tape, f, indent=0, sort_keys=True)


def day_calls(run):
    """(agent, session, request, response or None) for every agent chat call of the day, in order."""
    db = sqlite3.connect(os.path.join(run, "proxy.db"))
    gw = os.path.join(run, "gateway.db")
    cache = sqlite3.connect(gw) if os.path.exists(gw) else None
    out = []
    for agent, session, route, req_text, resp_text in db.execute(
            "SELECT agent, session, route, request, response FROM calls WHERE path LIKE '%chat/completions' "
            "AND status = 200 ORDER BY id"):
        if not agent or agent.startswith(SKIP_AGENTS):
            continue
        try:
            req = json.loads(req_text)
        except ValueError:
            continue
        resp = None
        if route == "firewall-response" and cache:  # the answer the firewall withheld on the day
            hit = cache.execute("SELECT response FROM cache WHERE key = ?", (Gateway.cache_key(req),)).fetchone()
            resp = json.loads(hit[0]) if hit else None
        elif route != "firewall":
            resp = json.loads(resp_text)
        out.append((agent, session or agent, req, resp))
    return out


def replay(run, llm, out_db, intent_mode="llm"):
    if os.path.exists(out_db):
        os.remove(out_db)
    fw = Firewall(LogStore(out_db), llm=llm, intent_mode=intent_mode)
    for agent, session, req, resp in day_calls(run):
        d = fw.inspect_request(agent, session, req)
        fw.commit(d)
        if not d.blocked and resp is not None:
            fw.commit(fw.inspect_response(agent, session, req, resp))
    return fw


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run", help="a runs/<day> folder")
    ap.add_argument("--offline", action="store_true", help="recorded classifier answers only")
    ap.add_argument("--rules-only", action="store_true", help="no intent check at all (refusal rule stands in)")
    ap.add_argument("--cassette", default=CASSETTE)
    ap.add_argument("--out", help="default: <run>/refirewall.db")
    a = ap.parse_args()
    llm = CassetteLLM(a.cassette, offline=a.offline)
    out = a.out or os.path.join(a.run, "refirewall.db")
    fw = replay(a.run, None if a.rules_only else llm, out, "heuristic" if a.rules_only else "llm")
    if llm.new:
        llm.save()
    print(json.dumps({"out": os.path.relpath(out, ROOT), "new_verdicts": llm.new, **dict(fw.stats)}, indent=1))


if __name__ == "__main__":
    main()
