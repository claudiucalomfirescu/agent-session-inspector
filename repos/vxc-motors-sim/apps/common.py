"""Shared plumbing for the VXC Motors systems: databases, the tool registry, permissions, audit.

Every system function is a *tool*: a plain Python function plus a JSON-schema spec that an
OpenAI-compatible tool-calling agent can use. Tools are registered with the @tool decorator:

    @tool("crm", "Search customers by name, email, phone or postcode.",
          query=Param("string", "free text"), limit=Param("integer", "max rows", default=10))
    def crm_search_customers(ctx, query, limit=10): ...

`ctx` (a Context) says who is calling (`ctx.actor`, a persona id), gives a DuckDB cursor
(`ctx.db`) and the current time (`ctx.now`). A tool returns any JSON-serialisable value, or
raises ToolError for a business-rule refusal the agent should read and react to.
"""
from __future__ import annotations

import datetime as dt
import decimal
import inspect
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("VXC_DATA_DIR", ROOT / "data"))
DB_FILES = {"internal": "vxc.duckdb", "bmw_portal": "bmw_portal.duckdb"}

# Internal systems share one company database; the BMW portal is "external" and keeps its own.
SYSTEM_DB = {"crm": "internal", "dms": "internal", "workshop": "internal", "parts": "internal",
             "finance": "internal", "mail": "internal", "chat": "internal", "bmw_portal": "bmw_portal"}

# People outside the company (customers, BMW staff, a recruiter) are agents too. They have an email
# address and nothing else: actor id "ext:<email>", and only these mail tools.
EXTERNAL_PREFIX = "ext:"
EXTERNAL_TOOLS = {"mail_inbox", "mail_read", "mail_send"}


class ToolError(Exception):
    """A refusal or validation failure. The message is shown to the agent as the tool result."""


@dataclass
class Param:
    type: str
    description: str
    default: Any = inspect.Parameter.empty
    enum: list | None = None
    items: dict | None = None

    def schema(self) -> dict:
        s = {"type": self.type, "description": self.description}
        if self.enum:
            s["enum"] = self.enum
        if self.items:
            s["items"] = self.items
        return s


@dataclass
class Tool:
    name: str
    system: str
    description: str
    params: dict[str, Param]
    fn: Callable
    writes: bool
    # Optional slow step run BEFORE the database lock is taken, e.g. asking another agent (an LLM call).
    # prepare(actor, args) -> value handed to the tool as ctx.prepared.
    prepare: Callable | None = None

    def spec(self) -> dict:
        required = [k for k, p in self.params.items() if p.default is inspect.Parameter.empty]
        return {"type": "function", "function": {
            "name": self.name, "description": f"[{self.system}] {self.description}",
            "parameters": {"type": "object",
                           "properties": {k: p.schema() for k, p in self.params.items()},
                           "required": required}}}


REGISTRY: dict[str, Tool] = {}


def tool(_system: str, _description: str, writes: bool = False, prepare: Callable | None = None, **params: Param):
    def deco(fn):
        REGISTRY[fn.__name__] = Tool(fn.__name__, _system, _description, params, fn, writes, prepare)
        return fn
    return deco


def now() -> dt.datetime:
    """Simulation clock: VXC_NOW (ISO timestamp) if set, else real UTC time (naive)."""
    fixed = os.environ.get("VXC_NOW")
    if fixed:
        return dt.datetime.fromisoformat(fixed)
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)


def jsonable(v):
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    return v


@dataclass
class Context:
    actor: str
    db: Any                     # duckdb cursor for the system's database
    now: dt.datetime = field(default_factory=now)
    persona: dict = field(default_factory=dict)
    prepared: Any = None

    def rows(self, sql: str, params: list | tuple = ()) -> list[dict]:
        cur = self.db.execute(sql, list(params))
        cols = [d[0] for d in cur.description]
        return [jsonable(dict(zip(cols, r))) for r in cur.fetchall()]

    def row(self, sql: str, params: list | tuple = ()) -> dict | None:
        r = self.rows(sql, params)
        return r[0] if r else None

    def scalar(self, sql: str, params: list | tuple = ()):
        r = self.db.execute(sql, list(params)).fetchone()
        return r[0] if r else None

    def next_id(self, table: str, col: str, prefix: str, width: int = 5) -> str:
        """Next sequential id like 'L-00042' for a VARCHAR key column."""
        n = self.scalar(f"SELECT max(CAST(substr({col}, {len(prefix) + 1}) AS INTEGER)) FROM {table} "
                        f"WHERE {col} LIKE ?", [prefix + "%"]) or 0
        return f"{prefix}{n + 1:0{width}d}"


class Store:
    """One DuckDB connection per database per process, serialised with a lock.

    DuckDB allows one writing process per file, so in a multi-agent run either all agents share
    this process (threads), or they call systems/server.py over HTTP.
    """
    _instances: dict[str, "Store"] = {}
    _lock = threading.Lock()

    def __init__(self, name: str):
        self.name = name
        self.path = DATA / DB_FILES[name]
        if not self.path.exists():
            from apps import seed  # build the seeded history on first use
            seed.build()
        self.con = duckdb.connect(str(self.path))
        self.lock = threading.RLock()

    @classmethod
    def get(cls, name: str) -> "Store":
        with cls._lock:
            s = cls._instances.get(name)
            if s is None or s.path != DATA / DB_FILES[name]:
                s = cls._instances[name] = Store(name)
            return s

    @classmethod
    def close_all(cls):
        with cls._lock:
            for s in cls._instances.values():
                s.con.close()
            cls._instances.clear()


# ---------------------------------------------------------------- personas & permissions

_PERSONAS: dict[str, dict] | None = None


def personas() -> dict[str, dict]:
    """Persona frontmatter keyed by id, read from company/personas/*.md (the source of truth)."""
    global _PERSONAS
    if _PERSONAS is None:
        import yaml
        out = {}
        for p in sorted((ROOT / "company" / "personas").glob("*.md")):
            _, front, _ = p.read_text(encoding="utf-8").split("---", 2)
            meta = yaml.safe_load(front)
            out[meta["id"]] = meta
        _PERSONAS = out
    return _PERSONAS


def persona_by_email(email: str) -> dict | None:
    return next((p for p in personas().values() if p.get("email") == email), None)


def external_actor(email: str) -> str:
    return EXTERNAL_PREFIX + email.strip().lower()


def profile(actor: str) -> dict | None:
    """Who is calling: a staff persona, or a minimal profile for an outside actor ("ext:<email>")."""
    if actor.startswith(EXTERNAL_PREFIX):
        email = actor[len(EXTERNAL_PREFIX):]
        if "@" not in email:
            return None
        return {"id": actor, "name": email, "email": email, "systems": ["mail"], "external": True}
    return personas().get(actor)


def call(actor: str, name: str, args: dict | None = None) -> Any:
    """Run one tool as `actor`, enforce system access, write the audit row. Returns jsonable data.

    Raises ToolError on refusals (also audited)."""
    args = dict(args or {})
    t = REGISTRY.get(name)
    if t is None:
        raise ToolError(f"unknown tool {name}")
    p = profile(actor)
    if p is None:
        raise ToolError(f"unknown user {actor}")
    prepared, prep_err = None, None
    if t.prepare and t.system in p.get("systems", []) and not p.get("external"):
        try:
            prepared = t.prepare(actor, args)
        except ToolError as e:
            prep_err = str(e)
    store = Store.get(SYSTEM_DB[t.system])
    with store.lock:
        cur = store.con.cursor()
        ctx = Context(actor=actor, db=cur, persona=p, prepared=prepared)
        ok, err, result = True, None, None
        try:
            if prep_err:
                raise ToolError(prep_err)
            if t.system not in p.get("systems", []):
                raise ToolError(f"access denied: {p['name']} has no {t.system} account")
            if p.get("external") and name not in EXTERNAL_TOOLS:
                raise ToolError(f"access denied: {name} is an internal VXC Motors tool")
            unknown = set(args) - set(t.params)
            if unknown:
                raise ToolError(f"unknown argument(s) {sorted(unknown)} for {name}")
            missing = [k for k, prm in t.params.items() if prm.default is inspect.Parameter.empty and k not in args]
            if missing:
                raise ToolError(f"missing argument(s) {missing} for {name}")
            if t.writes:
                cur.execute("BEGIN")
            try:
                result = jsonable(t.fn(ctx, **args))
                if t.writes:
                    cur.execute("COMMIT")
            except Exception:
                if t.writes:
                    cur.execute("ROLLBACK")
                raise
        except ToolError as e:
            ok, err = False, str(e)
        except (duckdb.Error, TypeError, ValueError, KeyError) as e:
            ok, err = False, f"{type(e).__name__}: {e}"
        _audit(cur, ctx, t, args, ok, err, result)
        cur.close()
    if not ok:
        raise ToolError(err)
    return result


def _audit(cur, ctx, t, args, ok, err, result):
    table = "portal_access_log" if t.system == "bmw_portal" else "audit_log"
    summary = err if not ok else json.dumps(result, default=str)[:300]
    cur.execute(f"INSERT INTO {table} (occurred_at, actor, system, tool, args, ok, result_summary) VALUES (?,?,?,?,?,?,?)",
                [ctx.now, ctx.actor, t.system, t.name, json.dumps(args, default=str), ok, summary])


def call_json(actor: str, name: str, args: dict | None = None) -> str:
    """Like call(), but always returns a JSON string (errors as {"error": ...}): what an agent sees."""
    try:
        return json.dumps(call(actor, name, args), default=str)
    except ToolError as e:
        return json.dumps({"error": str(e)})
