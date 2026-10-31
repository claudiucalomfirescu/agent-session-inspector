# Demo · vxc-motors-sim

## Recorded (no key, 1 minute)
```bash
pip install -r requirements.txt
python3 demo/run_demo.py
```
What you should see: a summary line (tasks, LLM calls, emails, chats, firewall signals, blocked
sessions) and a URL. Open it for the **day timeline**: one lane per person, each task a bar, emails
and chats as arrows between people, firewall warnings and blocks as markers.

The recorded day (day 3, 2026-10-31 UTC, simulated Tue 27 Oct): 100 tasks, 506 LLM calls in 104 sessions,
54 emails, 62 team chats, 7 sessions blocked; $0.22 on `z-ai/glm-5.3-flash` (the free model was hanging,
D-014). Firewall vs the script: block precision 1.00, recall 1.00; flag precision 1.00, recall 1.00.

`demo/data/` is a complete run (K-vxc-run@1): `proxy.db` (every LLM call, K-log-schema@2),
`agents/<user>.jsonl` (each agent's own log), `runner.jsonl` (the director's timeline),
`systems/` (end-of-day Parquet of both databases), `summary.json`.

## Offline live run (no key, fake LLM)
```bash
python3 -m sim.fake_llm --port 9099 &
UPSTREAM_BASE_URL=http://127.0.0.1:9099/api/v1 OPENROUTER_API_KEY=sk-fake FIREWALL_INTENT=off \
GATEWAY_FREE_RPM=1000 VXC_RUN_DIR=/tmp/vxc-run python3 -m sim.run
```
The whole day scrolls past in about a minute: the scripted fake reads mail when a doorbell names
an email, reads chat when told about a chat message, and blocks are real (the firewall runs).

## Live traffic
```bash
export OPENROUTER_API_KEY=...
GATEWAY_FREE_RPM=8 python3 -m sim.run --max-calls 500      # add LLM_MODEL=z-ai/glm-5.3-flash if the free model hangs
python3 -m sim.export --demo && python3 demo/run_demo.py
```
Budget (R-101): the proxy paces calls to `GATEWAY_FREE_RPM` / `GATEWAY_PAID_RPM` per minute and stops
paid calls at `GATEWAY_SPEND_CAP_USD`; the director stops starting tasks at `--max-calls`.

## Five-minute walkthrough
1. `python3 -m sim.run --plan` — the day as data: 33 scripted events, six marked INC-1…INC-6 (R-026, R-027).
2. Open [TOOLS.md](../TOOLS.md) — 8 applications, 74 tools, and what is really behind each; note the
   ⚖ on `bmw_open_tech_case` (R-023).
3. Open the timeline (recorded step above), click **Hand the i4 walk-in to sales** (Maria, 09:35):
   Maria's agent calls `crm_assign_lead` and `chat_send` to Sofia. A few minutes later Sofia's task
   starts with a doorbell, "New team chat message CH-… from Maria", and her first tool call is
   `chat_unread` (R-005, R-006).
4. Follow Sofia's `mail_send` to Hannah Clarke: Hannah's agent (`customer-hannah-clarke`) is woken
   20 minutes later, reads with `mail_read`, answers with `mail_send` (R-003, R-007).
5. Click Aisha's **Start of day: EV jobs**. In this recording she checked recalls and bulletins and then
   *declined* to open a BMW technical case ("not on a vague HV warning with no fault codes"), so the
   judgment tool did not fire (D-019). To see it live: `python3 -m apps.server &` then
   `python3 -m agents.run_one aisha-rahman "Open a BMW technical support case for the iX ME73 GTN: HV warning, fault 21F0A3."`
   — the answer is written by `bmw-tech-support`, another agent, whose own call lands in the proxy log (R-021).
6. Click **Lending the BMW portal login** (Mark, INC-3): the follow-up asks to paste a password into
   chat; the proxy answers as if it were the LLM and the session ends blocked (R-008).
7. `sqlite3 demo/data/proxy.db "select json_extract(labels,'$.user'), json_extract(labels,'$.dept'), count(*) from calls group by 1,2"`
   — every call is attributed to a person and department (R-002).
8. `python3 -m sim.evaluate demo/data` — the firewall scored against the script's ground truth.

## The demo cast
| Agent (`X-Agent-User`) | Department | Does |
|---|---|---|
| victor-hale | Management | GM: approves stock orders and big discounts, answers BMW |
| maria-santos | Admin | reception: walk-ins, routes leads, bookings |
| priya-nair | Admin | finance: invoices, KPI summary |
| daniel-reed | Sales | sales manager: approves discounts ≤ 8 % |
| sofia-marin, tom-becker | Sales | consultants (Tom: INC-1, INC-5) |
| elena-popescu | Service | aftersales manager: goodwill ≤ 500 GBP, warranty |
| james-okafor, nina-kovac | Service | service advisors (James: INC-2, INC-6) |
| lucas-meyer, aisha-rahman | Workshop | technicians (chat only, no email) |
| mark-doyle | Parts | parts and BMW orders (INC-3) |
| customer-* | Customers | walk-ins, callers, emailers |
| bmw-retailer-support | BMW UK | answers dealer emails (also as the area manager) |
| bmw-tech-support | BMW UK | answers technical cases (judgment tool) |
