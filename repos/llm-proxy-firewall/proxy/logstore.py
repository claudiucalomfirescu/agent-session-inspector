"""The proxy's SQLite log (K-log-schema@2): one file (logs/proxy.db), three tables.

  calls          one row per request through the proxy (K-log-schema@1, unchanged)
  signals        one row per firewall finding: session, user, turn, level (info / warning / block), topic,
                 which detector found it and what matched
  admin_actions  what was DONE about it: the firewall's automatic blocks and an administrator's manual
                 block / unblock / note, with who, when and why

The column list is a contract shared with other tools that read the log (the dashboard here, and the
separate llm-session-console). It is written down in SPEC.md; change both together.

  identity   agent (X-Agent-Id), session (X-Session-Id), user (X-Agent-User), dept (X-Agent-Dept),
             key_id (first 8 hex of sha256 of the client's API key; never the key itself),
             labels (JSON of every other X-Agent-* header)
  traffic    ts, duration_ms, method, path, status, model, finish_reason, error
  tokens     usage (the provider's JSON), and prompt/completion/total_tokens copied out of it
  bodies     request, response (secrets redacted)
  gateway    route, upstream_model, attempts, cost_usd
  firewall   firewall_level: the highest level of this call's signals (NULL = nothing found)

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
    """CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY, ts TEXT, session TEXT, user TEXT, agent TEXT, call_id INTEGER, turn INTEGER,
        direction TEXT,          -- request (what the agent sent) | response (what the LLM answered)
        level TEXT,              -- info | warning | block
        topic TEXT, detector TEXT,  -- keyword | intent_heuristic | intent_llm | grounding | escalation | session
        rule TEXT, matched TEXT, rationale TEXT, confidence REAL, excerpt TEXT, ref TEXT)""",
    """CREATE TABLE IF NOT EXISTS admin_actions (
        id INTEGER PRIMARY KEY, ts TEXT, actor TEXT, -- 'firewall' or the administrator's name
        action TEXT,             -- block_session | unblock_session | replace_response | note
        session TEXT, user TEXT, agent TEXT, topic TEXT, reason TEXT, ref TEXT, call_id INTEGER)""",
]
INDEXES = [
    "CREATE INDEX IF NOT EXISTS calls_session ON calls(session)",
    "CREATE INDEX IF NOT EXISTS calls_user ON calls(user)",
    "CREATE INDEX IF NOT EXISTS calls_ts ON calls(ts)",
    "CREATE INDEX IF NOT EXISTS signals_session ON signals(session)",
    "CREATE INDEX IF NOT EXISTS actions_session ON admin_actions(session)",
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
    for table in ("signals", "admin_actions"):  # logs written before K-log-schema@2 had no user column
        if "user" not in {r[1] for r in db.execute(f"PRAGMA table_info({table})")}:
            db.execute(f"ALTER TABLE {table} ADD COLUMN user TEXT")
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
