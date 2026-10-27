# agent-session-inspector

A learning project: from one agent calling an LLM to a simulated BMW dealership (**VXC Motors**)
whose agents are logged, inspected and firewalled by a proxy. Start with the
**[master plan](docs/MASTER_PLAN.md)**; each lesson has a page in [`docs/lessons/`](docs/lessons/)
and a visualization in [`viz/`](viz/).

## Shared LLM layer (use this for every agent)

```
pip install -r requirements.txt
export OPENROUTER_API_KEY=...                # only the proxy reads it
PROXY_LOGGING=on python3 proxy/proxy.py      # gateway on by default: rate limit, backoff,
                                             # glm-5.3-flash only after the free daily cap, $3 spend cap, cache
curl -s http://127.0.0.1:8080/v1/gateway/status
python3 -m unittest -v tests.test_gateway
```

```python
from llm import make_client, chat, start_proxy
start_proxy()                                            # no-op if already running
client, session = make_client("sales-anna", role="sales", department="sales")
resp = chat(client, [{"role": "user", "content": "hi"}])
```

See [lesson 3b](docs/lessons/03b-llm-gateway.md) for the rules and settings.

## LLM proxy research: steps 1-3

```
export OPENROUTER_API_KEY=...                       # only the proxy needs this when going through it

python3 agent/agent.py                              # step 1: agent -> OpenRouter directly

PROXY_GATEWAY=off python3 proxy/proxy.py            # step 2: pure pass-through proxy, no logging
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
