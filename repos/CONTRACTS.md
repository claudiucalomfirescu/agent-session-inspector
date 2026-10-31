# Ecosystem contracts (v1 proposal, 2026-10-30)

Shared surface between the four systems. Each contract has **one owner**; the owner's SPEC.md is
authoritative and consumers cite it by id and version (Prax Systems METHOD §6). This file is the
starting point the owners copy into their SPEC.md; once they do, their SPEC wins.

| Contract | Owner | Consumers |
|---|---|---|
| `K-openai-chat@1` | external (OpenAI-compatible API) | all |
| `K-agent-headers@1` | llm-proxy-log | llm-proxy-firewall, vxc-motors-sim, llm-session-console |
| `K-log-schema@1` | llm-proxy-log | llm-session-console |
| `K-log-schema@2` | llm-proxy-firewall | llm-session-console |
| `K-firewall-rules@1` | llm-proxy-firewall | (vxc-motors-sim ships its own rule file in this format) |
| `K-vxc-tools@1` | vxc-motors-sim | — |

## K-openai-chat@1
`POST /v1/chat/completions` with the OpenAI request/response shape (including `tools` and
`tool_calls`). `GET /v1/models` passed through. Non-streaming is required; streaming optional.

## K-agent-headers@1 — who is calling
Sent by clients, read and logged by the proxy, **stripped before forwarding upstream**.

| Header | Required | Meaning | Logged as |
|---|---|---|---|
| `X-Agent-User` | recommended | The human or agent persona the traffic belongs to (e.g. `maria.sales`). The console's "user". | `calls.user` |
| `X-Agent-Id` | optional | The agent program (e.g. `support-bot`). Defaults to `X-Agent-User`. | `calls.agent` |
| `X-Session-Id` | optional | Conversation id; proxy generates one per (agent, first message) if absent | `calls.session` |
| `X-Agent-Dept` | optional | Department / team | `calls.dept` |
| `X-Agent-<Anything>` | optional | Free labels | `calls.labels` (JSON object, key lower-cased without prefix) |

**Fallback identity:** when `X-Agent-User` is missing, `calls.user` = `key:` + first 8 hex chars of
SHA-256 of the client's bearer key (never the key itself); if there is no key, `anonymous`.

## K-log-schema@1 — SQLite file (default `logs/proxy.db`)
```sql
CREATE TABLE calls (
  id INTEGER PRIMARY KEY,
  ts TEXT,               -- ISO-8601 UTC, request start, e.g. 2026-10-30T21:00:00Z
  duration_ms INTEGER,
  user TEXT,             -- K-agent-headers: X-Agent-User or key:xxxxxxxx fallback
  agent TEXT,            -- X-Agent-Id (defaults to user)
  dept TEXT,             -- X-Agent-Dept, nullable
  session TEXT,
  method TEXT, path TEXT, status INTEGER,
  model TEXT,            -- model the client asked for
  upstream_model TEXT,   -- model that actually answered (fallbacks)
  finish_reason TEXT,
  usage TEXT,            -- JSON: {prompt_tokens, completion_tokens, total_tokens}
  cost_usd REAL,         -- nullable
  error TEXT,            -- nullable
  request TEXT,          -- JSON body as sent by the client (headers not stored)
  response TEXT,         -- JSON body as returned to the client
  labels TEXT            -- JSON object of extra X-Agent-* labels
);
```
Consumers MUST tolerate extra columns and extra tables.

## K-log-schema@2 = @1 plus firewall tables
```sql
ALTER TABLE calls ADD COLUMN firewall_level TEXT;  -- null | info | warning | block (max over signals of this call)
CREATE TABLE signals (
  id INTEGER PRIMARY KEY, ts TEXT, session TEXT, user TEXT, agent TEXT, call_id INTEGER, turn INTEGER,
  direction TEXT,   -- request | response
  level TEXT,       -- info | warning | block
  topic TEXT, detector TEXT, rule TEXT, matched TEXT, rationale TEXT, confidence REAL,
  excerpt TEXT, ref TEXT);
CREATE TABLE admin_actions (
  id INTEGER PRIMARY KEY, ts TEXT, actor TEXT,
  action TEXT,      -- block_session | unblock_session | replace_response | note
  session TEXT, user TEXT, agent TEXT, topic TEXT, reason TEXT, ref TEXT, call_id INTEGER);
```
The console detects @2 by the presence of the `signals` table and shows the firewall layer only then.

## K-firewall-rules@1
YAML file of topics, each with `id`, `level` (info|warning|block), keyword/co-occurrence rules and
an intent description (the format of today's `proxy/firewall_topics.yaml`, documented in the
firewall SPEC).

## K-vxc-tools@1
Each enterprise app is a local HTTP service (DuckDB-backed) and the agents see it only as
OpenAI-style tools. The motors-sim SPEC lists every tool, its HTTP route, and **what is really
behind it** (real service, mailbox, judgment agent).

## Shared fixture
`llm-proxy-log/demo/data/demo.db` (K-log-schema@1) and `llm-proxy-firewall/demo/data/demo.db`
(K-log-schema@2) are the fixtures llm-session-console's tests load. A schema change in an owner
repo that breaks the console's tests is a contract break and needs a new version.
