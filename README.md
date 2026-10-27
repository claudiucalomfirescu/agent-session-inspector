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
