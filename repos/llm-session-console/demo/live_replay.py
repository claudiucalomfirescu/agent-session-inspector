"""Watch the console update live without a proxy or an API key.

    python3 demo/live_replay.py                       # replays the recorded VXC day into demo/data/.cache/live.db
    python3 -m console --db demo/data/.cache/live.db  # in another terminal; refresh the browser and watch it grow

It copies the calls (and firewall findings / admin actions) of a recorded log into a fresh log file one
by one, in the order and roughly at the pace they happened (--speed 20 = twenty times faster), exactly
as a running proxy would append them. The console notices the file changing and shows the new rows on
the next request (SPEC R-016). With a real proxy you skip this: point --db at its log.
"""
import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from console.server import unpack_samples  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", help="recorded log to replay (default: the bundled recorded day)")
    ap.add_argument("--out", default=os.path.join(ROOT, "demo", "data", ".cache", "live.db"))
    ap.add_argument("--speed", type=float, default=20.0)
    a = ap.parse_args()
    src = a.src or next(p for p in unpack_samples() if p.endswith("vxc-recorded-day.db"))
    s = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    if os.path.exists(a.out):
        os.remove(a.out)
    d = sqlite3.connect(a.out)
    tables = [r[0] for r in s.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for (sql,) in s.execute("SELECT sql FROM sqlite_master WHERE type='table'"):
        d.execute(sql)
    d.commit()
    events = []
    for t in tables:
        cols = [r[1] for r in s.execute(f"PRAGMA table_info({t})")]
        for row in s.execute(f"SELECT * FROM {t} ORDER BY id"):
            r = dict(zip(cols, row))
            events.append((r.get("ts") or "", 0 if t == "calls" else 1, t, cols, row))
    events.sort(key=lambda e: e[:2])
    print(f"replaying {len(events)} rows from {src} into {a.out} at {a.speed}x; Ctrl-C to stop")
    prev = None
    for ts, _, t, cols, row in events:
        when = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S") if ts else None
        if prev and when:
            time.sleep(max(0, min(5, (when - prev).total_seconds() / a.speed)))
        prev = when or prev
        d.execute(f"INSERT INTO {t} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", row)
        d.commit()
        if t == "calls":
            print(f"  {ts}  {t:<14} {row[cols.index('agent')] if 'agent' in cols else ''}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
