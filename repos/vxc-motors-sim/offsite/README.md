# offsite/ · the VXC Motors all-staff off-site, held in a chat

All twelve employee agents plus a facilitator agent (Hannah Brooks) meet in one group chat for the annual
off-site. Victor, the General Manager, presents a business review built from the dealership's real data,
then everyone plays an icebreaker, brainstorms and votes, writes a story together and makes commitments.
Every message is one LLM call made **as that person**, through the logging proxy, with
`X-Agent-User` = staff id (K-agent-headers@1). Each agent's system prompt is its
[intrinsic context](../people/README.md): persona, soul, job and resume.

| | |
|---|---|
| Result | 85 messages from 13 agents in 52 minutes, all on GLM (free model was hanging), ~$0.07. Winning idea: Lucas's *First-Time Fix Promise*. Findings in [DECISIONS.md](DECISIONS.md#what-the-recorded-run-2026-10-30-2152-2244-utc-showed) |
| Recorded run | [`runs/2026-10-31/`](runs/2026-10-31/): `transcript.md` (read it), `transcript.jsonl`, `results.json`, `factsheet.json`, `meta.json`, `proxy.db` (the proxy's log of every call) |
| Replay | [`runs/2026-10-31/replay.html`](runs/2026-10-31/replay.html), open it in a browser (offline, animated); published at https://claude.ai/artifact/633ekHw6p5L5KiCf6KzMRD |
| Spec | [SPEC.md](SPEC.md) (R-OFF-ids) · [PROMPTS.md](PROMPTS.md) (rebuild prompts) · [DECISIONS.md](DECISIONS.md) |
| Tests | `python3 -m unittest tests.test_offsite_people` (offline, fake LLM) |

## Run it

```bash
pip install -r requirements.txt
# offline, canned answers, no key: checks the plumbing and builds a replay
python3 -m offsite.run --fake --out /tmp/offsite-fake && python3 -m offsite.replay /tmp/offsite-fake

# live: start the proxy (holds the real key, logs every call), then run the meeting
PROXY_LOGGING=on PROXY_LOG_DB=offsite/runs/mine/proxy.db GATEWAY_FREE_RPM=3 python3 proxy/proxy.py &
python3 -m offsite.run --out offsite/runs/mine          # ~95 calls, 3 per minute => about 35-60 minutes
python3 -m offsite.replay offsite/runs/mine
```

## Agenda

| Segment | What happens | Calls |
|---|---|---|
| Welcome | Hannah opens, Victor welcomes | 2 |
| Icebreaker | Two truths and a lie: each person guesses the previous person's lie, then posts their own (lie hidden); software scores | 15 |
| Business review | Victor: sales, aftersales and finance, outlook (from `factsheet.py`), then Q&A with 4 people Hannah picks | 12 |
| Brainstorm and vote | One idea each, 2 votes each (not your own), top 3, Victor backs or not | 28 |
| Lunch | scene line | 0 |
| Story game | "A customer's perfect day in 2027", one sentence each | 14 |
| Commitments | One commitment + one shout-out each, Victor and Hannah close | 15 |
