# Demo · llm-proxy-log

## Recorded (no key, 1 minute)
```bash
python3 dashboard/server.py --demo        # then open http://127.0.0.1:8091
```
What you should see: 125 calls, 48 sessions, 4 users over 7 days (2026-10-24 to 2026-10-30), about
115k tokens, $0.0075 of paid spend. The recording is a real run of the demo team against
`z-ai/glm-5.3-flash`; the sessions were spread over the week afterwards (label `redated: true`).

## Offline traffic (no key, fake LLM)
```bash
python3 demo/run.py --offline             # starts a fake LLM and the proxy, runs 16 sessions
python3 dashboard/server.py               # reads logs/proxy.db
python3 proxy/view_log.py                 # the same log in the terminal
```

## Live traffic (proves R-044)
```bash
export OPENROUTER_API_KEY=sk-or-...
python3 demo/run.py --live                # free model, one call every 15 s
python3 demo/run.py --live --pace 3 --model z-ai/glm-5.3-flash   # faster, costs well under a cent
```
Or run the proxy yourself and point any client at it:
```bash
python3 proxy/proxy.py &
curl -s http://127.0.0.1:8080/v1/chat/completions -H 'Content-Type: application/json' \
  -H 'X-Agent-User: me' -H 'X-Agent-Dept: research' \
  -d '{"model": "nvidia/nemotron-3.5-super-vl:free", "messages": [{"role": "user", "content": "Say hi"}]}'
```

## Five-minute walkthrough
1. Open the dashboard. The tiles at the top count calls, sessions, users and tokens (R-030).
2. "Calls per day, by user": one colour per person; hover a bar for the count (R-033).
3. Click **omar** in the Users table: every panel now shows only Omar's support-bot traffic. Click
   him again to clear the filter (R-034).
4. Click a session with 3+ calls, for example one starting "Lumen Dental wants a refund": the
   transcript shows Omar's message, the agent's `get_ticket` call, the tool result, the next call,
   and the answer, with latency and tokens per call (R-031, R-034).
5. In a terminal: `python3 proxy/view_log.py` lists the same sessions; `python3 proxy/view_log.py
   <session>` prints one conversation.
6. Run `python3 demo/run.py --offline --only 4`, then press **Reload** in the dashboard (pointed at
   `logs/proxy.db`): four new sessions appear for today.

## The demo cast
Brightleaf Software sells Leafdesk, a help-desk app for small shops. Everything they know is in
`demo/company.json`.

| Person | Dept | Agent | Tools | Typical task |
|---|---|---|---|---|
| Maya Chen | engineering | dev-assistant | `read_file`, `run_tests` | "The export test suite is failing. Run it and tell me why." |
| Omar Haddad | support | support-bot | `get_ticket`, `get_order`, `get_policy` | "Lumen Dental wants a refund in T-322. Are they eligible?" |
| Lena Novak | sales | sales-assistant | `get_lead`, `get_prices` | "Price the Business plan for 120 seats, monthly and annual." |
| Raj Patel | ops | ops-helper | `get_metrics`, `get_incident` | "Give me a status update on INC-19 for the team channel." |
