# Specification · llm-session-console

> Source of truth. If a behaviour is not here, a rebuild may drop it.
> Version: 0.1 · 2026-10-30 · Contracts provided: `K-console-api@1` · Contracts used:
> `K-log-schema@1`, `K-log-schema@2`, `K-agent-headers@1`

## 1. Glossary
| Term | Meaning |
|---|---|
| log | A SQLite file written by an LLM proxy: table `calls`, optionally `signals` and `admin_actions`. |
| call | One HTTP request through the proxy (one row of `calls`): the conversation so far in, one LLM answer out. |
| user | Who the traffic belongs to (§3.3). The unit the console drills into. |
| dept | The user's department / team, if the client said so. |
| session | A conversation: the calls sharing one `session` value (`X-Session-Id`). |
| step | One call inside a session, shown as *only the messages it added* plus the LLM's answer. |
| finding | A row of `signals`: the firewall noticed something (`info`, `warning`, `block`) on a call. |
| admin action | A row of `admin_actions`: an automatic block, a replaced response, or a person's block / unblock / note. |
| system traffic | Calls made by infrastructure, not users: by default agents named `firewall` or starting `console-`. |
| bucket | The time unit of a chart: `day`, `week` (starting Monday) or `hour`. |
| drill-down | Moving from a wider view to a narrower one by clicking: all → user → day → session → call. |
| galaxy | The 3D view: users as stars, sessions as planets, calls as moons. |

## 2. Components
| Id | Component | Responsibility | Inputs | Outputs |
|---|---|---|---|---|
| C-01 | store | Open a log read-only, detect its schema, keep a light in-memory index of calls, answer every aggregate | log file | Python dicts |
| C-02 | transcript | Turn a session's calls into steps (new messages only), attach findings and actions | rows of one session | session JSON |
| C-03 | server | Serve the UI and the JSON API (`K-console-api@1`) on localhost, several logs at once, refresh when a log changes | CLI flags, logs | HTTP |
| C-04 | drill-down UI | Hash-routed single page: global, user, session, firewall, search views; charts in plain SVG | API | browser |
| C-05 | galaxy UI | Three.js scene of users → sessions → calls with click-to-drill | API | browser (WebGL) |
| C-06 | demo data | Recorded logs, xz-compressed, unpacked on first run; a live-replay script | recorded logs | `demo/data/` |

## 3. Contracts

### Contracts we depend on
| Contract | Owner | What we rely on |
|---|---|---|
| `K-log-schema@1` | llm-proxy-log | Table `calls` with at least `id` (integer, increasing) and `ts` (`YYYY-MM-DDTHH:MM:SSZ`, UTC). Every other column is optional and used when present: `user, agent, dept, session, key_id, status, model, upstream_model, finish_reason, duration_ms, usage (JSON with prompt_tokens / completion_tokens / total_tokens / cost), prompt_tokens, completion_tokens, total_tokens, cost_usd, error, request (OpenAI chat request JSON), response (OpenAI chat response JSON or SSE text), labels (JSON object), route, attempts`. Extra columns and tables are ignored. |
| `K-log-schema@2` | llm-proxy-firewall | @1 plus `calls.firewall_level` and tables `signals(id, ts, session, user?, agent, call_id, turn, direction, level, topic, detector, rule, matched, rationale, confidence, excerpt, ref)` and `admin_actions(id, ts, actor, action, session, user?, agent, topic, reason, ref, call_id)`. The firewall layer is shown **iff** `signals` exists. |
| `K-agent-headers@1` | llm-proxy-log | `X-Agent-User` → `calls.user` (proxy falls back to `key:` + 8 hex of SHA-256 of the bearer key, then `anonymous`); `X-Agent-Id` → `agent`; `X-Session-Id` → `session`; `X-Agent-Dept` → `dept`; other `X-Agent-*` → `labels`. |
| `K-openai-chat@1` | external | Shapes of `request.messages[]` (roles system / user / assistant / tool, `tool_calls`, `tool_call_id`), `request.tools[]`, `response.choices[0].message`, `response.usage`. |

### 3.3 Identity rules (how a call gets its user and dept)
- user = first non-empty of: `calls.user`, `labels.user`, `"key:" + calls.key_id`, `calls.agent`, `"anonymous"`.
- dept = first non-empty of: `calls.dept`, `labels.dept`, `labels.department`, `"(none)"`.
- session = `calls.session`, or `<user>@<YYYY-MM-DD>` when empty (one session per user per day).
- The UI states which source the users came from: `X-Agent-User`, `API key` or `X-Agent-Id`.

### K-console-api@1 (provided)
Local HTTP, JSON, GET only. Every endpoint accepts `db=<log-name>` (default: the first log) and the shared
filters `from=YYYY-MM-DD`, `to=YYYY-MM-DD` (inclusive, UTC days), `user=`, `dept=`, `system=0|1`
(default 0: system traffic excluded) and, where charts are returned, `bucket=day|week|hour`.

| Route | Returns |
|---|---|
| `/api/dbs` | `{dbs: [meta…]}` |
| `/api/meta` | `{name, path, has_firewall, has_signals, has_actions, identity, first, last, calls, system_calls, users, depts[]}` |
| `/api/overview` | `{totals, series[], users[], depts[], heatmap[], models[]}`; `totals = {calls, sessions, users, tokens, prompt_tokens, completion_tokens, cost, errors, days, first, last, avg_ms, firewall: {info, warning, block}, blocked_calls}`; `series[] = {bucket, calls, sessions, users, tokens, prompt_tokens, completion_tokens, errors, cost, blocked, info, warning, block}` |
| `/api/users` | `[{user, dept, agents, calls, sessions, active_days, tokens, cost, errors, first_seen, last_seen, max_level, firewall, blocked, is_system, by_day: {day: calls}}]` |
| `/api/user/<user>` | `{user, totals, series, heatmap, models, sessions[], tools: [{tool, calls}]}`, 404 if unknown |
| `/api/sessions?level=` | `[{session, user, dept, started, ended, calls, tokens, cost, errors, max_level, firewall, blocked, title}]` |
| `/api/session/<id>` | `{session, user, dept, agent, labels, started, ended, system_prompt, tools[], steps[], loose_signals[], loose_actions[], totals}`; `steps[] = {call_id, ts, status, model, upstream_model, duration_ms, finish_reason, prompt_tokens, completion_tokens, total_tokens, firewall_level, input: [messages added by this call], output: assistant message, error, signals[], actions[]}` |
| `/api/call/<id>` | the raw row with `request`, `response`, `usage`, `labels` parsed, plus `signals[]` |
| `/api/firewall?level=&topic=` | `{enabled, events[], topics: [{topic, level, n, users}], detectors[], actions[]}`; `{enabled: false, …}` for @1 logs |
| `/api/galaxy` | `{users: [{user, dept, calls, sessions, tokens, max_level, is_system}], sessions: [{session, user, dept, calls, tokens, max_level, started, title}]}` |
| `/api/search?q=` | up to 100 `[{id, ts, user, session, fw, snippet}]`, newest first, case-insensitive substring of request or response |

Errors: unknown route or db → 404 `{error}`; exception → 500 `{error}`.

UI routes (hash): `#/`, `#/u/<user>`, `#/s/<session>?call=<id>`, `#/fw?level=&topic=`, `#/galaxy`,
`#/search?q=`, all carrying the shared filters so every view is a shareable link.

### CLI
`python3 -m console [--db PATH]… [--port 8095] [--host 127.0.0.1]`. Env: `CONSOLE_PORT`,
`CONSOLE_SYSTEM_AGENTS` (comma list; an entry ending in `-` is a prefix; default `firewall,console-`).
Without `--db`, every `demo/data/*.db.xz` is unpacked to `demo/data/.cache/` and served.

## 4. Requirements
| Id | Requirement | Acceptance check |
|---|---|---|
| R-001 | The console MUST open logs read-only and never change the file, nor hold a read transaction that blocks the proxy's writes. | test `test_R001_never_writes_to_the_log`, `test_R016_live_append_visible_without_restart` |
| R-002 | It MUST read legacy (no `user` column), @1 and @2 logs, show the firewall layer only when `signals` exists, and refuse a file with no `calls` table. | test `test_R002_*` |
| R-003 | Users MUST be resolved by the identity rules of §3.3, and the UI MUST say which source was used. | test `test_R003_user_identity_order` |
| R-004 | Departments MUST be resolved by §3.3. | test `test_R004_department` |
| R-005 | Totals (calls, sessions, users, tokens, cost, errors, latency, firewall counts, blocked calls) MUST honour the date, user, dept and system filters. | test `test_R005_totals_honour_filters` |
| R-006 | Time series MUST be available by day, week (Monday start) and hour, with empty days inside the range filled with zeros. | test `test_R006_series_buckets_and_zero_fill` |
| R-007 | The users table MUST give per user: dept, calls, sessions, active days, tokens, last seen, firewall counts by level, worst level, calls per day. | test `test_R007_users_table` |
| R-008 | The user view MUST give the user's totals, series, weekday × hour heatmap, the tools the LLM called for them, and their sessions. | test `test_R008_user_detail` |
| R-009 | Session lists MUST show start, title (labels.title or first user message), calls, tokens, length, worst firewall level, and filter by minimum level. | test `test_R009_sessions_list` |
| R-010 | A session MUST read as a conversation: each call shows only the messages it added and the LLM's answer (text and tool calls); findings and admin actions appear on their call; those without a call appear at session level. | test `test_R010_*` |
| R-011 | Any call's raw request and response MUST be viewable. | test `test_R011_raw_call` |
| R-012 | The firewall view MUST list findings (filter by level and topic), a topic × level matrix, counts by detector, findings over time and all admin actions; each row opens the session at that call. | test `test_R012_firewall_view` |
| R-013 | The galaxy endpoint MUST return compact user and session nodes; messages load only when a session is opened. | test `test_R013_galaxy_nodes` |
| R-014 | Search MUST find calls whose request or response contains a text, with a snippet. | test `test_R014_search` |
| R-015 | System traffic MUST be excluded by default and included on request. | test `test_R015_system_traffic_hidden_by_default` |
| R-016 | Rows the proxy appends while the console runs MUST appear on the next request without a restart. | test `test_R016_live_rows_appear_after_refresh`, `test_R016_live_append_visible_without_restart` |
| R-017 | Calls without a session id MUST be grouped into one session per user per day. | test `test_R017_sessions_without_id_group_per_user_and_day` |
| R-018 | `python3 -m console` with no arguments MUST serve the bundled demo logs, offline, with no dependency outside the Python standard library (Three.js is vendored). | test `test_R018_bundled_demo_logs_unpack_and_load` |
| R-019 | The server MUST bind 127.0.0.1 by default and refuse paths outside `web/`. | test `test_R019_static_files_and_no_traversal` |
| R-020 | Several logs MUST be servable at once and selected with `db=`; an unknown name is a 404. | test `test_R020_several_logs_selected_by_db` |
| R-021 | Drill-down UI: global → user → day → session → call, each level reachable by one click (chart bar, table row), with a breadcrumb and removable filter chips; every view is a URL. | manual: demo/DEMO.md steps 1–6; endpoints by test `test_R005_R021_every_view_endpoint_answers` |
| R-022 | Galaxy UI: drag to rotate, scroll to zoom; click a star (user) to fly to it, a planet (session) to show its calls as moons, a moon to read that call; each panel links into the drill-down; Esc returns to the overview. | manual: demo/DEMO.md step 8 |
| R-023 | On a log without firewall tables the UI MUST hide firewall numbers and say why on the firewall page. | manual: demo/DEMO.md step 9; API by test `test_R012_firewall_view` |
| R-024 | Charts MUST let the reader switch metric (calls, sessions, tokens, users, firewall) and bucket (day / week), and clicking a bar MUST narrow the date range to that bucket. | manual: demo/DEMO.md steps 2–3 |

## 5. Quality bars
| Id | Bar | Check |
|---|---|---|
| R-101 | The bundled 4-week log (~4,400 calls, ~160 MB unpacked) loads in under 5 s and each endpoint answers in under 1.5 s on a laptop. | test `test_R018_bundled_demo_logs_unpack_and_load` |
| R-102 | No outbound network at runtime; the UI loads nothing from a CDN. | manual: run with the network off (DEMO step 10) |
| R-103 | Streamed (SSE) responses stored by a proxy MUST be reassembled into one message. | test `test_R103_streamed_responses` |
| R-104 | The UI works in light and dark and respects `prefers-reduced-motion` (galaxy stops spinning). | manual: DEMO step 10 |

## 6. Out of scope
- Writing to the log, firewall administration, alerts and notifications.
- Authentication, remote hosting, multi-user access control.
- LLM summaries of sessions (the old console had them; they needed the network and the firewall exemption).
- Cost estimation for models that do not report cost in `usage`.
