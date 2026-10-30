# Specification · llm-proxy-firewall

> Source of truth. If a behaviour is not here, a rebuild may drop it.
> Version: 1.0 · Contracts provided: K-log-schema@2, K-firewall-rules@1 · Contracts used: K-openai-chat@1, K-agent-headers@1, K-log-schema@1
>
> This repo is a standalone copy of llm-proxy-log plus a firewall. Sections 1–4 up to "Demo" repeat
> llm-proxy-log's spec (same R-ids, same tests); the firewall adds §3 K-log-schema@2, K-firewall-rules@1,
> the admin routes, and requirements R-2xx.

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
| Firewall | The part of the proxy that reads every chat completion in both directions and decides a level. |
| Topic | A kind of policy breach (customer data leak, credential sharing…) defined in the topics file. |
| Rule | A regex test inside a topic: `any:` (keyword) or `all:` (co-occurrence, "intent heuristic"). |
| Signal | One finding: session, turn, direction, level, topic, detector, what matched. One row in `signals`. |
| Level | `info` (noted), `warning` (noted, forwarded, header), `block` (not forwarded; proxy answers). |
| Intent check | An LLM classifier asked whenever a rule fired at warning/block (and on any request-side finding); reads topic and the author's stance. |
| Blocked session | A session the firewall (or an admin) closed; every later request in it gets the block message. |
| Admin action | `block_session`, `unblock_session`, `replace_response` or `note`, by the firewall or a person. |

## 2. Components
| Id | Component | Responsibility | Inputs | Outputs |
|---|---|---|---|---|
| C-01 | proxy (`proxy/proxy.py`) | Forward every request to the provider with the real key; record it | HTTP from agents | HTTP to provider; rows in `calls` |
| C-02 | log store (`proxy/logstore.py`) | Create/upgrade the SQLite file; write rows without ever raising | rows | `logs/proxy.db` |
| C-03 | gateway (`proxy/gateway.py`) | Rate limit, retry, fall back, cap spend, cache replies for chat completions | chat requests | provider calls; `logs/gateway.db` |
| C-04 | dashboard (`dashboard/`) | Read the log read-only; show KPIs, calls per day per user, users, sessions, a transcript | `logs/proxy.db` | web page + JSON API on :8091 |
| C-05 | client helper (`client/`) | Make an OpenAI SDK client that sends the identity headers | agent name, user, dept | headers on every call |
| C-06 | demo (`demo/`) | A four-agent team with tools over a made-up company, including 8 risky tasks; offline fake LLM; recorded data | scenarios | traffic; `demo/data/` |
| C-07 | firewall (`proxy/firewall.py`) | Inspect requests and responses; decide a level; answer blocked sessions itself; record signals and admin actions | chat requests/responses, topics file | decisions; rows in `signals`, `admin_actions` |
| C-08 | topics file (`proxy/firewall_topics.yaml`) | The policy: topics, rules, levels, block message (K-firewall-rules@1) | — | loaded at start |

## 3. Contracts

### K-openai-chat@1 (used)
`POST /v1/chat/completions` with the OpenAI request/response shape, including `tools`,
`tool_calls` and `usage`. Every other path under `/v1` (for example `GET /v1/models`) is passed
through unchanged. Non-streaming is required; streamed bodies are forwarded as received.

### K-agent-headers@1 (owned by llm-proxy-log, repeated here) · who is calling
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

### K-log-schema@1 (owned by llm-proxy-log, repeated here) · `logs/proxy.db`
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
| `firewall_level` | TEXT | K-log-schema@2: highest level of this call's signals, NULL if none |

Indexes on `session`, `user`, `ts`.

### K-log-schema@2 (provided) = K-log-schema@1 + firewall tables
Readers detect @2 by the presence of the `signals` table.

`calls.firewall_level` TEXT: `info` | `warning` | `block` | NULL. For a blocked call `route` is
`firewall` (request side: never forwarded) or `firewall-response` (the LLM's answer was withheld).

`signals`, one row per finding:
| Column | Type | Meaning |
|---|---|---|
| `id` | INTEGER PK | |
| `ts` | TEXT | UTC, `YYYY-MM-DDTHH:MM:SSZ` |
| `session`, `user`, `agent` | TEXT | K-agent-headers@1 values of the call |
| `call_id` | INTEGER | `calls.id` of the call it was found in (NULL only if that row failed to write) |
| `turn` | INTEGER | 1 + number of assistant messages in the request |
| `direction` | TEXT | `request` (what the agent sent) or `response` (what the LLM answered) |
| `level` | TEXT | `info`, `warning`, `block` |
| `topic` | TEXT | topic id from the topics file, or `manual` |
| `detector` | TEXT | `keyword`, `intent_heuristic`, `intent_llm`, `grounding`, `escalation`, `session` |
| `rule` | TEXT | rule id, or `llm-classifier`, `llm-<stance>`, `warnings-to-block`, `session-blocked` |
| `matched` | TEXT | what the regexes matched, nullable |
| `rationale` | TEXT | why (LLM rationale, "lowered from warning …"), nullable |
| `confidence` | REAL | LLM confidence 0..1, nullable |
| `excerpt` | TEXT | up to ~200 chars around the match |
| `ref` | TEXT | `FW-XXXXXXXX` block reference on block rows |

`admin_actions`, one row per action:
| Column | Type | Meaning |
|---|---|---|
| `id` | INTEGER PK | |
| `ts` | TEXT | UTC |
| `actor` | TEXT | `firewall` or the administrator's name |
| `action` | TEXT | `block_session`, `unblock_session`, `replace_response`, `note` |
| `session`, `user`, `agent`, `topic` | TEXT | |
| `reason` | TEXT | e.g. `keyword:cred-secret-in-text; intent_llm:llm-classifier`, or the admin's words |
| `ref` | TEXT | block reference |
| `call_id` | INTEGER | the call that triggered it, nullable for manual actions |

The firewall's own classifier calls are logged in `calls` with user and agent `firewall` and session
`firewall-intent`, labels `{"role": "intent-classifier", "tier": "free"|"paid"}`.

### K-firewall-rules@1 (provided) · the topics file
YAML, path `FIREWALL_TOPICS` (default `proxy/firewall_topics.yaml`):
```yaml
organization: <one line naming the organisation, used in the classifier prompt>
warnings_to_block: 3          # warnings on one topic in one session -> block
block_message: "... {title} ... {policy} ... {ref}"
grounding: {...}              # optional: approval-claim check (R-217)
topics:
  <topic_id>:
    title: Credential sharing
    policy: <one sentence shown in the block message>
    intent: <one paragraph for the LLM classifier>
    llm_max_level: block      # optional cap on what the LLM alone may give this topic
    rules:
      - id: <rule id>
        level: info | warning | block
        any: [<regex>, ...]   # keyword: fires if any matches
        # or
        all: [<regex>, ...]   # intent_heuristic: fires only if every one matches
        hard: true            # optional: the LLM may never lower it
```
Regexes are Python syntax, case-insensitive, dot matches newline.

### Firewall HTTP surface (on the proxy)
| Route | Behaviour |
|---|---|
| `GET /v1/firewall/status` | intent mode, topics, blocked sessions, counters |
| `POST /v1/firewall/sessions/<id>/block` | body `{"actor": "...", "reason": "..."}`; closes the session (topic `manual`) |
| `POST /v1/firewall/sessions/<id>/unblock` | reopens it and clears its warning counts |
| `POST /v1/firewall/sessions/<id>/note` | records a note |

With `FIREWALL_ADMIN_TOKEN` set, these need header `X-Admin-Token`. Other settings: `FIREWALL`
(on|off), `FIREWALL_TOPICS`, `FIREWALL_INTENT` (auto|llm|heuristic|off), `FIREWALL_INTENT_MODEL`,
`FIREWALL_INTENT_MIN_FREE`, `FIREWALL_EXEMPT_AGENTS`, `FIREWALL_DISCLOSE` (adds `X-Firewall:
warning` or `X-Firewall: block; topic=…; ref=…` to replies).

A blocked reply is an ordinary chat completion (status 200, `finish_reason: "stop"`, the requested
`model`, zero usage) whose text is the topics file's `block_message`; for `stream: true` it is sent
as server-sent events ending in `data: [DONE]`.

### Dashboard additions
`GET /api/signals` and `GET /api/actions` return those tables in id order; the page shows firewall
levels on sessions and calls, a "flagged/blocked" KPI, a firewall findings table, and the findings of
the open session.

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
- `demo/data/team-week.json`: `{"calls": [...], "signals": [...], "admin_actions": [...]}`; calls keep their original `id`, the other rows point at it with `call_id`.
- `demo/data/demo.db`: the same rows in a K-log-schema@2 file, sessions spread over the 7 days ending
  2026-10-30 (label `"redated": true`). This file is the fixture llm-session-console tests against.

### Contracts we depend on
| Contract | Owner | What we rely on |
|---|---|---|
| K-openai-chat@1 | external | request `model`, `messages`, `tools`, `stream`; response `choices[0].message`, `finish_reason`, `usage` |
| K-agent-headers@1 | llm-proxy-log | the headers and fallbacks above, unchanged |
| K-log-schema@1 | llm-proxy-log | the `calls` table above; @2 only adds |

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
| R-022 | When the free daily cap is reached (429 per-day, or `GET /key` shows none left), calls MUST move to the fallback model for the rest of the UTC day. A free-model call that times out (`GATEWAY_FREE_TIMEOUT_S`, default 90) or answers 504 MUST go to the fallback model at once, without retries. | `test_R022_*` |
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
| R-041 | `python3 demo/recording.py load` MUST load the recorded calls into a log once (re-running adds nothing) and `--redate-days N` MUST move whole sessions into the N days ending at `--anchor`, marking them `redated`. Firewall intent checks (session `firewall-intent`) move with the agent session they judged. | `test_R041_*` |
| R-042 | `demo/data/demo.db` MUST follow K-log-schema@1, cover the four demo users, at least 12 sessions over at least 3 days, with no NULL user or session and no provider key. | `test_R042_*` |
| R-043 | The live generator MUST be able to space LLM calls (`--pace` seconds) to respect a shared rate limit. | `test_R043_*` |
| R-044 | `python3 demo/run.py --live` MUST run the same team against the real provider with `OPENROUTER_API_KEY`. | manual: demo/DEMO.md "Live traffic" |

### Firewall
| Id | Requirement | Acceptance check |
|---|---|---|
| R-201 | Each topic's rules MUST give the expected level on the crafted messages (none, info, warning, block for every topic). | `test_R201_*` |
| R-202 | The firewall MUST inspect only what is new in a request (user and tool messages after the last assistant message), never the system prompt or earlier turns. | `test_R202_*` |
| R-203 | Tool results MUST be inspected like user messages. | `test_R203_*` |
| R-204 | `warnings_to_block` warnings on one topic in one session MUST block the session (detector `escalation`). | `test_R204_*` |
| R-205 | When a rule fires at warning or block (or on any request-side finding), the LLM intent check MUST be asked; it can raise the level; verdicts are cached by text; its prompt names the organisation from the topics file. | `test_R205_*` |
| R-206 | The LLM MAY lower co-occurrence findings it is confident are harmless and findings in text whose author refuses or reports, down to info; it MUST NOT lower request-side keyword findings or `hard` rules. | `test_R206_*` |
| R-207 | `FIREWALL_INTENT=heuristic` (or off) MUST skip the LLM entirely. | `test_R207_*` |
| R-208 | Blocked sessions MUST stay blocked across a proxy restart (rebuilt from `admin_actions`) until unblocked. | `test_R208_*` |
| R-209 | On block, the request MUST NOT reach the provider; the agent MUST get an ordinary chat completion with the block message and reference; every later request of that session MUST get the same treatment. | `test_R209_*` |
| R-210 | Info and warning findings MUST be forwarded as normal; a warning MUST add `X-Firewall: warning`; `calls.firewall_level` MUST hold the call's highest level. | `test_R210_*` |
| R-211 | The admin routes MUST block, unblock and note sessions, recording who and why; with `FIREWALL_ADMIN_TOKEN` set they MUST require it. | `test_R211_*` |
| R-212 | A block found in the LLM's answer (text or tool-call arguments) MUST replace the answer with the block message and record `replace_response`. | `test_R212_*` |
| R-213 | `signals` and `admin_actions` rows MUST carry the call's user and agent. | `test_R213_*` |
| R-214 | A blocked streaming request MUST get the block message as server-sent events. | `test_R214_*` |
| R-215 | The intent check MUST go through the gateway and be logged as user/agent `firewall`, session `firewall-intent`. | `test_R215_*` |
| R-216 | Agents in `FIREWALL_EXEMPT_AGENTS` MUST NOT be inspected (and need the admin token when one is set). | `test_R216_*` |
| R-217 | The grounding layer (approval claims checked against tool results) MUST run only when the topics file has a `grounding:` section. | `test_R217_*` |
| R-218 | The topics file MUST be replaceable (`FIREWALL_TOPICS`) without code changes. | `test_R218_*` |
| R-219 | A topic's `llm_max_level` MUST cap the level the LLM check alone can give it; rules still decide above it. | `test_R219_*` |
| R-230 | The dashboard MUST serve `/api/signals` and `/api/actions`. | `test_R230_*` |
| R-231 | The dashboard MUST show firewall levels on sessions and calls, flagged/blocked counts, the findings table, and the findings of an open session. | manual: demo/DEMO.md steps 3–5 |
| R-242 | `demo/data/demo.db` MUST follow K-log-schema@2 with info, warning and block signals, at least 3 blocked sessions, a user on every signal, and every signal pointing at a call of its session. | `test_R242_*` |
| R-243 | `python3 demo/run.py --live` MUST produce real firewall decisions from the LLM intent check on the risky scenarios. | manual: demo/DEMO.md "Live traffic" |

## 5. Quality bars
| Id | Bar | Check |
|---|---|---|
| R-100 | The proxy and dashboard MUST run on the Python 3.10+ standard library plus PyYAML (for the topics file). | `test_R100_*` |
| R-101 | The repo MUST be self-contained: nothing imported from outside its folder; only `openai` for the demo agents. | `test_R101_*` |
| R-102 | Logging adds well under 50 ms per call on a laptop (one SQLite insert under a lock). | manual: compare `duration_ms` with the fake LLM's fixed latency in an offline run |
| R-103 | The proxy listens on 127.0.0.1 by default; exposing it is an explicit choice (`PROXY_HOST`). | manual: `proxy/proxy.py` defaults |

## 6. Out of scope
- A policy for your organisation: the shipped topics file is the demo company's. Write your own.
- Guarantees: regexes and an LLM classifier miss paraphrases and misread intent. The firewall is a
  tripwire with an audit trail, not a data-loss-prevention product.
- Drill-down console, per-user timelines, 3D views (llm-session-console).
- Authentication of clients; per-user quotas; multi-provider routing; log retention policies.
