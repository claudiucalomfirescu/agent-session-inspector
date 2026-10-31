# Rebuild prompts · llm-proxy-log

These prompts rebuild this repository from an empty folder. They are written for a capable coding
model: they say *what* and cite the spec, and say *how* only where the how is a contract (headers,
schema, routes, file formats).

**Always give the model first:** `prax.yaml`, `GOAL.md`, `SPEC.md`, and for later steps the files it
already produced. Give it `tests/` too: they are black-box (HTTP in, HTTP and SQLite out) and are the
definition of done.

How these were made: the code was first built step by step in the agent-session-inspector learning
project (lessons 2–3: pass-through proxy, logging; lesson 3b: gateway; a dashboard thread), then
extracted and generalised on 2026-10-30 with the prompts below as the record of each step.

## P-REBUILD — one shot
```text
You are rebuilding the system described in GOAL.md and SPEC.md (attached), whose current shape is in
ARCHITECTURE.md. Target language/runtime: <LANGUAGE>. Implement every requirement R-xxx in SPEC.md
and every contract exactly as specified: K-agent-headers@1 (header names, fallbacks for user, agent
and session, key_id = first 8 hex of SHA-256 of the client's bearer token), K-log-schema@1 (table
`calls`, every column, types, timestamp format), the proxy routes (/v1/..., /healthz,
/v1/gateway/status), the dashboard routes (/, /api/calls, /api/session/<id>, --demo). Those are not
negotiable; internal structure is yours. The proxy and dashboard must need nothing beyond the
language's standard library plus SQLite. Port the acceptance tests in tests/ to <LANGUAGE> keeping
their R-ids (test names contain R0xx); they start the proxy and dashboard as processes and talk HTTP.
Keep demo/data/ byte-compatible: the new dashboard must open demo/data/demo.db unchanged. Rebuild the
offline fake LLM and the four-agent demo team (demo/company.json, demo/scenarios.json are data: copy
them). Finish with a README quickstart that works offline from demo/data/. Report which R-ids you
could not satisfy and why.
```

## P-VERIFY
```text
Run the acceptance tests and the walkthrough in demo/DEMO.md against the rebuild. Produce a table of
every R-id in SPEC.md with pass / fail / manual and the evidence (test name and output, or what you
saw on screen). Then load demo/data/demo.db in the rebuilt dashboard and in llm-session-console (if
available) and confirm both show 4 users, 48 sessions, 125 calls. Do not change SPEC.md to make a
test pass.
```

## Step-by-step prompts

### P-01 · Pass-through proxy
- **Goal:** an HTTP server that forwards everything under /v1 to the provider with the real key.
- **Delivers:** R-001, R-002, R-003, R-010, R-103
- **Read first:** GOAL.md, SPEC.md §3 (K-openai-chat@1, proxy HTTP surface)
- **Done when:** `python3 -m unittest tests.test_proxy -k R001 -k R002 -k R003 -k R010`

```text
Create proxy/proxy.py: a threaded HTTP server (standard library only) listening on PROXY_HOST:PROXY_PORT
(default 127.0.0.1:8080). Every request under /v1/... is forwarded to UPSTREAM_BASE_URL + the rest of the
path with the same method and body. Replace the client's Authorization with "Bearer $OPENROUTER_API_KEY".
Drop hop-by-hop headers (Host, Connection, Content-Length, Transfer-Encoding, Accept-Encoding) and every
X-Agent-* and X-Session-Id header. Return the provider's status, headers (minus hop-by-hop) and body
unchanged, including error statuses. If the provider cannot be reached, answer 502 with
{"error": {"code": 502, "message": "proxy could not reach provider: <ExceptionName>"}}. Add GET /healthz
answering {"ok": true, ...} without forwarding. Exit with a clear message if OPENROUTER_API_KEY is unset.
```

### P-02 · SQLite log of every call
- **Goal:** one row per call in logs/proxy.db with the K-log-schema@1 columns.
- **Delivers:** R-004, R-009, R-011, R-012, R-013, R-014
- **Read first:** SPEC.md §3 K-log-schema@1
- **Done when:** `python3 -m unittest tests.test_proxy`

```text
Create proxy/logstore.py with open_db(path) (create the file and table `calls` exactly as in SPEC.md
K-log-schema@1, add any missing column to an existing older file with ALTER TABLE, create indexes on
session, user, ts) and a LogStore class whose insert(table, row_dict) is guarded by a lock and never
raises (print a one-line error to stderr and return None). In proxy.py, when PROXY_LOGGING is on (the
default), after each request write one row: ts (request start, UTC, YYYY-MM-DDTHH:MM:SSZ), duration_ms,
method, path, status, model from the request body, finish_reason of the first choice, usage JSON and
the three token counts copied from it, error (the provider's error object, or {code, message} for a
non-JSON error), request and response bodies as text. Before storing, replace the real key with
[REDACTED] and any "Bearer <8+ token chars>" with "Bearer [REDACTED]". A logging failure must never
change the reply.
```

### P-03 · Who is calling
- **Goal:** user, dept, agent, session, key_id and labels resolved per K-agent-headers@1.
- **Delivers:** R-005, R-006, R-007, R-008
- **Read first:** SPEC.md §3 K-agent-headers@1
- **Done when:** `python3 -m unittest tests.test_proxy -k R005 -k R006 -k R007 -k R008`

```text
Add identity(headers, request_json) to proxy.py and store its result in the row. user = X-Agent-User,
else "key:" + key_id when the client sent a bearer token, else "anonymous". key_id = first 8 hex chars of
sha256(token). agent = X-Agent-Id, else user. dept = X-Agent-Dept. session = X-Session-Id, else
"auto-" + first 12 hex of sha256(agent + "\0" + json.dumps(first user message content, sort_keys=True)),
so all turns of one conversation share it. Every other X-Agent-<Name> header goes into labels as
{"<name lower-cased>": value}; labels is NULL when there are none. Never store the token itself.
```

### P-04 · Gateway: budget and traffic rules
- **Goal:** chat completions pass a rate limiter, retry, fallback, spend cap and cache.
- **Delivers:** R-020, R-021, R-022, R-023, R-024, R-025
- **Read first:** SPEC.md R-020…R-025, the GATEWAY_* settings
- **Done when:** `python3 -m unittest tests.test_gateway tests.test_proxy -k R025`

```text
Create proxy/gateway.py with a Gateway(upstream, key, Config) used by the proxy for POST
/chat/completions when PROXY_GATEWAY is on (default). Rules: (1) models ending ":free" take a slot in a
sliding 60 s window of GATEWAY_FREE_RPM (default 16) requests, paid models in GATEWAY_PAID_RPM; wait up to
GATEWAY_MAX_WAIT_S for a slot, else answer 429 with error.metadata.gateway = "rate_limit". (2) A 429
that is not a daily cap, or a 502/503, is retried on the same model up to GATEWAY_RETRIES times with
exponential backoff from GATEWAY_BACKOFF_S, honouring Retry-After. (3) A 429 mentioning a per-day / daily
limit, or GET {upstream}/key showing free_model_daily_requests.remaining <= GATEWAY_FREE_RESERVE, moves
free-model calls to GATEWAY_FALLBACK_MODEL until the next UTC midnight; a request with reasoning
{"enabled": false} is sent to the fallback with {"effort": "low"} instead. (4) Paid spend is tracked in
a ledger (usage.cost, else tokens x GATEWAY_PRICE_IN/OUT) and compared with the key's own usage; at
GATEWAY_SPEND_CAP_USD paid calls get 429 metadata.gateway = "spend_cap". (5) Successful answers are
cached by sha256 of the request JSON minus user/stream fields; GATEWAY_CACHE = off | record | replay |
strict (strict: miss = 504 metadata.gateway = "cache_miss"). Return meta {route, upstream_model,
attempts, cost_usd} and log those columns. Add GET /v1/gateway/status.
```

### P-05 · Small dashboard
- **Goal:** one page that answers "who used the LLM, when, how much, and what was said".
- **Delivers:** R-030, R-031, R-032, R-033, R-034
- **Read first:** SPEC.md dashboard HTTP surface, R-030…R-034
- **Done when:** `python3 -m unittest tests.test_dashboard`, then demo/DEMO.md steps 2–4 by eye

```text
Create dashboard/server.py (standard library) serving dashboard/static/index.html at / and JSON at
/api/calls (every call ordered by ts, id, without request/response/usage, JSON columns decoded, NULL for
columns an older file lacks) and /api/session/<id> (all columns, decoded). Open SQLite read-only
(file:...?mode=ro); a missing file or table gives []. Refuse paths outside static/. --demo reads
demo/data/demo.db. The page (vanilla JS + inline SVG, no CDN, light and dark): KPI tiles (calls,
sessions, users, tokens, errors, average latency, paid spend), a stacked bar chart of calls per day per
user with a legend, a users table (dept, sessions, calls, tokens) that filters everything when clicked,
a sessions list (start, user, agent, calls, tokens), and a transcript panel that rebuilds the
conversation from the session's calls: new user/tool messages of each request, then the assistant's
answer and tool calls, with per-call time, latency, model, route and tokens. If /api/signals exists,
also show firewall levels and findings (llm-proxy-firewall serves it).
```

### P-06 · Demo team, offline fake LLM, recorded data
- **Goal:** a clone shows real-looking traffic with no key, and a key produces fresh traffic.
- **Delivers:** R-040, R-041, R-042, R-043, R-044
- **Read first:** SPEC.md demo data, GOAL.md success criteria 1 and 3
- **Done when:** `python3 -m unittest tests.test_demo`, `python3 dashboard/server.py --demo`

```text
Create a made-up company in demo/company.json (Brightleaf Software: people maya/engineering,
omar/support, lena/sales, raj/ops; orders, tickets, policies, leads, prices, repo files, test results,
metrics, incidents). demo/agents.py: four agents (dev-assistant, support-bot, sales-assistant,
ops-helper), each working for one person, each with 2-3 OpenAI function tools that only read
company.json and always return JSON. demo/scenarios.json: 16 tasks, some with follow-up messages.
demo/team.py runs each scenario as one session through the proxy using client/ (OpenAI SDK with the
identity headers), executing tool calls until the agent answers (max 4 LLM calls per message), with
--pace seconds between LLM calls. demo/fake_llm.py: an OpenAI-compatible offline server that calls the
tool whose name/description best matches the user's words (filling parameters with id-like tokens from
the message), then answers by quoting the tool result; usage = chars/4. demo/run.py --offline starts the
fake LLM and the proxy and runs the team; --live uses OPENROUTER_API_KEY with --pace 15 by default.
demo/recording.py: export a log to JSON, load JSON files into a log (skip sessions already present;
--redate-days N --anchor DAY moves whole sessions to random days, seeded, label redated=true). Record
one real run, export it to demo/data/team-day.json and build demo/data/demo.db with
--redate-days 7 --anchor 2026-10-30.
```

### P-07 · Prax documents and explainer
- **Goal:** the repo passes Prax Systems Silver.
- **Delivers:** R-100, R-101 (and the documents themselves)
- **Read first:** ../prax-systems/METHOD.md, templates/, EXPLAINER_GUIDE.md
- **Done when:** `python3 tools/prax_check.py . --level silver`

```text
Write README (60-second offline quickstart first), GOAL, SPEC (this file's structure: glossary,
components, contracts with exact shapes, R-ids with acceptance checks), ARCHITECTURE (Mermaid, runtime
table, R-id -> code map), ROADMAP, DECISIONS (every autonomous decision, flagged for review),
demo/DEMO.md (walkthrough that proves the manual R-ids) and explainers/index.html: one self-contained
animated page (no network, light/dark, reduced motion, keyboard) with scenes What, The problem, How it
works (one real call from demo/data travelling agent -> proxy -> provider -> log -> dashboard), What you
get, Replicate it. Add a test that no file imports anything from outside the repo.
```
