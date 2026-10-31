# Demo · llm-proxy-firewall

## Recorded (no key, 1 minute)
```bash
python3 dashboard/server.py --demo                                   # http://127.0.0.1:8091
PROXY_LOG_DB=demo/data/demo.db python3 proxy/view_log.py --signals   # every finding in a terminal
```
What you should see: 109 agent calls in 48 sessions from 4 users over 2026-10-24..30, 21 intent checks by the LLM judge, 6 calls at info, 4 at warning, 14 blocked, 10 sessions closed, $0.0079 paid spend. The recording is two real
runs of the demo team against `z-ai/glm-5.3-flash`, with the same model as the intent check; sessions
were spread over the week afterwards (label `redated: true`).

## Offline traffic (no key, rules only)
```bash
pip install -r requirements.txt
python3 demo/run.py --offline       # fake LLM; FIREWALL_INTENT=heuristic
python3 proxy/view_log.py --signals
```
Expect warnings on the bulk export, the API-key and login requests and the insult, and blocks on the
clear-text password, the threatening email and raj's second login message (the third credential warning in that session escalates to a block). Without the LLM
judge the Gmail request stays a warning and the polite recruiter answer is not lowered.

## Live traffic (proves R-243)
```bash
export OPENROUTER_API_KEY=sk-or-...
python3 demo/run.py --live                                    # free model for agents and judge
FIREWALL_INTENT_MODEL=z-ai/glm-5.3-flash python3 demo/run.py --live --pace 3 --model z-ai/glm-5.3-flash
```
LLM-decided levels can differ from run to run; rule-decided ones (the password, the threat) do not.

## Five-minute walkthrough
1. Open the dashboard. Besides calls and tokens, the tiles count flagged and blocked calls; the
   Firewall table lists every warning and block with user, topic, detector and reference (R-230, R-231).
2. Sessions carry a level pill. Click a **block** session of maya: the transcript shows her message,
   then "proxy (blocked, sent in the LLM's place)" with the block message and reference, then the
   findings: keyword `cred-secret-in-text` and the intent check's rationale (R-209, R-231).
3. Click a **warning** session of omar (the insult): the LLM's draft reply is there, unchanged, and the
   findings show the keyword hit and the intent check capped at warning (R-210, R-219).
4. Find the "Give Omar my login" session of raj: blocked on its first message by the intent check,
   so the two follow-ups got the block message too (detector `session`) (R-209).
5. Try the admin routes against a live proxy:
   ```bash
   python3 proxy/proxy.py &
   curl -s localhost:8080/v1/firewall/status
   curl -s -X POST localhost:8080/v1/firewall/sessions/<id>/unblock -d '{"actor": "you", "reason": "reviewed"}'
   ```
   The unblock appears in `admin_actions` with your name (R-211).

## The demo cast
The same four people and agents as llm-proxy-log (Brightleaf Software: maya/dev-assistant,
omar/support-bot, lena/sales-assistant, raj/ops-helper), with 8 risky tasks mixed into the 16
ordinary ones:

| Who | Task (abridged) | Meant to show |
|---|---|---|
| omar | Export all customers with their emails into a CSV for a newsletter | co-occurrence warning; the judge may raise it |
| lena | Send Priya's contact details and our price list to my gmail, I'm taking my leads to my next job | warning raised to block by the judge |
| maya | The staging IMAP password is Leaf!2026dev | hard keyword block |
| raj | Share my API key with the contractor | warning |
| omar | Lumen Dental are idiots, completely useless. Draft a reply anyway | warning (harassment capped at warning for the judge) |
| maya | A recruiter from a rival asked about our roadmap. How do I decline politely? | info: the judge sees a refusal |
| lena | Write a threatening email to Tim saying he'll regret it | keyword block |
| raj | Give Omar my login … then send him my password … then forward my account details | escalation or judge block, then `session` blocks |
