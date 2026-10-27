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
