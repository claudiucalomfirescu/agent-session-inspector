"""The proxy's SQLite log: one file (logs/proxy.db), one table `calls`, one row per request.

The column list is a contract shared with other tools that read the log (the dashboard here, and the
separate llm-session-console). It is written down in SPEC.md; change both together.

  identity   agent (X-Agent-Id), session (X-Session-Id), user (X-Agent-User), dept (X-Agent-Dept),
             key_id (first 8 hex of sha256 of the client's API key; never the key itself),
             labels (JSON of every other X-Agent-* header)
  traffic    ts, duration_ms, method, path, status, model, finish_reason, error
  tokens     usage (the provider's JSON), and prompt/completion/total_tokens copied out of it
  bodies     request, response (secrets redacted)
  gateway    route, upstream_model, attempts, cost_usd
  firewall   firewall_level (always NULL here; filled by the llm-proxy-firewall variant)

Older files get missing columns on first open. Writes never raise: a logging failure must not change
what the agent gets back.
"""
import json
import os
import sqlite3
import sys
import threading
import time

# Every column after the original step-3 table, with its type. Added to old files on open.
CALL_COLUMNS = {"user": "TEXT", "dept": "TEXT", "key_id": "TEXT",
                "prompt_tokens": "INTEGER", "completion_tokens": "INTEGER", "total_tokens": "INTEGER",
                "route": "TEXT", "upstream_model": "TEXT", "attempts": "INTEGER", "cost_usd": "REAL",
                "labels": "TEXT", "firewall_level": "TEXT"}

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS calls (
        id INTEGER PRIMARY KEY, ts TEXT, duration_ms INTEGER, agent TEXT, session TEXT,
        method TEXT, path TEXT, status INTEGER, model TEXT, finish_reason TEXT,
        usage TEXT, error TEXT, request TEXT, response TEXT)""",
]
INDEXES = [
    "CREATE INDEX IF NOT EXISTS calls_session ON calls(session)",
    "CREATE INDEX IF NOT EXISTS calls_user ON calls(user)",
    "CREATE INDEX IF NOT EXISTS calls_ts ON calls(ts)",
]


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


def open_db(path):
    """Open (and create or upgrade) a log file. Used by the proxy and by the demo loader."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False)
    for stmt in SCHEMA:
        db.execute(stmt)
    have = {r[1] for r in db.execute("PRAGMA table_info(calls)")}
    for col, kind in CALL_COLUMNS.items():
        if col not in have:
            db.execute(f"ALTER TABLE calls ADD COLUMN {col} {kind}")
    for stmt in INDEXES:
        db.execute(stmt)
    db.commit()
    return db


class LogStore:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self._db = None

    def db(self):
        if self._db is None:
            self._db = open_db(self.path)
        return self._db

    def insert(self, table, row):
        """Insert a dict as one row; returns the new id, or None if the write failed."""
        try:
            with self.lock:
                cols = ", ".join(f'"{c}"' for c in row)
                cur = self.db().execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(row))})",
                                        [json.dumps(v) if isinstance(v, (dict, list)) else v for v in row.values()])
                self.db().commit()
                return cur.lastrowid
        except Exception as e:  # noqa: BLE001
            print(f"log write to {table} failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
            return None

    def query(self, sql, args=()):
        with self.lock:
            cur = self.db().execute(sql, args)
            names = [d[0] for d in cur.description]
            return [dict(zip(names, r)) for r in cur.fetchall()]
