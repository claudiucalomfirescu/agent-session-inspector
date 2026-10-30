# Rebuild prompts · vxc-motors-sim

These prompts rebuild this repository from an empty folder. They are written for a capable coding
model; they say *what* and cite the spec, and say *how* only where the how is a contract.

How they were made: the system grew over several sessions in the parent learning project
(lessons 4–9: company and personas, mock systems, multi-agent workday, firewall) and was then
extracted and reworked into this repo on 2026-10-30 (agents vs tools, HTTP services, chat app,
doorbells, judgment tool). The step prompts below are that history condensed into the order a
rebuild should follow, rewritten against SPEC.md v0.2.

**Always give the model first:** `prax.yaml`, `GOAL.md`, `SPEC.md`, `TOOLS.md`, and for later steps
the files it already produced. For P-02 also give it `company/` (the personas are data, not code)
and `data/parquet/` if you want byte-identical history.

## P-REBUILD — one shot
```text
You are rebuilding the system described in GOAL.md, SPEC.md and TOOLS.md (attached), whose current
shape is in ARCHITECTURE.md. Target language/runtime: <LANGUAGE>. Implement every requirement
R-xxx in SPEC.md and the contracts exactly: K-vxc-tools@1 (HTTP routes, actor rules, audit rows,
the 74 tools with the parameter names in TOOLS.md), K-vxc-run@1 (run folder layout and
runner.jsonl events), and send K-agent-headers@1 on every LLM call. Keep the company data
(company/personas/*.md) and the day script (sim/day.py EVENTS: times, actors, goals, follow-ups,
incidents, expect) as data, unchanged. Agents must act only through tool calls their LLM asked for;
messages between agents only through the mail and chat applications; the director must never touch
business data. Include a scripted fake LLM so the whole day runs offline. Port the tests in tests/
keeping their R-ids. Keep demo/data/ readable by the new code. Finish with the README quickstart
working offline. Report which R-ids you could not satisfy and why.
```

## P-VERIFY
```text
Run the acceptance tests and the walkthrough in demo/DEMO.md against the rebuild. Produce a table
of every R-id in SPEC.md with pass/fail/manual and the evidence (test name or command output).
Then run one live day with `python -m sim.run --max-calls 150` at 8 requests/min and compare its
summary.json and firewall signals with demo/data (same incidents blocked? emails and chats present?).
Do not change SPEC.md to make a test pass.
```

## Step-by-step prompts

### P-01 · LLM layer and proxy
- **Goal:** agents can call an OpenAI-compatible endpoint with identity headers; a proxy logs and polices it.
- **Delivers:** R-002, R-022
- **Read first:** GOAL.md, SPEC.md §3 "Contracts we depend on"
- **Done when:** `python3 -m unittest tests.test_gateway tests.test_firewall`

```text
Copy the proxy from the sibling repo llm-proxy-firewall into proxy/ (it is a dependency we vendor,
not something we design here) and replace its topic file with ours (proxy/firewall_topics.yaml).
Write llm/: make_client(agent_id, session_id=None, user=None, dept=None, **labels) returning an
OpenAI client pointed at LLM_BASE_URL (default http://127.0.0.1:8080/v1, dummy key) that sends
X-Agent-User, X-Agent-Id, X-Session-Id, X-Agent-Dept and X-Agent-<Label> for every extra label;
chat(client, messages, tools=None, log=None) with a small retry on 429/5xx; start_proxy() that
starts proxy/proxy.py if nothing answers; AgentLog writing the agent's own JSONL log
(session_start, request (new messages only), response (with the X-Firewall header parsed),
tool, error, session_end). Never put the real key anywhere but the proxy's environment.
```

### P-02 · The company and its data
- **Goal:** 12 personas and a deterministic seeded history in two DuckDB databases.
- **Delivers:** R-025, R-103
- **Read first:** SPEC.md §2 C-01, C-02; ARCHITECTURE.md "Data model"; company/README.md
- **Done when:** `python3 -m unittest tests.test_systems.SeedTest`

```text
Keep company/personas/*.md as given (YAML frontmatter is the source of truth). Write apps/schema.py
with the internal and portal schemas from ARCHITECTURE.md, apps/catalog.py (BMW models, parts,
recalls, bulletins), apps/seed.py that generates January–October 2026 of dealership history with a
fixed random seed and writes data/vxc.duckdb, data/bmw_portal.duckdb and Parquet snapshots, and
apps/scenario_today.py that adds the open work each person finds on Tuesday 27 October 2026 at
07:45 (overnight web leads, a discount approval for Daniel, a stock-order approval for Victor, a
sold car arrived for Sofia, an iX with a high-voltage warning for Aisha, ...). Two builds must give
identical data. All emails *.example, all names generated.
```

### P-03 · The applications as tools
- **Goal:** the 74 tools of TOOLS.md with their business rules, audit and actor model.
- **Delivers:** R-018, R-019, R-023, R-024
- **Read first:** SPEC.md §3 K-vxc-tools@1, TOOLS.md, company/README.md "Business rules"
- **Done when:** `python3 -m unittest tests.test_systems` and `python -m apps.catalogue` leaves TOOLS.md unchanged

```text
Implement apps/common.py: a @tool(app, description, writes=False, prepare=None, **Param) registry
that produces OpenAI tool specs; call(actor, tool, args) that checks the actor may use the app
(persona `systems`, or ext:<email> with only mail_inbox/mail_read/mail_send), validates arguments,
runs the tool in a transaction, and writes one audit row for every call including refusals;
a refusal is a ToolError whose message the agent reads. Then implement every tool of TOOLS.md in
apps/crm.py, dms.py, workshop.py, parts.py, finance.py, mail.py, chat.py and bmw_portal/, enforcing
the rules in the applications (apps/rules.py), never in prompts. Write apps/catalogue.py that
regenerates TOOLS.md from the registry, including the "what is really behind it" column.
```

### P-04 · The applications as services
- **Goal:** agents reach the applications only over HTTP; the director gets a notification feed and owns the clock.
- **Delivers:** R-010, R-011, R-012, R-013, R-014, R-015, R-016
- **Read first:** SPEC.md §3 routes table
- **Done when:** `python3 -m unittest tests.test_services`

```text
Write apps/server.py serving the internal apps on VXC_INTERNAL_URL's port (8100) and the BMW portal
on VXC_PORTAL_URL's port (8200), both in one process (`python -m apps.server`), seeding on first
start. Routes exactly as SPEC.md §3: /health, /apps, /tools?actor=, POST /call, POST /clock,
GET /events (who wrote to whom, sequence numbers, never the body), GET /sim/customer. Write
agents/toolclient.py: ToolClient(actor) fetches its specs from both services and routes each call
to the service that hosts the tool; wait_ready().
```

### P-05 · Agents
- **Goal:** employees, customers and BMW as agents with clear prompts; a judgment tool backed by an agent.
- **Delivers:** R-003, R-017, R-021
- **Read first:** SPEC.md §1, §2 C-04…C-06
- **Done when:** `python3 -m unittest tests.test_services` (R-017) and P-06's test (R-003, R-021)

```text
Write agents/prompts.py (staff prompt from the persona: who you are, responsibilities, the company
rules, "you are an AI agent acting for this person, you act only through your tools; email = mail_send,
team chat = chat_send; when told a message arrived, read it with mail_read / chat_unread first";
customer prompts; BMW retailer desk; BMW technical support engineer). agents/staff.py: StaffAgent
running the tool-calling loop (max 8 model calls per user turn, scripted follow-ups or a live
respond() callback, stops when the proxy blocks the session). agents/external.py: MailAgent (only
the three mail tools, acting as ext:<email>) and Talker (no tools, for face-to-face and phone).
agents/bmw.py: tech_support_answer() — one LLM call as user bmw-tech-support, dept "BMW UK" — used
as the `prepare` step of bmw_open_tech_case so it runs before the portal's database lock.
VXC_BMW_AGENT=off skips it (case queued).
```

### P-06 · The director and the day
- **Goal:** one command runs the whole workday; agents only learn about each other through doorbells.
- **Delivers:** R-001, R-004, R-005, R-006, R-007, R-008, R-020, R-026, R-027, R-101, R-102
- **Read first:** SPEC.md §3 K-vxc-run@1, sim/day.py (data, keep it)
- **Done when:** `python3 -m unittest tests.test_workday_offline tests.test_docs`

```text
Write sim/run.py: starts the services (separate process) and the proxy, sets the clock through
POST /clock, turns sim/day.py EVENTS into time-ordered tasks for a small worker pool (one task per
person at a time; the clock never runs more than 25 simulated minutes ahead of the oldest running
task). Task kinds: staff, customer (Talker conversation of `rounds` exchanges, or a MailAgent that
writes an email), inbound (a scripted outside email sent through the mail service as ext:<from>),
reply (an outside party's MailAgent answering), admin (IT admin notes and one manual block through
the proxy's admin routes). A Watcher polls GET /events every second and after every task: a new
email or chat wakes the recipient 6 simulated minutes after it was sent with a doorbell that names
the message but not its body; mail to a customer or BMW wakes that party's agent 20 minutes later
(max 2 answers per address); chains stop after 3 hops (deferred notes join the person's next task).
Write runner.jsonl and summary.json (K-vxc-run@1). Never import the database layer. Also write
sim/fake_llm.py, a scripted upstream that makes the whole day run offline (mail_read on a doorbell
naming MSG-…, chat_unread on a chat doorbell, chat_send when the goal says "team chat", mail_send
when asked to write an email, bmw_open_tech_case when asked for a technical support case).
```

### P-07 · Record, export, evaluate
- **Goal:** a recorded live day ships in demo/data and can be viewed and scored offline.
- **Delivers:** R-009, R-022
- **Read first:** SPEC.md §3 K-vxc-run@1, demo/DEMO.md
- **Done when:** `python3 -m unittest tests.test_docs` with no skips; `python demo/run_demo.py` opens the day

```text
Write sim/export.py: snapshot a finished run (proxy.db and gateway.db with any key scrubbed,
agents/*.jsonl, runner.jsonl, summary.json, Parquet copies of both databases) into runs/<name>/
or, with --demo, into demo/data/; assert no file contains a key; bake the data into
viz/workday.html from viz/workday_template.html (tasks, sessions, emails and chats with their
bodies read from the mail/chat Parquet, firewall signals, admin actions, stats). Write
sim/evaluate.py scoring the firewall against each event's `expect`. Write demo/run_demo.py that
rebuilds the page from demo/data and serves it.
```

### P-08 · Show it
- **Goal:** README, DEMO walkthrough and an animated explainer a newcomer understands in five minutes.
- **Delivers:** (story layer, no R-ids)
- **Read first:** GOAL.md, ARCHITECTURE.md, ../prax-systems/templates/EXPLAINER_GUIDE.md
- **Done when:** `python3 tools/prax_check.py . --level silver`

```text
Write explainers/index.html: one self-contained file (inline SVG/CSS/JS, no network) that animates,
with play/pause/step controls and prefers-reduced-motion respected, in light and dark: (1) what it
is: a dealership of 12 agents, 8 applications as tools, one proxy; (2) the problem: you cannot see
what company agents do; (3) how it works: an email from Maria to Sofia as a tool call, the doorbell,
mail_read, the reply, a chat incident blocked by the firewall, the BMW tech case answered by
another agent; (4) try it: the offline and live commands. Publish it and link it from README and
prax.yaml.
```
