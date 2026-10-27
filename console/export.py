"""Bake a log snapshot into self-contained pages, for the repo's viz/ folder and for publishing as artifacts.

    python3 console/export.py --demo                 # logs/demo.db -> viz/console.html + viz/mission-control.html
    python3 console/export.py logs/proxy.db          # a real log
    python3 console/export.py logs/proxy.db --since 2026-10-27T08:00 --until 2026-10-27T12:00

The pages are the same files the live server serves (console/web/); the snapshot is put in as
window.SNAPSHOT, so they render with no server: the console in read-only mode, mission control in
replay mode. The real provider key never reaches the log (the proxy redacts it); this script
redacts OPENROUTER_API_KEY again, in case.
"""
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import model  # noqa: E402

# The published artifacts of the demo day; the two pages link to each other.
PUBLISHED = {"console": "https://claude.ai/artifact/4qKXJBDNUJXZNcUJKNvipu", "mission": "https://claude.ai/artifact/WbX69o9po7W8Dx9Pjx1iT4"}
PAGES = {"console.html": "console.html", "mission.html": "mission-control.html"}


def window_copy(path, since, until):
    """A temporary copy of the log with only the rows inside [since, until)."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False).name
    shutil.copy(path, tmp)
    db = sqlite3.connect(tmp)
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ("calls", "signals", "admin_actions"):
        if t in tables:
            if since:
                db.execute(f"DELETE FROM {t} WHERE ts < ?", (since,))
            if until:
                db.execute(f"DELETE FROM {t} WHERE ts >= ?", (until,))
    db.commit()
    db.close()
    return tmp


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("db", nargs="?", default=os.path.join(model.ROOT, "logs", "proxy.db"))
    ap.add_argument("--demo", action="store_true", help="use logs/demo.db (seeded if missing)")
    ap.add_argument("--since")
    ap.add_argument("--until")
    ap.add_argument("--out", default=os.path.join(model.ROOT, "viz"))
    ap.add_argument("--console-url", default=os.environ.get("CONSOLE_URL"),
                    help="where the published console lives, linked from mission control (--demo: the demo artifact)")
    ap.add_argument("--mission-url", default=os.environ.get("MISSION_URL"))
    args = ap.parse_args()
    if args.demo:
        args.db = os.path.join(model.ROOT, "logs", "demo.db")
        if not os.path.exists(args.db):
            subprocess.run([sys.executable, os.path.join(HERE, "seed_demo.py"), "--out", args.db], check=True)
    path = window_copy(args.db, args.since, args.until) if args.since or args.until else args.db
    label = "synthetic demo day" if args.demo else os.path.relpath(args.db, model.ROOT)
    snap = model.build(path, source_label=label)
    snap["links"] = {"console": args.console_url or (PUBLISHED["console"] if args.demo else None),
                     "mission": args.mission_url or (PUBLISHED["mission"] if args.demo else None)}
    text = json.dumps(snap, separators=(",", ":"))
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        text = text.replace(key, "[REDACTED]")
    text = text.replace("</", "<\\/")  # nothing in the data can close the script tag
    os.makedirs(args.out, exist_ok=True)
    for src, dst in PAGES.items():
        with open(os.path.join(HERE, "web", src), encoding="utf-8") as f:
            page = f.read()
        page = page.replace("<!--SNAPSHOT-->", f"<script>window.SNAPSHOT = {text};</script>", 1)
        with open(os.path.join(args.out, dst), "w", encoding="utf-8") as f:
            f.write(page)
        print(f"{os.path.join(args.out, dst)}: {len(page) // 1024} KB, {snap['totals']['sessions']} sessions, "
              f"{snap['totals']['calls']} calls")


if __name__ == "__main__":
    main()
