# Specification · vxc-motors-sim

> Source of truth. If a behaviour is not here, a rebuild may drop it.
> Version: 0.2 (2026-10-30) · Contracts provided: `K-vxc-tools@1`, `K-vxc-run@1` ·
> Contracts used: `K-openai-chat@1`, `K-agent-headers@1`, `K-log-schema@2`, `K-firewall-rules@1`

## 1. Glossary
| Term | Meaning |
|---|---|
| **Agent** | A program that holds an LLM conversation and acts only by asking the LLM which tool to call, then calling it. Every person in the simulation is an agent. |
| **Employee** | One of the 12 VXC Motors staff (`company/personas/<id>.md`). Played by a *staff agent*. Id = persona id, e.g. `tom-becker`. |
| **Outside party** | Someone not employed by VXC: a customer, BMW UK Retailer Support, BMW's area manager, BMW technical support. Also agents. |
| **Application (app)** | An enterprise system: CRM, DMS, Workshop, Parts, Finance, Mail, Chat (internal) and the BMW Partner Portal (external). |
| **Tool** | One operation of an application, exposed to agents in OpenAI tool format (e.g. `dms_set_deal_price`). |
| **Service** | The HTTP process hosting applications: `internal` (7 apps, one DuckDB file) and `bmw_portal` (one app, its own DuckDB file). |
| **Judgment tool** | A tool whose answer is written by another agent (an LLM) instead of a deterministic function. Today: `bmw_open_tech_case`. |
| **Actor** | Who calls a tool: a persona id, or `ext:<email>` for an outside party. |
| **Director** | The simulation process (`sim/run.py`): owns the clock and the day's script, starts agents, rings doorbells. Holds no business data. |
| **Doorbell** | The director's note to an agent: "new email MSG-… from X, subject …" or "new team chat message CH-… from X". Never contains the message body. |
| **Task** | One unit of work for one actor at a simulated time: scripted (`E01…`) or created by the day (`T001…`). One task = one LLM session. |
| **Incident** | A staged risky situation (`INC-1…INC-6`) with a ground-truth expectation for the firewall. |
| **Proxy** | The OpenAI-compatible logging, firewall and budget proxy every LLM call goes through (copy of `llm-proxy-firewall`). |

## 2. Components
| Id | Component | Responsibility | Inputs | Outputs |
|---|---|---|---|---|
| C-01 | Company (`company/`) | 12 personas: role, department, manager, email, which apps they may use, personality, risk profile; business rules | — | persona frontmatter |
| C-02 | Applications (`apps/`) | The 8 apps as tools over DuckDB, rules enforcement, audit of every call; seeded history Jan–Oct 2026 and the 07:45 morning of the day | tool calls | JSON results, audit rows |
| C-03 | Services (`apps/server.py`) | Serve the apps over HTTP (K-vxc-tools@1), the notification feed, the clock | HTTP | HTTP |
| C-04 | Staff agents (`agents/staff.py`) | One employee working one task: tool-calling loop through the proxy | goal, follow-ups | tool calls, a final answer |
| C-05 | Outside agents (`agents/external.py`) | Customers and BMW: `MailAgent` (mail tools only) and `Talker` (face to face / phone, no tools) | doorbell or prompt | emails, spoken words |
| C-06 | BMW technical support agent (`agents/bmw.py`) | Writes the answer of the judgment tool `bmw_open_tech_case` | case + BMW facts | answer text |
| C-07 | Director (`sim/run.py`, `sim/day.py`) | Clock, timeline of the day, task queue, worker pool, doorbells, IT admin actions, budget stop | day script, `/events` | `runner.jsonl`, `summary.json` |
| C-08 | Proxy (`proxy/`) | Log, firewall, gateway; holds the real key | agent HTTP | `proxy.db`, `gateway.db` |
| C-09 | LLM layer (`llm/`) | Client with identity headers; the agent's own log | — | `agents/<user>.jsonl` |
| C-10 | Export & evaluation (`sim/export.py`, `sim/evaluate.py`) | Snapshot a run (secrets scrubbed), bake the timeline page, score the firewall | run folder | `runs/<run-name>/`, `demo/data/`, `viz/workday.html` |
| C-11 | Fake LLM (`sim/fake_llm.py`) | Scripted upstream so the whole day runs offline | chat requests | chat responses |

## 3. Contracts

### K-vxc-tools@1 (provided)
Two HTTP services, JSON in and out, no authentication (local simulation).

| Service | Default URL (env) | Apps |
|---|---|---|
| internal | `http://127.0.0.1:8100` (`VXC_INTERNAL_URL`) | `crm`, `dms`, `workshop`, `parts`, `finance`, `mail`, `chat` |
| bmw_portal | `http://127.0.0.1:8200` (`VXC_PORTAL_URL`) | `bmw_portal` |

Routes (both services unless noted):

| Route | Request | Response |
|---|---|---|
| `GET /health` | — | `{"ok": true, "service": "internal"}` |
| `GET /apps` | — | `{"crm": {"name": "VXC CRM", "tools": ["crm_search_customers", …]}, …}` |
| `GET /tools?actor=<actor>` | — | list of OpenAI tool specs `{"type":"function","function":{"name","description","parameters"}}` the actor may use on this service; 404 for an unknown actor |
| `POST /call` | `{"actor": "tom-becker", "tool": "dms_get_deal", "args": {"deal_id": "D-00042"}}` | the tool's JSON result, or `{"error": "<why>"}` (refusals are errors the agent reads) |
| `POST /clock` | `{"now": "2026-10-27T09:10:00"}` | `{"now": …}`; sets simulated time for every later call |
| `GET /events?mail_after=N&chat_after=M` (internal) | — | `{"mail": [{"seq","msg_id","from","to","cc","subject","sent_at","to_customer"}], "chat": [{"seq","chat_id","from","to","sent_at"}]}`; **never a message body** |
| `GET /sim/customer?fuel=&pick=` (internal) | — | a real CRM customer with a car `{"customer_id","name","email","vin","car"}` (director only, not a tool) |

Actors: a persona id gets the tools of the apps in its persona's `systems` list; `ext:<email>` gets
exactly `mail_inbox`, `mail_read`, `mail_send` acting as that address. Every call, accepted or
refused, writes one audit row (`audit_log` internal, `portal_access_log` portal):
`occurred_at, actor, system, tool, args JSON, ok, result_summary`.

The full tool list (74 tools), parameters and **what is really behind each application** is the
generated [TOOLS.md](TOOLS.md), part of this contract. Summary:

| App | Tools | Behind it |
|---|---:|---|
| crm, dms, workshop, parts, finance | 55 | deterministic Python + SQL over `vxc.duckdb`; business rules enforced here (discount 3/8/GM %, goodwill 500 GBP, 3 stock orders/week, parts only against a job card, exports logged) |
| mail | 4 | real mailboxes (`messages` table); outside parties have mailboxes too |
| chat | 3 | real channel (`chat_messages`): `chat_send(to, message)`, `chat_unread()`, `chat_history(colleague)` |
| bmw_portal | 12 | separate service and database; orders advance with the clock; warranty decided by a fixed rule; **`bmw_open_tech_case` is answered by BMW's technical support agent** through the proxy |

Table shapes are in `apps/schema.py` (internal: 24 tables incl. `messages`, `chat_messages`,
`audit_log`; portal: 13 incl. `tech_cases`). Seed snapshots in `data/parquet/<db>/<table>.parquet`.

### K-vxc-run@1 (provided) — a recorded run
A run folder (`runs/<run-name>/`, and the shipped `demo/data/`) contains:

| File | Content |
|---|---|
| `proxy.db` | the proxy's SQLite log, K-log-schema@2 (calls, signals, admin_actions) |
| `gateway.db` | the gateway's answer cache (replay with `GATEWAY_CACHE=replay`) |
| `agents/<user>.jsonl` | each agent's own log: `session_start, request, response, tool, error, session_end` |
| `runner.jsonl` | director timeline, one JSON object per line: `{"ts","sim","event", task?, task_kind?, actor?, title?, incident?, …}`; events `day_start, task_start, session_start, tool, followup, blocked, task_end, mail, chat, inbound_mail, external_mail, customer_says, deferred, admin, stopped, day_end` |
| `summary.json` | `{"date","calls","minutes","stopped","tasks":[{"task","actor","title","sim","incident","session","status","calls","firewall"}],"not_started"}` |
| `systems/<db>/<table>.parquet` | end-of-day copy of both databases |

### Contracts we depend on
| Contract | Owner | What we rely on |
|---|---|---|
| `K-openai-chat@1` | external | `POST /v1/chat/completions` with `tools` / `tool_calls` |
| `K-agent-headers@1` | llm-proxy-log | We send `X-Agent-User` (persona id, `customer-<slug>`, `bmw-retailer-support`, `bmw-tech-support`), `X-Agent-Id` (= user), `X-Agent-Dept`, `X-Session-Id` (one per task), and labels `X-Agent-Role`, `-Org` (`vxc-motors` / `external` / `bmw`), `-Kind`, `-Task`, `-Sim-Time`, `-Title`, `-Incident` |
| `K-log-schema@2` | llm-proxy-firewall | `calls` (agent, session, labels, request, response, route, firewall_level), `signals`, `admin_actions`; admin endpoints `POST /v1/firewall/sessions/<id>/{note,block}` |
| `K-firewall-rules@1` | llm-proxy-firewall | our topic file `proxy/firewall_topics.yaml` (discount fraud, customer PII leak, credential sharing, competitor poaching, harassment, unsupported approval claims) |

## 4. Requirements

| Id | Requirement | Acceptance check |
|---|---|---|
| R-001 | `python -m sim.run` MUST run the scripted day from 08:00 to the last event and exit 0, starting the services and the proxy itself. | test `test_R001_day_runs_to_the_end` |
| R-002 | Every LLM request of every agent MUST carry `X-Agent-User` and `X-Agent-Dept` (K-agent-headers@1). | test `test_R002_every_agent_call_carries_identity_headers` |
| R-003 | Customers and BMW MUST be agents with their own identity (`customer-*`, `bmw-*`) going through the same proxy. | test `test_R003_outside_parties_are_agents_too` |
| R-004 | An email MUST only be sent by an agent executing a `mail_send` tool call that its LLM asked for, so the email text is in the proxy log. | test `test_R004_email_is_a_tool_call_seen_by_the_proxy` |
| R-005 | When mail arrives, the director MUST wake the recipient with a doorbell naming the message, and the recipient MUST read it with `mail_read`. | test `test_R005_recipient_reads_mail_by_tool_after_doorbell` |
| R-006 | Team chat MUST work the same way: `chat_send` stores, a doorbell wakes, `chat_unread` delivers. | test `test_R006_chat_is_a_tool_call_and_read_by_tool` |
| R-007 | An email to a customer or BMW address MUST wake that party's agent, which answers with `mail_send` (at most 2 answers per address per day). | test `test_R007_customer_and_bmw_answer_by_email` |
| R-008 | The staged incidents MUST be written so that the firewall blocks INC-1, INC-3 and INC-5 on scripted text alone. | test `test_R008_staged_incidents_hit_the_firewall` |
| R-009 | The repo MUST ship one recorded live day in `demo/data/` (K-vxc-run@1) and a page that shows it offline. | test `test_R009_demo_data_is_a_complete_run` |
| R-010 | Each service MUST list its applications at `GET /apps`. | test `test_R010_apps_listed_per_service` |
| R-011 | `GET /tools?actor=` MUST return only tools of the apps in the persona's `systems` list. | test `test_R011_tools_follow_persona_systems` |
| R-012 | An outside actor MUST get exactly the three mail tools; any other tool is refused. | test `test_R012_external_actor_has_only_mail` |
| R-013 | `chat_send` MUST store a message; `chat_unread` MUST return it once and mark it read. | test `test_R013_chat_is_stored_and_read_by_tool` |
| R-014 | `mail_send` MUST put the message in the recipient's mailbox (`mail_inbox`, `mail_read`). | test `test_R014_email_lands_in_recipient_mailbox` |
| R-015 | `GET /events` MUST report who sent what to whom and never the body. | test `test_R015_events_carry_no_message_text` |
| R-016 | `POST /clock` MUST set the time every later tool call sees. | test `test_R016_clock_is_set_by_the_director` |
| R-017 | `bmw_open_tech_case` MUST record a case; with the BMW agent off it is `queued`. | test `test_R017_tech_case_is_recorded_without_agent` |
| R-018 | Every tool call, including refusals, MUST be audited; a refusal MUST explain why. | test `test_R018_every_call_is_audited_and_refusals_explained` |
| R-019 | `dms_link_bmw_order` MUST create the on-order stock record (bug of days 1 and 2 fixed). | test `test_R019_link_bmw_order_creates_stock_record` |
| R-020 | The director MUST NOT read or write business data directly; only through the services' HTTP routes. | test `test_R020_director_never_touches_business_data` |
| R-021 | The tech-case answer MUST come from the BMW technical support agent through the proxy (`bmw-tech-support`, dept `BMW UK`). | test `test_R021_tech_case_answered_by_bmw_agent` |
| R-022 | No API key MUST appear in any log, run folder or demo data. | test `test_R022_no_key_in_logs`, `test_R022_demo_data_has_no_key` |
| R-023 | `TOOLS.md` MUST match the tool registry (regenerated by `python -m apps.catalogue`). | test `test_R023_tool_catalogue_is_current` |
| R-024 | Business rules MUST be enforced by the applications, not by prompts: discount limits 3 % / 8 % / GM, stock orders > 3 per week need the GM, parts only against a job card, mail privacy, logged exports. | tests `RulesTest` and `FlowTest` in tests/test_systems.py |
| R-025 | The seed MUST be deterministic: two builds give identical data. | test `test_R025_seed_reproducible` |
| R-026 | The day script MUST be data (`sim/day.py` EVENTS), and `--plan` MUST print it without any LLM call. | test `test_R026_plan_needs_no_llm` |
| R-027 | Every incident event MUST carry an `expect` ground truth, scored by `python -m sim.evaluate <run>`. | test `test_R027_incidents_have_ground_truth` |

## 5. Quality bars
| Id | Bar | Check |
|---|---|---|
| R-101 | A live day MUST stay under the budget: the director passes `GATEWAY_FREE_RPM` / `GATEWAY_PAID_RPM` (8/min for the recorded day) and `GATEWAY_SPEND_CAP_USD` (default 4) to the proxy, and stops starting tasks at `--max-calls`. | manual: DEMO.md "Live" step, `summary.json` calls and minutes |
| R-102 | The whole offline day (fake LLM) MUST finish in under 5 minutes on a laptop. | test `test_R102_offline_day_is_fast` |
| R-103 | Customer data in the seed MUST be fictional (`*.example` domains, generated names). | manual: `data/parquet/internal/customers.parquet` |

## 6. Out of scope
- Authentication between agents and services (actors name themselves).
- Real email or chat delivery outside the simulation.
- The proxy's own behaviour (owned by llm-proxy-firewall; we ship a copy).
- A console: use llm-session-console on `demo/data/proxy.db`.
