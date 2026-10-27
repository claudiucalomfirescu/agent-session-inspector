"""The proxy's SQLite log: one file (logs/proxy.db), three tables.

  calls          one row per request through the proxy (lesson 3; gateway columns from 3b,
                 firewall_level from 9). Old files get new columns on first open.
  signals        one row per firewall finding: which session and turn, the level (info / warning /
                 block), the topic, which detector found it and what matched (lesson 8).
  admin_actions  what was DONE about it: the firewall's automatic blocks and an administrator's
                 manual block / unblock / note, with who, when and why (lesson 9).

Writes never raise: a logging failure must not change what the agent gets back.
"""
import json
import os
import sqlite3
import sys
import threading
import time

# Columns added to `calls` after step 3.
CALL_COLUMNS = {"route": "TEXT", "upstream_model": "TEXT", "attempts": "INTEGER", "cost_usd": "REAL",
                "labels": "TEXT", "firewall_level": "TEXT"}

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS calls (
        id INTEGER PRIMARY KEY, ts TEXT, duration_ms INTEGER, agent TEXT, session TEXT,
        method TEXT, path TEXT, status INTEGER, model TEXT, finish_reason TEXT,
        usage TEXT, error TEXT, request TEXT, response TEXT)""",
    """CREATE TABLE IF NOT EXISTS signals (
        id INTEGER PRIMARY KEY, ts TEXT, session TEXT, agent TEXT, call_id INTEGER, turn INTEGER,
        direction TEXT,          -- request (what the agent sent) | response (what the LLM answered)
        level TEXT,              -- info | warning | block
        topic TEXT, detector TEXT,  -- keyword | intent_heuristic | intent_llm | escalation | session
        rule TEXT, matched TEXT, rationale TEXT, confidence REAL, excerpt TEXT, ref TEXT)""",
    """CREATE TABLE IF NOT EXISTS admin_actions (
        id INTEGER PRIMARY KEY, ts TEXT, actor TEXT, -- 'firewall' or the administrator's name
        action TEXT,             -- block_session | unblock_session | replace_response | note
        session TEXT, agent TEXT, topic TEXT, reason TEXT, ref TEXT, call_id INTEGER)""",
    "CREATE INDEX IF NOT EXISTS signals_session ON signals(session)",
    "CREATE INDEX IF NOT EXISTS actions_session ON admin_actions(session)",
]


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z"


class LogStore:
    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        self._db = None

    def db(self):
        if self._db is None:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            self._db = sqlite3.connect(self.path, check_same_thread=False)
            for stmt in SCHEMA:
                self._db.execute(stmt)
            have = {r[1] for r in self._db.execute("PRAGMA table_info(calls)")}
            for col, kind in CALL_COLUMNS.items():
                if col not in have:
                    self._db.execute(f"ALTER TABLE calls ADD COLUMN {col} {kind}")
            self._db.commit()
        return self._db

    def insert(self, table, row):
        """Insert a dict as one row; returns the new id, or None if the write failed."""
        try:
            with self.lock:
                cols = ", ".join(row)
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
