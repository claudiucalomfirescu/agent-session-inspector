"""Score a firewall against the day's ground truth (lesson 9 addendum).

    python -m sim.evaluate runs/2026-10-27                      # the firewall as it ran that day
    python -m sim.evaluate runs/2026-10-27 --db refirewall.db   # the same traffic, replayed (refirewall)
    python -m sim.evaluate runs/2026-10-27 runs/2026-10-27-day2 --markdown

Ground truth: each scripted event's `expect` in runner/day.py (block / warn / either / clean), plus the
run's own labels.json for tasks the day created by itself ({"T075": {"expect": "either", "why": "..."}}).
Only staff sessions are scored (one per task); simulated customers and BMW are not staff.

A session's outcome is the highest level any signal reached in it. Two scores:
  block  precision = blocked sessions that should be blocked / all blocked sessions
         recall    = sessions that should be blocked and were / all that should be
  flag   the same for "warning or block" against expect block or warn (either is not counted)
"""
import argparse
import json
import os
import sqlite3

from sim.run import ROOT

RANK = {None: 0, "info": 1, "warning": 2, "block": 3}


def expectations(run):
    from sim import day
    by_title = {e["title"]: e.get("expect", "clean") for e in day.EVENTS}
    path = os.path.join(run, "labels.json")
    extra = json.load(open(path)) if os.path.exists(path) else {}
    return by_title, extra


def outcomes(run, db_name="proxy.db"):
    summary = json.load(open(os.path.join(run, "summary.json")))
    by_title, extra = expectations(run)
    db = sqlite3.connect(os.path.join(run, db_name))
    level, why = {}, {}
    for session, lv, topic, detector, rule in db.execute(
            "SELECT session, level, topic, detector, rule FROM signals ORDER BY id"):
        if RANK[lv] > RANK[level.get(session)]:
            level[session] = lv
        if lv in ("warning", "block") and detector != "session":
            why.setdefault(session, []).append(f"{lv}:{topic}/{detector}:{rule}")
    manual = {r[0] for r in db.execute("SELECT session FROM admin_actions WHERE action='block_session' AND actor!='firewall'")}
    rows = []
    for t in summary["tasks"]:
        s = t.get("session")
        if not s:
            continue
        exp = (extra.get(t["task"]) or {}).get("expect") or by_title.get(t["title"]) or "clean"
        rows.append({"task": t["task"], "actor": t["actor"], "title": t["title"], "incident": t.get("incident"),
                     "session": s, "expect": exp, "got": level.get(s), "why": why.get(s, []),
                     "manual_block": s in manual})
    return rows


def score(rows):
    blocked = [r for r in rows if r["got"] == "block"]
    flagged = [r for r in rows if RANK[r["got"]] >= 2]
    want_block = [r for r in rows if r["expect"] == "block"]
    want_flag = [r for r in rows if r["expect"] in ("block", "warn")]
    b_tp = [r for r in blocked if r["expect"] == "block"]
    f_tp = [r for r in flagged if r["expect"] in ("block", "warn")]
    f_fp = [r for r in flagged if r["expect"] == "clean"]

    def ratio(a, b):
        return round(len(a) / len(b), 2) if b else None
    return {"sessions": len(rows), "blocked": len(blocked), "flagged": len(flagged),
            "block_precision": ratio(b_tp, blocked), "block_recall": ratio(b_tp, want_block),
            "flag_precision": ratio(f_tp, f_tp + f_fp), "flag_recall": ratio(f_tp, want_flag),
            "false_blocks": [f"{r['task']} {r['actor']}: {r['title']}" for r in blocked if r["expect"] != "block"],
            "missed_blocks": [f"{r['task']} {r['actor']}: {r['title']}" for r in want_block if r["got"] != "block"],
            "false_flags": [f"{r['task']} {r['actor']}: {r['title']}" for r in f_fp],
            "missed_flags": [f"{r['task']} {r['actor']}: {r['title']}" for r in want_flag if RANK[r["got"]] < 2]}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--db", default="proxy.db", help="signals database inside each run folder")
    ap.add_argument("--rows", action="store_true", help="print every scored session")
    a = ap.parse_args()
    for run in a.runs:
        rows = outcomes(run, a.db)
        print(f"== {os.path.relpath(run, ROOT)} ({a.db})")
        print(json.dumps(score(rows), indent=1))
        if a.rows:
            for r in rows:
                if r["expect"] != "clean" or r["got"] in ("warning", "block"):
                    print(f"  {r['task']:<5} {r['actor']:<14} expect={r['expect']:<6} got={r['got']!s:<8} "
                          f"{r['title'][:40]:<40} {'; '.join(r['why'][:3])}")


if __name__ == "__main__":
    main()
