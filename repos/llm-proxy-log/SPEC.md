# Specification · llm-proxy-log

> Source of truth. If a behaviour is not here, a rebuild may drop it.
> Version: 1.0 · Contracts provided: K-agent-headers@1, K-log-schema@1 · Contracts used: K-openai-chat@1

## 1. Glossary
| Term | Meaning |
|---|---|
| Provider | The real LLM API (OpenRouter by default; any OpenAI-compatible API). |
| Agent | A program that calls the LLM: a support bot, a coding assistant. Identified by `X-Agent-Id`. |
| User | The person (or persona) an agent works for. Identified by `X-Agent-User`. The unit the dashboard and console group by. |
| Session | One conversation or task: every LLM call that shares the same message history. Identified by `X-Session-Id`. |
| Call | One HTTP request through the proxy and its answer: one row in `calls`. |
| Turn | One chat completion inside a session. A session with tool use has several turns. |
| Gateway | The proxy's budget layer: rate limit, retries, fallback model, spend cap, replay cache. |
| Real key | The provider API key. Only the proxy process holds it. |
| Client key | Whatever key the agent sends (often a dummy). Never forwarded; only its hash is logged. |
| Demo team | Four made-up agents at "Brightleaf Software" used to generate demo traffic. |

## 2. Components
| Id | Component | Responsibility | Inputs | Outputs |
|---|---|---|---|---|
| C-01 | proxy (`proxy/proxy.py`) | Forward every request to the provider with the real key; record it | HTTP from agents | HTTP to provider; rows in `calls` |
| C-02 | log store (`proxy/logstore.py`) | Create/upgrade the SQLite file; write rows without ever raising | rows | `logs/proxy.db` |
| C-03 | gateway (`proxy/gateway.py`) | Rate limit, retry, fall back, cap spend, cache replies for chat completions | chat requests | provider calls; `logs/gateway.db` |
| C-04 | dashboard (`dashboard/`) | Read the log read-only; show KPIs, calls per day per user, users, sessions, a transcript | `logs/proxy.db` | web page + JSON API on :8091 |
| C-05 | client helper (`client/`) | Make an OpenAI SDK client that sends the identity headers | agent name, user, dept | headers on every call |
| C-06 | demo (`demo/`) | A four-agent team with tools over a made-up company; offline fake LLM; recorded data | scenarios | traffic; `demo/data/` |

## 3. Contracts

### K-openai-chat@1 (used)
`POST /v1/chat/completions` with the OpenAI request/response shape, including `tools`,
`tool_calls` and `usage`. Every other path under `/v1` (for example `GET /v1/models`) is passed
through unchanged. Non-streaming is required; streamed bodies are forwarded as received.

### K-agent-headers@1 (provided) · who is calling
Sent by clients, read and logged by the proxy, **removed before forwarding**.

| Header | Required | Meaning | Logged as |
|---|---|---|---|
| `X-Agent-User` | recommended | The person or persona the traffic belongs to (`omar`, `tom-becker`) | `calls.user` |
| `X-Agent-Id` | optional | The agent program (`support-bot`). Defaults to the user. | `calls.agent` |
| `X-Session-Id` | optional | Conversation id. If absent, derived (below). | `calls.session` |
| `X-Agent-Dept` | optional | Department or team | `calls.dept` |
| `X-Agent-<Anything>` | optional | Free labels | `calls.labels` JSON, key = the part after `X-Agent-`, lower-cased (`X-Agent-Sim-Time` → `sim-time`) |
| `Authorization` | optional | The client's own key. Never forwarded. | `calls.key_id` = first 8 hex chars of SHA-256 of the bearer token |

Fallbacks, applied in this order:
- `user` = `X-Agent-User`, else `key:<key_id>` if the client sent a key, else `anonymous`.
- `agent` = `X-Agent-Id`, else `user`.
- `session` = `X-Session-Id`, else `auto-` + first 12 hex of SHA-256 of `agent + "\0" + JSON(first user message content)`
  (so every turn of one conversation gets the same id), else NULL for requests without messages.

Example:
```http
POST /v1/chat/completions
Authorization: Bearer dummy
X-Agent-User: omar
X-Agent-Dept: support
X-Agent-Id: support-bot
X-Session-Id: 4f1c2a9e7b10
X-Agent-Org: brightleaf
```

### K-log-schema@1 (provided) · `logs/proxy.db`
One SQLite file (path `PROXY_LOG_DB`, default `logs/proxy.db`), table `calls`, one row per call.
Consumers MUST tolerate extra columns and extra tables. Older files are upgraded in place by adding
missing columns.

| Column | Type | Meaning |
|---|---|---|
| `id` | INTEGER PK | insertion order |
| `ts` | TEXT | request start, UTC, `YYYY-MM-DDTHH:MM:SSZ` |
| `duration_ms` | INTEGER | until the answer was ready to send back |
| `user` | TEXT | K-agent-headers@1 user (never NULL for rows written by this proxy) |
| `agent` | TEXT | K-agent-headers@1 agent |
| `dept` | TEXT | nullable |
| `session` | TEXT | K-agent-headers@1 session |
| `key_id` | TEXT | 8 hex chars, nullable |
| `method`, `path` | TEXT | as received, e.g. `POST`, `/v1/chat/completions` |
| `status` | INTEGER | HTTP status returned to the client |
| `model` | TEXT | model the client asked for |
| `upstream_model` | TEXT | model that actually answered (differs after a fallback) |
| `finish_reason` | TEXT | of the first choice |
| `usage` | TEXT (JSON) | the provider's `usage` object |
| `prompt_tokens`, `completion_tokens`, `total_tokens` | INTEGER | copied from `usage`, nullable |
| `cost_usd` | REAL | paid-model cost when known, nullable |
| `route` | TEXT | gateway route: `primary`, `fallback`, `direct`, `cache`, `refused`, `passthrough`, NULL |
| `attempts` | INTEGER | upstream attempts the gateway made |
| `error` | TEXT (JSON) | provider or proxy error object, NULL on success |
| `request` | TEXT (JSON) | body as sent by the client, secrets redacted |
| `response` | TEXT (JSON) | body as returned to the client, secrets redacted |
| `labels` | TEXT (JSON) | other `X-Agent-*` headers, NULL if none |
| `firewall_level` | TEXT | always NULL here; filled by llm-proxy-firewall (K-log-schema@2) |

Indexes on `session`, `user`, `ts`.

### Proxy HTTP surface
| Route | Behaviour |
|---|---|
| `ANY /v1/...` | forwarded to `UPSTREAM_BASE_URL` + path, logged |
| `GET /healthz` | `{"ok": true, "logging": bool, "gateway": bool}`; not forwarded, not logged |
| `GET /v1/gateway/status` | gateway state: models, free requests left, spend, limiter load, cache size |

Environment: `OPENROUTER_API_KEY` (required), `UPSTREAM_BASE_URL` (default
`https://openrouter.ai/api/v1`), `PROXY_HOST`/`PROXY_PORT` (127.0.0.1:8080), `PROXY_LOGGING`
(on), `PROXY_LOG_DB` (logs/proxy.db), `PROXY_GATEWAY` (on), and the `GATEWAY_*` settings listed in
`proxy/gateway.py`.

### Dashboard HTTP surface (port `DASHBOARD_PORT`, default 8091)
| Route | Returns |
|---|---|
| `GET /` | the dashboard page |
| `GET /api/calls` | every call, ordered by `ts, id`, without `request`/`response`/`usage`; JSON columns decoded |
| `GET /api/session/<id>` | every call of one session, all columns, JSON decoded |

`python3 dashboard/server.py --demo` reads `demo/data/demo.db` instead of `PROXY_LOG_DB`.

### Demo data
- `demo/data/team-day.json`: list of `calls` rows (K-log-schema@1 columns, JSON columns decoded, no `id`).
- `demo/data/demo.db`: the same rows in a K-log-schema@1 file, sessions spread over the 7 days ending
  2026-10-30 (label `"redated": true`). This file is the fixture llm-session-console tests against.

### Contracts we depend on
| Contract | Owner | What we rely on |
|---|---|---|
| K-openai-chat@1 | external | request `model`, `messages`, `tools`; response `choices[0].message`, `finish_reason`, `usage` |

## 4. Requirements

### Proxy and log
| Id | Requirement | Acceptance check |
|---|---|---|
| R-001 | The proxy MUST forward every `/v1/...` request to the provider and return the provider's status and body unchanged. | `test_R001_*` |
| R-002 | The proxy MUST send the real key to the provider and never the client's key. | `test_R002_*` |
| R-003 | The proxy MUST remove `X-Agent-*` and `X-Session-Id` headers before forwarding. | `test_R003_*` |
| R-004 | With logging on, the proxy MUST write exactly one `calls` row per request, with every K-log-schema@1 column. | `test_R004_*` |
| R-005 | `user`, `dept`, `agent`, `session` MUST come from the K-agent-headers@1 headers. | `test_R005_*` |
| R-006 | Without `X-Agent-User`, `user` MUST be `key:<key_id>` or `anonymous`; without `X-Agent-Id`, `agent` MUST be the user. | `test_R006_*` |
| R-007 | Without `X-Session-Id`, every turn of one conversation MUST get the same derived `auto-…` session, and a new conversation a different one. | `test_R007_*` |
| R-008 | Every other `X-Agent-*` header MUST be stored in `labels` under its lower-cased suffix. | `test_R008_*` |
| R-009 | `prompt_tokens`, `completion_tokens`, `total_tokens` MUST be copied from the response's `usage`. | `test_R009_*` |
| R-010 | Provider errors MUST reach the client unchanged and be logged with `error`; an unreachable provider MUST give a JSON 502. | `test_R010_*` |
| R-011 | With `PROXY_LOGGING=off` the proxy MUST record nothing. | `test_R011_*` |
| R-012 | A failure to write the log MUST NOT change the reply. | `test_R012_*` |
| R-013 | The real key, the client key and any `Bearer <token>` text MUST NOT appear in the log. | `test_R013_*` |
| R-014 | Opening a log written by an older version MUST add the missing columns and keep the old rows. | `test_R014_*` |

### Gateway
| Id | Requirement | Acceptance check |
|---|---|---|
| R-020 | Free-model calls MUST wait for a slot in a sliding 60 s window (`GATEWAY_FREE_RPM`), giving up after `GATEWAY_MAX_WAIT_S`. | `test_R020_*` |
| R-021 | A per-minute 429 or a 502/503 MUST be retried on the same model with exponential backoff. | `test_R021_*` |
| R-022 | When the free daily cap is reached (429 per-day, or `GET /key` shows none left), calls MUST move to the fallback model for the rest of the UTC day. | `test_R022_*` |
| R-023 | Fallback calls MUST be refused with a 429 (`metadata.gateway = "spend_cap"`) once spend reaches `GATEWAY_SPEND_CAP_USD`. | `test_R023_*` |
| R-024 | Successful replies MUST be cached by request hash; `GATEWAY_CACHE=replay` serves hits, `strict` refuses misses with a 504. | `test_R024_*` |
| R-025 | `GET /v1/gateway/status` MUST report models, free budget, spend and cache, and calls MUST record their `route`. | `test_R025_*` |

### Dashboard
| Id | Requirement | Acceptance check |
|---|---|---|
| R-030 | `GET /api/calls` MUST list every call in time order without request/response bodies. | `test_R030_*` |
| R-031 | `GET /api/session/<id>` MUST return that session's calls with bodies decoded. | `test_R031_*` |
| R-032 | The dashboard MUST open the log read-only and show an empty list when there is no log. | `test_R032_*` |
| R-033 | `GET /` MUST serve one page with KPIs, a calls-per-day-by-user chart, a users table, a sessions list and a transcript panel, and nothing outside `dashboard/static/`. | `test_R033_*` |
| R-034 | Clicking a user filters every panel to that user; clicking a session shows its conversation turn by turn (user, tool calls, tool results, answers). | manual: demo/DEMO.md step 3–4 |

### Demo
| Id | Requirement | Acceptance check |
|---|---|---|
| R-040 | `python3 demo/run.py --offline` MUST run the demo team through the proxy with no API key (fake LLM), producing sessions with tool calls for several users. | `test_R040_*` |
| R-041 | `python3 demo/recording.py load` MUST load the recorded calls into a log once (re-running adds nothing) and `--redate-days N` MUST move whole sessions into the N days ending at `--anchor`, marking them `redated`. | `test_R041_*` |
| R-042 | `demo/data/demo.db` MUST follow K-log-schema@1, cover the four demo users, at least 12 sessions over at least 3 days, with no NULL user or session and no provider key. | `test_R042_*` |
| R-043 | The live generator MUST be able to space LLM calls (`--pace` seconds) to respect a shared rate limit. | `test_R043_*` |
| R-044 | `python3 demo/run.py --live` MUST run the same team against the real provider with `OPENROUTER_API_KEY`. | manual: demo/DEMO.md "Live traffic" |

## 5. Quality bars
| Id | Bar | Check |
|---|---|---|
| R-100 | The proxy and dashboard MUST run on the Python 3.10+ standard library alone. | `test_R100_*` |
| R-101 | The repo MUST be self-contained: nothing imported from outside its folder; only `openai` for the demo agents. | `test_R101_*` |
| R-102 | Logging adds well under 50 ms per call on a laptop (one SQLite insert under a lock). | manual: compare `duration_ms` with the fake LLM's fixed latency in an offline run |
| R-103 | The proxy listens on 127.0.0.1 by default; exposing it is an explicit choice (`PROXY_HOST`). | manual: `proxy/proxy.py` defaults |

## 6. Out of scope
- Content inspection, blocking, admin actions (llm-proxy-firewall).
- Drill-down console, per-user timelines, 3D views (llm-session-console).
- Authentication of clients; per-user quotas; multi-provider routing; log retention policies.
