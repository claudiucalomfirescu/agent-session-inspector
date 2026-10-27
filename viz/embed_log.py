"""Put a snapshot of the proxy log into a visualization page, so the page works offline and as a published artifact.

    python3 viz/embed_log.py                                   # logs/proxy.db -> viz/sequence.html
    python3 viz/embed_log.py viz/data/lesson3-sample-log.json  # a saved JSON snapshot instead
    python3 viz/embed_log.py logs/proxy.db --session c5300e26f24a --out viz/sequence.html

Rows are exported with request/response/usage/error parsed back into JSON. The proxy already
redacts the key before writing; this script redacts OPENROUTER_API_KEY again, in case.
"""
import argparse
import json
import os
import re
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))


def rows_from_db(path, sessions):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    q, args = "SELECT * FROM calls", ()
    if sessions:
        q += " WHERE session IN (%s)" % ",".join("?" * len(sessions))
        args = tuple(sessions)
    out = []
    for r in db.execute(q + " ORDER BY id", args):
        row = dict(r)
        for k in ("usage", "error", "request", "response", "labels"):
            if row.get(k):
                try:
                    row[k] = json.loads(row[k])
                except ValueError:
                    pass
        out.append(row)
    return out


def embed(page, rows):
    text = json.dumps(rows, separators=(",", ":"))
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        text = text.replace(key, "[REDACTED]")
    text = text.replace("</", "<\\/")  # keep the JSON from closing its <script> tag
    with open(page) as f:
        html = f.read()
    html, n = re.subn(r'(<script id="log-data" type="application/json">).*?(</script>)',
                      lambda m: m.group(1) + text + m.group(2), html, count=1, flags=re.S)
    if not n:
        raise SystemExit(f"{page} has no log-data block")
    with open(page, "w") as f:
        f.write(html)
    print(f"{len(rows)} calls embedded in {page}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("source", nargs="?", default=os.environ.get("PROXY_LOG_DB", "logs/proxy.db"))
    ap.add_argument("--session", action="append", help="only these sessions (repeatable)")
    ap.add_argument("--out", default=os.path.join(HERE, "sequence.html"))
    a = ap.parse_args()
    if a.source.endswith(".json"):
        with open(a.source) as f:
            rows = json.load(f)
        if a.session:
            rows = [r for r in rows if r.get("session") in a.session]
    else:
        rows = rows_from_db(a.source, a.session)
    embed(a.out, rows)
