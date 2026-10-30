"""Ship a recorded log with the repo, and load it back, so the dashboard has data without a key.

    python3 demo/recording.py export logs/recording.db demo/data/team-day.json
    python3 demo/recording.py load                      # every demo/data/*.json into logs/proxy.db
    python3 demo/recording.py load --redate-days 14     # spread the sessions over the last 14 days

The JSON file is a list of `calls` rows (SPEC.md), JSON columns decoded, ids dropped. Loading appends rows
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


def export(db_path, out_path):
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    have = {r[1] for r in db.execute("PRAGMA table_info(calls)")}
    rows = []
    for r in db.execute("SELECT * FROM calls ORDER BY id"):
        rows.append({c: (_decode(r[c]) if c in JSON_COLUMNS else r[c]) for c in COLUMNS if c in have})
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print(f"{out_path}: {len(rows)} calls, {len({r['session'] for r in rows})} sessions")


def _shift(ts, days):
    t = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) - timedelta(days=days)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def load(files, db_path, redate_days=0, seed=7, anchor=None):
    db = open_db(db_path)
    present = {r[0] for r in db.execute("SELECT DISTINCT session FROM calls")}
    rng = random.Random(seed)
    today = datetime.strptime(anchor, "%Y-%m-%d").date() if anchor else datetime.now(timezone.utc).date()
    added = 0
    for path in files:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f)
        shift = {}
        for r in rows:
            if r.get("session") in present:
                continue
            r = dict(r)
            if redate_days:
                s = r.get("session")
                if s not in shift:  # whole session moves together, to a day in [today - N + 1, today]
                    recorded = datetime.strptime(r["ts"], "%Y-%m-%dT%H:%M:%SZ").date()
                    shift[s] = (recorded - today).days + rng.randrange(redate_days)
                r["ts"] = _shift(r["ts"], shift[s])
                r["labels"] = {**(r.get("labels") or {}), "redated": True}
            cols = [c for c in COLUMNS if c in r]
            vals = [json.dumps(r[c], ensure_ascii=False) if c in JSON_COLUMNS and r[c] is not None
                    and not isinstance(r[c], str) else r[c] for c in cols]
            db.execute(f"INSERT INTO calls ({', '.join(f'{chr(34)}{c}{chr(34)}' for c in cols)}) "
                       f"VALUES ({', '.join('?' * len(cols))})", vals)
            added += 1
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
