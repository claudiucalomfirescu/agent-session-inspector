# agent-session-inspector

## LLM proxy research: steps 1-3

```
export OPENROUTER_API_KEY=...                       # only the proxy needs this when going through it

python3 agent/agent.py                              # step 1: agent -> OpenRouter directly

python3 proxy/proxy.py                              # step 2: pass-through proxy, no logging
PROXY_LOGGING=on python3 proxy/proxy.py             # step 3: same, recording to logs/proxy.db

LLM_BASE_URL=http://127.0.0.1:8080/v1 LLM_API_KEY=dummy python3 agent/agent.py   # agent via proxy

python3 proxy/view_log.py                           # list sessions
python3 proxy/view_log.py <session>                 # read one conversation turn by turn
```

Multi-turn example (order lookup -> customer -> shipping -> calculator, 5 LLM calls):

```
AGENT_ID=support-bot AGENT_GOAL="A customer asks what they will pay in total for order A-1001. Look up the order, then the customer (for their loyalty discount), then the shipping rate for their country. Apply the discount to the items subtotal, add shipping unless the discounted subtotal is above the free-shipping threshold, and use the calculator for the arithmetic. Reply to the customer by first name with a short breakdown." \
LLM_BASE_URL=http://127.0.0.1:8080/v1 LLM_API_KEY=dummy python3 agent/agent.py
```

## Session Inspector dashboard

Six visual boards over the proxy log, served by a small stdlib server next to the proxy and the agent:

```
python3 dashboard/seed_sample.py      # optional: load the recorded sample sessions into logs/proxy.db
python3 dashboard/server.py           # http://127.0.0.1:8090
```

The server reads `logs/proxy.db` read-only (override with `PROXY_LOG_DB`, port with `DASHBOARD_PORT`), so new
runs logged by the proxy (`PROXY_LOGGING=on`) show up on the next page load. No API key is needed to browse.

| Board | What it shows |
|---|---|
| A1 Chat thread | Each logged session as a conversation: system prompt, goal, tool calls, tool results, model reasoning, plus per-call facts and raw JSON |
| A2 Sequence | Every call as hops between Agent, Proxy, OpenRouter and Log DB, with the request, response and stored row for each hop |
| A3 Turn inspector | Sessions table, a token and latency strip per turn, and what was sent and received on the selected turn |
| B1 Topology | Steps 1 to 3 as an architecture map with a simulated turn, and each entity's config and key code |
| B2 Packet trace | One real logged turn walked through the code, line by line, with the values it carried |
| B3 Feature matrix | What each entity does in each step, and what changed from the step before |

The sample (`dashboard/sample/proxy-sample.json`) is eight calls logged through the proxy on 2026-10-27: the
five-turn support-bot session from the example above (`get_order` -> `get_customer` -> `get_shipping` ->
`calculator` -> answer), a two-turn clock-bot session, and one call the provider rejected (unknown model, HTTP 400).
`seed_sample.py` skips sessions already in the log, so running it twice is harmless.

The board pages in `dashboard/static/` are the canvas designs kept close to their original Design Component
markup; `dc-lite.js` is the small runtime that renders them (`{{holes}}`, `<sc-for>`, `<sc-if>`, `onClick`).
Board options can be set in the URL, e.g. `chat.html?showHops=false` or `sequence.html?showLogLane=false`.
