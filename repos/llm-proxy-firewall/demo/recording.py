"""Ship a recorded log with the repo, and load it back, so the dashboard has data without a key.

    python3 demo/recording.py export logs/recording.db demo/data/team-week.json
    python3 demo/recording.py load                      # every demo/data/*.json into logs/proxy.db
    python3 demo/recording.py load --redate-days 14     # spread the sessions over the last 14 days

The JSON file holds the three K-log-schema@2 tables (SPEC.md): {"calls": [...], "signals": [...],
"admin_actions": [...]}, JSON columns decoded; signals and actions point at calls by the calls' original id. Loading appends rows
to PROXY_LOG_DB with the proxy's own schema and skips sessions already in the log, so it is safe to run
twice. --redate-days moves each session, as a whole, to a random day in the N days ending at --anchor (default today;
same time of day, seeded, so repeatable); the rows get label "redated": true so nobody mistakes them for real dates.
"""
import argparse
import glob
import json
import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "proxy"))
from logstore import CALL_COLUMNS, open_db  # noqa: E402

BASE_COLUMNS = ["ts", "duration_ms", "agent", "session", "method", "path", "status", "model", "finish_reason",
                "usage", "error", "request", "response"]
COLUMNS = BASE_COLUMNS + list(CALL_COLUMNS)
JSON_COLUMNS = ("usage", "error", "request", "response", "labels")


def _decode(v):
    try:
        return json.loads(v) if isinstance(v, str) else v
    except ValueError:
        return v


SIDE_TABLES = ("signals", "admin_actions")  # K-log-schema@2: rows point at calls by call_id


def export(db_path, out_path):
    """{"calls": [...], "signals": [...], "admin_actions": [...]}; calls keep their id so the others can point at them."""
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    have = {r[1] for r in db.execute("PRAGMA table_info(calls)")}
    out = {"calls": [{"id": r["id"], **{c: (_decode(r[c]) if c in JSON_COLUMNS else r[c]) for c in COLUMNS if c in have}}
                     for r in db.execute("SELECT * FROM calls ORDER BY id")]}
    for t in SIDE_TABLES:
        out[t] = [{k: r[k] for k in r.keys() if k != "id"} for r in db.execute(f"SELECT * FROM {t} ORDER BY id")]
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"{out_path}: {len(out['calls'])} calls, {len({r['session'] for r in out['calls']})} sessions, "
          f"{len(out['signals'])} signals, {len(out['admin_actions'])} admin actions")


def _shift(ts, days):
    t = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) - timedelta(days=days)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _insert(db, table, row, columns=None):
    cols = [c for c in (columns or row) if c in row]
    vals = [json.dumps(row[c], ensure_ascii=False) if c in JSON_COLUMNS and row[c] is not None
            and not isinstance(row[c], str) else row[c] for c in cols]
    return db.execute(f"INSERT INTO {table} ({', '.join(f'{chr(34)}{c}{chr(34)}' for c in cols)}) "
                      f"VALUES ({', '.join('?' * len(cols))})", vals).lastrowid


def load(files, db_path, redate_days=0, seed=7, anchor=None):
    """Load recorded files (the format above, or a plain list of calls as llm-proxy-log ships) into a log.
    The firewall's own classifier calls (session firewall-intent) move with the session they judged."""
    db = open_db(db_path)
    present = {r[0] for r in db.execute("SELECT DISTINCT session FROM calls")}
    rng = random.Random(seed)
    today = datetime.strptime(anchor, "%Y-%m-%d").date() if anchor else datetime.now(timezone.utc).date()
    added = 0
    for path in files:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        data = data if isinstance(data, dict) else {"calls": data}
        calls = data["calls"]
        # which session each call belongs to for redating: an intent call belongs to the next agent call
        owner, nxt = {}, None
        for i in range(len(calls) - 1, -1, -1):
            s = calls[i].get("session")
            if s != "firewall-intent":
                nxt = s
            owner[i] = s if s != "firewall-intent" else nxt
        prev = None
        for i, r in enumerate(calls):  # an intent call after the last agent call belongs to the one before
            owner[i] = owner[i] or prev
            prev = owner[i]
        shift, ids = {}, {}
        for i, r in enumerate(calls):
            if owner[i] in present or (r.get("session") in present and r.get("session") != "firewall-intent"):
                continue
            r = dict(r)
            old_id = r.pop("id", None)
            if redate_days:
                s = owner[i]
                if s not in shift:  # whole session moves together, to a day in [today - N + 1, today]
                    recorded = datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ").date()
                    shift[s] = (recorded - today).days + rng.randrange(redate_days)
                r["ts"] = _shift(r["ts"], shift[s])
                r["labels"] = {**(r.get("labels") or {}), "redated": True}
            new_id = _insert(db, "calls", r, COLUMNS)
            if old_id is not None:
                ids[old_id] = new_id
            added += 1
        for t in SIDE_TABLES:
            for r in data.get(t, []):
                if r.get("session") in present:
                    continue
                r = dict(r)
                r["call_id"] = ids.get(r.get("call_id"))
                if redate_days and r.get("session") in shift and r.get("ts"):
                    r["ts"] = _shift(r["ts"], shift[r["session"]])
                _insert(db, t, r)
    db.commit()
    print(f"{db_path}: added {added} recorded calls" + ("" if added else " (already present)"))
    return added


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export")
    e.add_argument("db")
    e.add_argument("out")
    lo = sub.add_parser("load")
    lo.add_argument("files", nargs="*")
    lo.add_argument("--db", default=os.environ.get("PROXY_LOG_DB", "logs/proxy.db"))
    lo.add_argument("--redate-days", type=int, default=0)
    lo.add_argument("--anchor", help="last day of the spread, YYYY-MM-DD (default: today)")
    a = p.parse_args(argv)
    if a.cmd == "export":
        export(a.db, a.out)
    else:
        load(a.files or sorted(glob.glob(os.path.join(HERE, "data", "*.json"))), a.db, a.redate_days, anchor=a.anchor)


if __name__ == "__main__":
    main()
