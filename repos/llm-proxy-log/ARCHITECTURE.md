# Architecture · llm-proxy-log

## Component diagram
```mermaid
flowchart LR
  subgraph agents[Agents: any OpenAI-compatible client]
    A1[support-bot<br/>X-Agent-User: omar]
    A2[dev-assistant<br/>X-Agent-User: maya]
  end
  A1 & A2 -- "POST /v1/chat/completions<br/>dummy key + identity headers" --> P
  subgraph proxy[proxy/proxy.py :8080]
    P[Handler<br/>identity() · strip headers · swap key] --> G[gateway.py<br/>rate limit · retry · fallback<br/>spend cap · cache]
    P --> L[logstore.py<br/>one row per call]
  end
  G -- "real key" --> U[(Provider<br/>OpenRouter or any<br/>OpenAI-compatible API)]
  L --> DB[(logs/proxy.db<br/>K-log-schema@1)]
  G --> GDB[(logs/gateway.db<br/>cache + spend ledger)]
  DB -- read-only --> D[dashboard/server.py :8091]
  DB -- read-only --> C[llm-session-console<br/>separate repo]
```

One request, step by step:
1. The agent's SDK posts to `http://127.0.0.1:8080/v1/chat/completions` with a dummy key and the
   identity headers (`client/` sets them for you).
2. `Handler._forward` reads the body, drops hop-by-hop and identity headers, puts the real key in
   `Authorization`.
3. Chat completions go through `Gateway.chat` (wait for a rate slot, send, retry 429/5xx, move to the
   fallback model on the daily cap, refuse at the spend cap, cache the answer). Other paths go
   straight to `_upstream`.
4. `identity()` resolves user, agent, session, key_id, labels (K-agent-headers@1 fallbacks).
5. `log_call()` redacts secrets and inserts one row through `LogStore.insert`, which never raises.
6. The provider's status, headers and body go back to the agent unchanged.

## Runtime
| Process | Command | Port / file | Env |
|---|---|---|---|
| proxy | `python3 proxy/proxy.py` | :8080, writes `logs/proxy.db`, `logs/gateway.db` | `OPENROUTER_API_KEY`, `UPSTREAM_BASE_URL`, `PROXY_*`, `GATEWAY_*` |
| dashboard | `python3 dashboard/server.py [--demo]` | :8091, reads `logs/proxy.db` or `demo/data/demo.db` | `PROXY_LOG_DB`, `DASHBOARD_*` |
| fake LLM (offline) | started by `demo/run.py --offline` | :8099 | `FAKE_LLM_*` |
| demo team | `python3 demo/team.py` or `demo/run.py` | client of :8080 | `LLM_BASE_URL`, `LLM_MODEL` |

## Data model
`calls` as specified in SPEC.md §3 (K-log-schema@1). The gateway keeps its own file
(`logs/gateway.db`: `cache(key, ts, model, response)`, `spend(ts, model, tokens, cost_usd)`), which is
an implementation detail, not a contract.

## Requirement → code map
| R-id | Where |
|---|---|
| R-001, R-010 | `proxy/proxy.py: Handler._forward, _upstream` |
| R-002, R-003 | `proxy/proxy.py: SKIP_REQUEST, Handler._forward` (header filter) |
| R-004, R-009, R-013 | `proxy/proxy.py: log_call, _redact` |
| R-005…R-008 | `proxy/proxy.py: identity` |
| R-011 | `proxy/proxy.py: LOGGING` |
| R-012 | `proxy/logstore.py: LogStore.insert` (catches everything) |
| R-014 | `proxy/logstore.py: open_db` (ALTER TABLE for missing columns) |
| R-020…R-024 | `proxy/gateway.py: RateLimiter, Gateway.chat, _classify, _record_cost` |
| R-025 | `proxy/gateway.py: Gateway.status`; `proxy/proxy.py` route |
| R-030…R-032 | `dashboard/server.py: load_calls, load_session, query` |
| R-033, R-034 | `dashboard/static/index.html` |
| R-040 | `demo/run.py`, `demo/fake_llm.py`, `demo/team.py` |
| R-041 | `demo/recording.py: load` |
| R-042 | `demo/data/demo.db` (built by `recording.py load --redate-days 7 --anchor 2026-10-30`) |
| R-043 | `demo/team.py: Pacer` |

## Extension points
- **Another provider:** set `UPSTREAM_BASE_URL` and the key; set `PROXY_GATEWAY=off` if its rate
  limits differ from OpenRouter's (or tune `GATEWAY_*`).
- **More identity:** add any `X-Agent-<Name>` header; it lands in `labels` with no code change. A
  label that deserves its own column goes into K-log-schema@2+ (a new contract version).
- **Your own agents:** use `client.make_client(agent, user=..., dept=...)`, or just send the
  headers from any language.
- **Your own demo company:** edit `demo/company.json` (data), `demo/agents.py` (tools, personas) and
  `demo/scenarios.json` (tasks).
- **A richer view:** read `logs/proxy.db` from your own tool; SPEC.md is the contract.
