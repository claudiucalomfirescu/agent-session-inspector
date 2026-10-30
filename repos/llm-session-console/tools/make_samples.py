"""Build the demo logs in demo/data/ from recorded proxy logs.

    python3 tools/make_samples.py RECORDED_DAY1.db RECORDED_DAY2.db [--out samples]

Inputs are two real VXC Motors workdays recorded by the proxy on 27 Oct 2026 (agent-session-inspector,
runs/2026-10-27*/proxy.db): 12 staff agents, simulated customers and the BMW desk, every call real
(nvidia nemotron :free via OpenRouter), with firewall findings and blocks.

Outputs (xz-compressed; the console unpacks them on first run):

  vxc-recorded-day.db.xz  day 1 exactly as recorded, old schema (no user/dept columns): shows the
                          console reading a log whose users come from X-Agent-Id.
  vxc-4-weeks.db.xz       the current schema (user, dept, key_id, token columns) over four weeks:
                          the two real days placed on Wed 28 and Thu 29 Oct (each call at its simulated
                          office time), and 17 earlier days *rebuilt* from those real sessions: a
                          deterministic sample of them, copied with new session ids and shifted times.
                          Rebuilt rows say so: labels.replay_of = <original session>. Nothing is invented;
                          volumes vary by weekday, one person is on holiday a week, one day has an incident.

No network, no LLM. Same inputs -> byte-identical outputs (seeded).
"""
import argparse
import hashlib
import json
import lzma
import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_ID = hashlib.sha256(b"dummy").hexdigest()[:12]   # every VXC agent sends the dummy key; the proxy holds the real one
SCHEMA = """
CREATE TABLE calls (id INTEGER PRIMARY KEY, ts TEXT, duration_ms INTEGER, agent TEXT, session TEXT, user TEXT, dept TEXT,
  key_id TEXT, method TEXT, path TEXT, status INTEGER, model TEXT, finish_reason TEXT, usage TEXT, prompt_tokens INTEGER,
  completion_tokens INTEGER, total_tokens INTEGER, error TEXT, request TEXT, response TEXT, route TEXT, upstream_model TEXT,
  attempts INTEGER, cost_usd REAL, labels TEXT, firewall_level TEXT);
CREATE TABLE signals (id INTEGER PRIMARY KEY, ts TEXT, session TEXT, user TEXT, agent TEXT, call_id INTEGER, turn INTEGER, direction TEXT,
  level TEXT, topic TEXT, detector TEXT, rule TEXT, matched TEXT, rationale TEXT, confidence REAL, excerpt TEXT, ref TEXT);
CREATE TABLE admin_actions (id INTEGER PRIMARY KEY, ts TEXT, actor TEXT, action TEXT, session TEXT, user TEXT, agent TEXT, topic TEXT,
  reason TEXT, ref TEXT, call_id INTEGER);
CREATE INDEX signals_session ON signals(session);
CREATE INDEX actions_session ON admin_actions(session);
"""
FMT = "%Y-%m-%dT%H:%M:%SZ"


def rows(db, sql):
    cur = db.execute(sql)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def load_day(path):
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    calls = rows(db, "SELECT * FROM calls ORDER BY id")
    sigs = rows(db, "SELECT * FROM signals ORDER BY id")
    acts = rows(db, "SELECT * FROM admin_actions ORDER BY id")
    # Office time of every call: sim-time label + seconds since its session's first call. Calls without
    # a label (the firewall's own classifier) take the office time of the call just before them.
    first_ts, last_sim, last_real = {}, None, None
    for c in calls:
        lab = json.loads(c["labels"] or "{}")
        real = datetime.strptime(c["ts"], FMT)
        first_ts.setdefault(c["session"], (real, lab.get("sim-time")))
        start, sim = first_ts[c["session"]]
        if sim:
            h, m = map(int, sim.split(":"))
            c["office"] = timedelta(hours=h, minutes=m) + (real - start)
        elif last_sim is not None:
            c["office"] = last_sim + (real - last_real)
        else:
            c["office"] = timedelta(hours=8)
        last_sim, last_real = c["office"], real
        c["lab"] = lab
    by_session = {}
    for c in calls:
        by_session.setdefault(c["session"], []).append(c)
    return {"calls": calls, "signals": sigs, "actions": acts, "sessions": by_session}


def plan(days_src):
    """[(date, source day index, session id, shift minutes, replay)] for every session in the output."""
    out = []
    real_dates = [datetime(2026, 10, 28), datetime(2026, 10, 29)]
    for i, d in enumerate(real_dates):
        for s in days_src[i]["sessions"]:
            out.append((d, i, s, 0, False))
    pool = [(i, s, c) for i, day in enumerate(days_src) for s, c in day["sessions"].items()]
    d = datetime(2026, 10, 5)
    weekday_load = [1.0, 0.85, 0.8, 0.85, 0.7, 0.12, 0.0]
    while d < real_dates[0]:
        rnd = random.Random(d.strftime("%Y%m%d"))
        week = (d - datetime(2026, 10, 5)).days // 7
        load = weekday_load[d.weekday()] * (0.32 + 0.05 * week)          # slow growth week on week
        incident = d == datetime(2026, 10, 14)
        for i, s, calls in pool:
            agent = calls[0]["agent"]
            lab = calls[0]["lab"]
            if agent == "firewall":
                continue
            if agent == "priya-nair" and week == 1:                          # on holiday
                continue
            if d.weekday() >= 5 and lab.get("department") not in ("Customers", "Service"):
                continue
            flagged = any(c.get("firewall_level") in ("warning", "block") for c in calls)
            p = load * (0.35 if flagged and not incident else 2.2 if flagged else 1.0)
            if rnd.random() < p:
                out.append((d, i, s, rnd.randint(-25, 25), True))
        d += timedelta(days=1)
    return out


def build_history(days_src, out_path):
    entries = plan(days_src)
    new_calls, call_map, sess_map = [], {}, {}
    for date, i, s, shift, replay in entries:
        new_s = s if not replay else hashlib.sha1(f"{s}:{date:%Y%m%d}".encode()).hexdigest()[:12]
        sess_map[(i, s, date)] = new_s
        for c in days_src[i]["sessions"][s]:
            ts = date + c["office"] + timedelta(minutes=shift)
            lab = dict(c["lab"])
            if replay:
                lab["replay_of"] = s
            else:
                lab["recorded"] = f"2026-10-27 run {i + 1}"
            usage = json.loads(c["usage"] or "{}") if c["usage"] else {}
            new_calls.append({**{k: v for k, v in c.items() if k not in ("id", "office", "lab")},
                              "ts": ts.strftime(FMT), "session": new_s, "user": c["agent"],
                              "dept": lab.pop("department", None) or ("System" if c["agent"] == "firewall" else None),
                              "key_id": KEY_ID, "labels": json.dumps(lab),
                              "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
                              "total_tokens": usage.get("total_tokens"),
                              "_src": (i, c["id"], date)})
    new_calls.sort(key=lambda c: (c["ts"], c["_src"][1]))
    for n, c in enumerate(new_calls, 1):
        call_map[c.pop("_src")] = n
        c["id"] = n
    if os.path.exists(out_path):
        os.remove(out_path)
    db = sqlite3.connect(out_path)
    db.executescript(SCHEMA)
    cols = [r[1] for r in db.execute("PRAGMA table_info(calls)")]
    db.executemany(f"INSERT INTO calls ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                   [[c.get(k) for k in cols] for c in new_calls])
    # firewall findings and admin actions follow their call (or their session's first call)
    ts_of = {c["id"]: c["ts"] for c in new_calls}
    sigs, acts = [], []
    for date, i, s, shift, replay in sorted(entries, key=lambda e: (e[0], e[1], e[2])):
        new_s = sess_map[(i, s, date)]
        first = call_map[(i, days_src[i]["sessions"][s][0]["id"], date)]
        for kind, src, dst in (("signals", days_src[i]["signals"], sigs), ("actions", days_src[i]["actions"], acts)):
            for r in src:
                if r["session"] != s:
                    continue
                cid = call_map.get((i, r["call_id"], date)) if r.get("call_id") else None
                dst.append({**r, "session": new_s, "call_id": cid, "ts": ts_of.get(cid or first), "user": r.get("agent")})
    sigs.sort(key=lambda r: (r["ts"], r["id"]))
    acts.sort(key=lambda r: (r["ts"], r["id"]))
    for table, data in (("signals", sigs), ("admin_actions", acts)):
        if not data:
            continue
        cols = [k for k in data[0] if k != "id"]
        db.executemany(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                       [[r[k] for k in cols] for r in data])
    db.commit()
    db.execute("VACUUM")
    db.close()
    return len(new_calls), len({c["session"] for c in new_calls}), len(sigs), len(acts)


def xz(src, dst):
    with open(src, "rb") as fi, lzma.open(dst, "wb", preset=9 | lzma.PRESET_EXTREME) as fo:
        fo.write(fi.read())
    os.utime(dst, (0, 0))   # stable mtime: the console re-unpacks only when the archive really changes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("day1")
    ap.add_argument("day2")
    ap.add_argument("--out", default=os.path.join(ROOT, "demo", "data"))
    a = ap.parse_args()
    os.makedirs(os.path.join(a.out, ".cache"), exist_ok=True)
    days = [load_day(a.day1), load_day(a.day2)]
    tmp = os.path.join(a.out, ".cache", "vxc-4-weeks.db")
    n, s, g, x = build_history(days, tmp)
    xz(tmp, os.path.join(a.out, "vxc-4-weeks.db.xz"))
    print(f"vxc-4-weeks: {n} calls, {s} sessions, {g} signals, {x} admin actions, {os.path.getsize(tmp) >> 20} MB raw")
    raw = os.path.join(a.out, ".cache", "vxc-recorded-day.db")
    src = sqlite3.connect(f"file:{a.day1}?mode=ro", uri=True)
    if os.path.exists(raw):
        os.remove(raw)
    dst = sqlite3.connect(raw)
    src.backup(dst)
    dst.execute("VACUUM")
    dst.close()
    xz(raw, os.path.join(a.out, "vxc-recorded-day.db.xz"))
    for name in sorted(os.listdir(a.out)):
        if name.endswith(".xz"):
            print(f"  {name}: {os.path.getsize(os.path.join(a.out, name)) >> 10} KB")


if __name__ == "__main__":
    sys.exit(main())
