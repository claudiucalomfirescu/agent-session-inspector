"""Read-only access to one proxy log (SQLite) and every aggregate the console shows.

The log is written by the proxy (llm-proxy-log or llm-proxy-firewall). This module never writes to it:
it opens the file with `mode=ro` and keeps its own working copy of the light columns in an in-memory
table called `facts`, one row per call, so charts and tables never parse the big request/response JSON.

    calls          required. Columns are detected, so old logs (no user/dept/key_id) still work.
    signals        optional (firewall repo only): one row per firewall finding.
    admin_actions  optional (firewall repo only): automatic blocks and an admin's block/unblock/note.

Who is the "user" of a call (SPEC §3): calls.user (X-Agent-User, or the proxy's own
"key:<hash>" fallback), else labels.user, else "key:" + key_id, else agent (X-Agent-Id), else "anonymous".
"""
import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta

LEVELS = ("info", "warning", "block")
SYSTEM_AGENTS = tuple(a.strip() for a in os.environ.get("CONSOLE_SYSTEM_AGENTS", "firewall,console-").split(",") if a.strip())


def level_rank(level):
    return LEVELS.index(level) + 1 if level in LEVELS else 0


def _j(text):
    if not isinstance(text, str):
        return text
    try:
        return json.loads(text)
    except ValueError:
        return text


class Filters:
    """The filter every view shares: a date range, optionally one user, one dept, system traffic on/off."""

    def __init__(self, q=None):
        q = q or {}
        g = lambda k: (q.get(k) or [None])[0] if isinstance(q.get(k), list) else q.get(k)  # noqa: E731
        self.since = g("from") or None      # YYYY-MM-DD, inclusive
        self.until = g("to") or None        # YYYY-MM-DD, inclusive
        self.user = g("user") or None
        self.dept = g("dept") or None
        self.system = (g("system") or "0") in ("1", "true", "yes")

    def where(self, alias="f"):
        sql, args = [], []
        if self.since:
            sql.append(f"{alias}.day >= ?"); args.append(self.since)
        if self.until:
            sql.append(f"{alias}.day <= ?"); args.append(self.until)
        if self.user:
            sql.append(f"{alias}.user = ?"); args.append(self.user)
        if self.dept:
            sql.append(f"{alias}.dept = ?"); args.append(self.dept)
        if not self.system:
            sql.append(f"{alias}.is_system = 0")
        return (" WHERE " + " AND ".join(sql)) if sql else "", args


class Store:
    def __init__(self, path):
        if not os.path.exists(path):
            raise FileNotFoundError(path)
        self.path = path
        self.name = os.path.splitext(os.path.basename(path))[0]
        self.lock = threading.RLock()
        # autocommit: never hold a read transaction open, or the proxy could not write while we run
        self.db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.tables = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "calls" not in self.tables:
            raise ValueError(f"{path}: no `calls` table, not a proxy log")
        self.cols = {r[1] for r in self.db.execute("PRAGMA table_info(calls)")}
        self.has_firewall = "signals" in self.tables   # @1 logs may carry an always-NULL firewall_level column
        self.has_signals = "signals" in self.tables
        self.has_actions = "admin_actions" in self.tables
        self.last_id = 0
        self.db.execute("""CREATE TEMP TABLE facts (
            id INTEGER PRIMARY KEY, ts TEXT, day TEXT, hour INTEGER, dow INTEGER, user TEXT, dept TEXT,
            agent TEXT, session TEXT, status INTEGER, ok INTEGER, model TEXT, finish TEXT, duration_ms INTEGER,
            prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, cost REAL,
            fw TEXT, fw_rank INTEGER, is_system INTEGER, kind TEXT, tools INTEGER)""")
        for stmt in ("CREATE INDEX temp.f_user ON facts(user)", "CREATE INDEX temp.f_session ON facts(session)",
                     "CREATE INDEX temp.f_day ON facts(day)"):
            self.db.execute(stmt)
        self.db.execute("CREATE TEMP TABLE sig (id INTEGER PRIMARY KEY, ts TEXT, day TEXT, session TEXT, user TEXT,"
                        " call_id INTEGER, turn INTEGER, direction TEXT, level TEXT, topic TEXT, detector TEXT, rule TEXT,"
                        " matched TEXT, rationale TEXT, confidence REAL, excerpt TEXT, ref TEXT, is_system INTEGER)")
        self.db.execute("CREATE TEMP TABLE act (id INTEGER PRIMARY KEY, ts TEXT, day TEXT, actor TEXT, action TEXT,"
                        " session TEXT, user TEXT, topic TEXT, reason TEXT, ref TEXT, call_id INTEGER, is_system INTEGER)")
        self.refresh()

    # --- loading ----------------------------------------------------------------------------------
    def _c(self, name, fallback="NULL"):
        return name if name in self.cols else fallback

    def refresh(self):
        """Pull rows written since the last refresh (the proxy may still be appending: live mode)."""
        with self.lock:
            labels = self._c("labels")
            user_parts = [f"NULLIF({self._c('user')}, '')", f"json_extract({labels}, '$.user')" if labels != "NULL" else "NULL",
                          "'key:' || key_id" if "key_id" in self.cols else "NULL", f"NULLIF({self._c('agent')}, '')", "'anonymous'"]
            dept_parts = [f"NULLIF({self._c('dept')}, '')"]
            if labels != "NULL":
                dept_parts += [f"json_extract({labels}, '$.dept')", f"json_extract({labels}, '$.department')"]
            dept_parts.append("'(none)'")
            tok = lambda k: (f"COALESCE({k}, json_extract(usage, '$.{k}'))" if k in self.cols  # noqa: E731
                             else f"json_extract(usage, '$.{k}')")
            cost = (f"COALESCE(cost_usd, json_extract(usage, '$.cost'), 0)" if "cost_usd" in self.cols
                    else "COALESCE(json_extract(usage, '$.cost'), 0)")
            n_tools = "json_array_length(json_extract(request, '$.tools'))"
            rows = self.db.execute(f"""
                SELECT id, ts, COALESCE({', '.join(user_parts)}) AS user, COALESCE({', '.join(dept_parts)}) AS dept,
                       COALESCE({self._c('agent')}, '') AS agent, {self._c('session')} AS session, {self._c('status')} AS status,
                       {self._c('model')} AS model, {self._c('finish_reason')} AS finish_reason, {self._c('duration_ms')} AS duration_ms,
                       {tok('prompt_tokens')} AS pt, {tok('completion_tokens')} AS ct, {tok('total_tokens')} AS tt,
                       {cost} AS cost, {self._c('firewall_level')} AS fw,
                       {f"json_extract({labels}, '$.kind')" if labels != "NULL" else "NULL"} AS kind,
                       CASE WHEN json_valid({self._c('request', "''")}) THEN {n_tools} END AS tools,
                       {self._c('error')} AS error
                FROM calls WHERE id > ? ORDER BY id""", (self.last_id,)).fetchall()
            out = []
            for r in rows:
                ts = r["ts"] or ""
                try:
                    dt = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
                except ValueError:
                    dt = datetime(1970, 1, 1)
                user = str(r["user"])
                agent = r["agent"] or ""
                system = int(any(agent == a or (a.endswith("-") and agent.startswith(a)) for a in SYSTEM_AGENTS)
                             or any(user == a or (a.endswith("-") and user.startswith(a)) for a in SYSTEM_AGENTS))
                session = r["session"] or f"{user}@{ts[:10]}"   # no X-Session-Id: one session per user per day
                ok = int((r["status"] or 0) < 400 and not r["error"])
                out.append((r["id"], ts, ts[:10], dt.hour, dt.weekday(), user, r["dept"], agent, session, r["status"], ok,
                            r["model"], r["finish_reason"], r["duration_ms"], r["pt"] or 0, r["ct"] or 0,
                            r["tt"] or ((r["pt"] or 0) + (r["ct"] or 0)), r["cost"] or 0, r["fw"], level_rank(r["fw"]),
                            system, r["kind"], r["tools"] or 0))
            self.db.executemany("INSERT INTO facts VALUES (" + ",".join("?" * 23) + ")", out)
            if rows:
                self.last_id = rows[-1]["id"]
            self._load_firewall()
            return len(out)

    def _load_firewall(self):
        """Signals and admin actions are small; reload them whole and give each the call's user."""
        self.db.execute("DELETE FROM sig")
        self.db.execute("DELETE FROM act")
        who = "(SELECT user FROM facts WHERE facts.session = x.session LIMIT 1)"
        sysq = "(SELECT is_system FROM facts WHERE facts.session = x.session LIMIT 1)"
        cols = lambda t: {r[1] for r in self.db.execute(f"PRAGMA main.table_info({t})")}  # noqa: E731
        if self.has_signals:
            own = "NULLIF(x.user, ''), " if "user" in cols("signals") else ""
            self.db.execute(f"""INSERT INTO sig SELECT id, ts, substr(ts,1,10), session,
                COALESCE({own}(SELECT user FROM facts WHERE facts.id = x.call_id), {who}, agent), call_id, turn, direction,
                level, topic, detector, rule, matched, rationale, confidence, excerpt, ref, COALESCE({sysq}, 0)
                FROM main.signals x""")
        if self.has_actions:
            own = "NULLIF(x.user, ''), " if "user" in cols("admin_actions") else ""
            self.db.execute(f"""INSERT INTO act SELECT id, ts, substr(ts,1,10), actor, action, session,
                COALESCE({own}(SELECT user FROM facts WHERE facts.id = x.call_id), {who}, agent), topic, reason, ref, call_id,
                COALESCE({sysq}, 0) FROM main.admin_actions x""")

    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    # --- views ------------------------------------------------------------------------------------
    def meta(self):
        r = self.q("SELECT MIN(day) AS first, MAX(day) AS last, COUNT(*) AS calls, SUM(is_system) AS system_calls,"
                   " COUNT(DISTINCT user) AS users FROM facts")[0]
        return {"name": self.name, "path": self.path, "has_firewall": self.has_firewall, "has_signals": self.has_signals,
                "has_actions": self.has_actions, "identity": self.identity_source(), **r,
                "depts": [d["dept"] for d in self.q("SELECT DISTINCT dept FROM facts WHERE is_system = 0 ORDER BY dept")]}

    def identity_source(self):
        """Which header the users in this log came from (shown in the UI so nobody guesses)."""
        if "user" in self.cols and self.q("SELECT 1 FROM calls WHERE user IS NOT NULL AND user != '' LIMIT 1"):
            if self.q("SELECT 1 FROM calls WHERE user IS NOT NULL AND user != '' AND user NOT LIKE 'key:%'"
                      " AND user != 'anonymous' LIMIT 1"):
                return "X-Agent-User"
            return "API key"
        if "key_id" in self.cols and self.q("SELECT 1 FROM calls WHERE key_id IS NOT NULL LIMIT 1"):
            return "API key"
        return "X-Agent-Id"

    def _fw_counts(self, f, by=None):
        """Firewall findings (signals) by level, honouring the filter; with `by`, grouped by that column."""
        if not self.has_signals:
            return {} if by is None else []
        w, a = Filters.where(f, "s")
        w = w.replace("s.dept = ?", "s.user IN (SELECT DISTINCT user FROM facts WHERE dept = ?)")
        sel = f"{by} AS k, " if by else ""
        rows = self.q(f"SELECT {sel}level, COUNT(*) AS n FROM sig s{w} GROUP BY {'k, ' if by else ''}level", a)
        if by is None:
            return {r["level"]: r["n"] for r in rows}
        return rows

    def overview(self, f, bucket="day"):
        w, a = f.where()
        tot = self.q(f"""SELECT COUNT(*) AS calls, COUNT(DISTINCT session) AS sessions, COUNT(DISTINCT user) AS users,
                COALESCE(SUM(total_tokens),0) AS tokens, COALESCE(SUM(prompt_tokens),0) AS prompt_tokens,
                COALESCE(SUM(completion_tokens),0) AS completion_tokens, COALESCE(SUM(cost),0) AS cost,
                COALESCE(SUM(1-ok),0) AS errors, COUNT(DISTINCT day) AS days, MIN(day) AS first, MAX(day) AS last,
                CAST(AVG(duration_ms) AS INTEGER) AS avg_ms FROM facts f{w}""", a)[0]
        tot["firewall"] = self._fw_counts(f)
        tot["blocked_calls"] = self.q(f"SELECT COUNT(*) AS n FROM facts f{w}{' AND' if w else ' WHERE'} fw = 'block'", a)[0]["n"]
        return {"totals": tot, "series": self.series(f, bucket), "users": self.users(f),
                "depts": self.q(f"""SELECT dept, COUNT(*) AS calls, COUNT(DISTINCT user) AS users, COUNT(DISTINCT session) AS sessions,
                     SUM(total_tokens) AS tokens FROM facts f{w} GROUP BY dept ORDER BY calls DESC""", a),
                "heatmap": self.heatmap(f), "models": self.q(f"""SELECT COALESCE(model,'?') AS model, COUNT(*) AS calls,
                     SUM(total_tokens) AS tokens FROM facts f{w} GROUP BY model ORDER BY calls DESC""", a)}

    def _bucket_expr(self, bucket):
        if bucket == "week":   # ISO-ish week, labelled by its Monday
            return "date(day, '-' || ((CAST(strftime('%w', day) AS INTEGER) + 6) % 7) || ' days')"
        if bucket == "hour":
            return "substr(ts, 1, 13) || ':00'"
        return "day"

    def series(self, f, bucket="day"):
        """Per bucket: calls, sessions, active users, tokens, errors, and firewall findings by level.
        Empty days inside the range are filled with zeros so the axis is honest."""
        w, a = f.where()
        b = self._bucket_expr(bucket)
        rows = self.q(f"""SELECT {b} AS bucket, COUNT(*) AS calls, COUNT(DISTINCT session) AS sessions,
                COUNT(DISTINCT user) AS users, SUM(total_tokens) AS tokens, SUM(prompt_tokens) AS prompt_tokens,
                SUM(completion_tokens) AS completion_tokens, SUM(1-ok) AS errors, SUM(cost) AS cost,
                SUM(fw='block') AS blocked FROM facts f{w} GROUP BY bucket ORDER BY bucket""", a)
        by = {r["bucket"]: r for r in rows}
        for r in rows:
            r.update({"info": 0, "warning": 0, "block": 0})
        if self.has_signals:
            sb = b.replace("day", "s.day") if bucket != "hour" else "substr(s.ts, 1, 13) || ':00'"
            for r in self._fw_counts(f, by=sb):
                if r["k"] in by:
                    by[r["k"]][r["level"]] = r["n"]
        if rows:
            step = timedelta(days=7) if bucket == "week" else timedelta(hours=1) if bucket == "hour" else timedelta(days=1)
            fmt = "%Y-%m-%dT%H:00" if bucket == "hour" else "%Y-%m-%d"
            d, end = datetime.strptime(rows[0]["bucket"], fmt), datetime.strptime(rows[-1]["bucket"], fmt)
            filled = []
            while d <= end:
                k = d.strftime(fmt)
                filled.append(by.get(k) or {"bucket": k, "calls": 0, "sessions": 0, "users": 0, "tokens": 0, "prompt_tokens": 0,
                                            "completion_tokens": 0, "errors": 0, "cost": 0, "blocked": 0,
                                            "info": 0, "warning": 0, "block": 0})
                d += step
            rows = filled
        return rows

    def heatmap(self, f):
        """Calls by weekday (0 = Monday) and hour of day: when does this user / team talk to the LLM."""
        w, a = f.where()
        return self.q(f"SELECT dow, hour, COUNT(*) AS calls FROM facts f{w} GROUP BY dow, hour", a)

    def users(self, f):
        w, a = f.where()
        rows = self.q(f"""SELECT user, MAX(dept) AS dept, GROUP_CONCAT(DISTINCT agent) AS agents, COUNT(*) AS calls,
                COUNT(DISTINCT session) AS sessions, COUNT(DISTINCT day) AS active_days, SUM(total_tokens) AS tokens,
                SUM(cost) AS cost, SUM(1-ok) AS errors, MIN(ts) AS first_seen, MAX(ts) AS last_seen,
                MAX(fw_rank) AS fw_rank, SUM(fw='block') AS blocked, MAX(is_system) AS is_system
                FROM facts f{w} GROUP BY user ORDER BY calls DESC""", a)
        fw = {}
        for r in self._fw_counts(f, by="s.user"):
            fw.setdefault(r["k"], {})[r["level"]] = r["n"]
        spark = {}
        for r in self.q(f"SELECT user, day, COUNT(*) AS n FROM facts f{w} GROUP BY user, day", a):
            spark.setdefault(r["user"], {})[r["day"]] = r["n"]
        for r in rows:
            r["firewall"] = fw.get(r["user"], {})
            r["max_level"] = LEVELS[r["fw_rank"] - 1] if r["fw_rank"] else (
                "block" if r["firewall"].get("block") else "warning" if r["firewall"].get("warning")
                else "info" if r["firewall"].get("info") else None)
            r["by_day"] = spark.get(r["user"], {})
        return rows

    def user(self, user, f, bucket="day"):
        f.user = user
        ov = self.overview(f, bucket)
        if not ov["users"]:
            return None
        return {"user": ov["users"][0], "totals": ov["totals"], "series": ov["series"], "heatmap": ov["heatmap"],
                "models": ov["models"], "sessions": self.sessions(f), "tools": self.tool_usage(f)}

    def sessions(self, f, level=None, limit=2000):
        w, a = f.where()
        rows = self.q(f"""SELECT session, user, MAX(dept) AS dept, GROUP_CONCAT(DISTINCT agent) AS agents, MIN(ts) AS started,
                MAX(ts) AS ended, COUNT(*) AS calls, SUM(total_tokens) AS tokens, SUM(cost) AS cost, SUM(1-ok) AS errors,
                MAX(fw_rank) AS fw_rank, SUM(fw='block') AS blocked, SUM(duration_ms) AS llm_ms, MIN(id) AS first_call
                FROM facts f{w} GROUP BY session ORDER BY started DESC LIMIT ?""", a + [limit])
        sig = {}
        if self.has_signals:
            for r in self.q("SELECT session, level, COUNT(*) AS n FROM sig GROUP BY session, level"):
                sig.setdefault(r["session"], {})[r["level"]] = r["n"]
        titles = self._session_titles([r["first_call"] for r in rows])
        for r in rows:
            r["firewall"] = sig.get(r["session"], {})
            ranks = [r["fw_rank"] or 0] + [level_rank(lv) for lv in r["firewall"]]
            r["max_level"] = LEVELS[max(ranks) - 1] if max(ranks) else None
            r["title"] = titles.get(r["first_call"])
        if level:
            rows = [r for r in rows if level_rank(r["max_level"]) >= level_rank(level)]
        return rows

    def _session_titles(self, call_ids):
        """A short title per session: labels.title if the client sent one, else the first user message."""
        out = {}
        ids = [i for i in call_ids if i]
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            lab = "labels" if "labels" in self.cols else "NULL"
            for r in self.q(f"""SELECT id, json_extract({lab}, '$.title') AS t, request FROM calls
                                 WHERE id IN ({','.join('?' * len(chunk))})""", chunk):
                t = r["t"]
                if not t:
                    req = _j(r["request"])
                    msgs = req.get("messages") if isinstance(req, dict) else None
                    for m in msgs or []:
                        if m.get("role") == "user" and isinstance(m.get("content"), str):
                            t = m["content"]
                            break
                out[r["id"]] = (t or "").strip().replace("\n", " ")[:120] or None
        return out

    def tool_usage(self, f):
        """Which tools the LLM asked this user's agent to call, counted from the responses."""
        w, a = f.where()
        counts = {}
        for r in self.q(f"SELECT c.response FROM calls c JOIN facts f ON f.id = c.id{w} AND f.finish = 'tool_calls'"
                        if w else "SELECT c.response FROM calls c JOIN facts f ON f.id = c.id WHERE f.finish = 'tool_calls'", a):
            from .transcript import parse_response
            msg = parse_response(r["response"]).get("message") or {}
            for tc in msg.get("tool_calls") or []:
                name = (tc.get("function") or {}).get("name") or "?"
                counts[name] = counts.get(name, 0) + 1
        return sorted(({"tool": k, "calls": v} for k, v in counts.items()), key=lambda x: -x["calls"])

    def session(self, session):
        from .transcript import build_session
        calls = self.q("SELECT c.*, f.user, f.dept, f.total_tokens, f.prompt_tokens, f.completion_tokens, f.cost AS cost"
                       " FROM calls c JOIN facts f ON f.id = c.id WHERE f.session = ? ORDER BY c.id", (session,))
        if not calls:
            return None
        sigs = self.q("SELECT * FROM sig WHERE session = ? ORDER BY id", (session,)) if self.has_signals else []
        acts = self.q("SELECT * FROM act WHERE session = ? ORDER BY id", (session,)) if self.has_actions else []
        return build_session(session, calls, sigs, acts)

    def call(self, call_id):
        rows = self.q("SELECT c.*, f.user, f.dept, f.session AS session_key FROM calls c JOIN facts f ON f.id = c.id"
                      " WHERE c.id = ?", (call_id,))
        if not rows:
            return None
        r = rows[0]
        for k in ("request", "response", "usage", "labels", "error"):
            if k in r:
                r[k] = _j(r[k].strip() if isinstance(r[k], str) else r[k])
        r["signals"] = self.q("SELECT * FROM sig WHERE call_id = ?", (call_id,)) if self.has_signals else []
        return r

    def firewall(self, f, level=None, topic=None, limit=1000):
        """Every finding, newest first, plus the counts the firewall page charts."""
        if not self.has_signals:
            return {"enabled": False, "events": [], "topics": [], "actions": []}
        w, a = Filters.where(f, "s")
        w = w.replace("s.dept = ?", "s.user IN (SELECT DISTINCT user FROM facts WHERE dept = ?)")
        extra, ea = [], []
        if level:
            extra.append("s.level = ?"); ea.append(level)
        if topic:
            extra.append("s.topic = ?"); ea.append(topic)
        if extra:
            w = (w + " AND " if w else " WHERE ") + " AND ".join(extra)
        events = self.q(f"SELECT s.* FROM sig s{w} ORDER BY s.ts DESC, s.id DESC LIMIT ?", a + ea + [limit])
        topics = self.q(f"SELECT s.topic, s.level, COUNT(*) AS n, COUNT(DISTINCT s.user) AS users FROM sig s{w}"
                        " GROUP BY s.topic, s.level", a + ea)
        detectors = self.q(f"SELECT s.detector, s.level, COUNT(*) AS n FROM sig s{w} GROUP BY s.detector, s.level", a + ea)
        aw, aa = Filters.where(f, "x")
        aw = aw.replace("x.dept = ?", "x.user IN (SELECT DISTINCT user FROM facts WHERE dept = ?)")
        actions = self.q(f"SELECT x.* FROM act x{aw} ORDER BY x.ts DESC LIMIT ?", aa + [limit]) if self.has_actions else []
        return {"enabled": True, "events": events, "topics": topics, "detectors": detectors, "actions": actions}

    def galaxy(self, f):
        """Compact node lists for the 3D view: users and their sessions (messages load on demand)."""
        users = self.users(f)
        sessions = self.sessions(f, limit=5000)
        keep = {"session", "user", "calls", "tokens", "max_level", "started", "title", "dept"}
        return {"users": [{k: u[k] for k in ("user", "dept", "calls", "sessions", "tokens", "max_level", "is_system")}
                          for u in users],
                "sessions": [{k: s[k] for k in keep} for s in sessions]}

    def search(self, text, f, limit=100):
        """Calls whose request or response contains `text` (case-insensitive LIKE)."""
        w, a = f.where()
        like = f"%{text}%"
        cond = "(c.request LIKE ? OR c.response LIKE ?)"
        sql = (f"SELECT f.id, f.ts, f.user, f.session, f.fw FROM facts f JOIN calls c ON c.id = f.id{w}"
               f"{' AND ' if w else ' WHERE '}{cond} ORDER BY f.id DESC LIMIT ?")
        rows = self.q(sql, a + [like, like, limit])
        for r in rows:  # a snippet around the first hit, from the newest message only
            c = self.q("SELECT request, response FROM calls WHERE id = ?", (r["id"],))[0]
            for blob in (c["response"] or "", c["request"] or ""):
                i = blob.lower().find(text.lower())
                if i >= 0:
                    r["snippet"] = blob[max(0, i - 80): i + 80 + len(text)].replace("\\n", " ")
                    break
        return rows
