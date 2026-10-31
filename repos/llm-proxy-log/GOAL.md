# Goal · llm-proxy-log

## Pitch
Put one small proxy between your AI agents and the LLM, and you get a complete, searchable record of
who asked what, what came back, how long it took and what it cost, without changing a line of agent
code beyond its base URL.

## The problem
Teams now run several AI agents (a support bot, a coding assistant, a sales helper), each calling an
LLM API with a shared key. Nobody can answer simple questions afterwards: which person's agent made
these calls, what exactly was sent, which conversation burned the tokens, why did yesterday's run
fail? Provider dashboards show totals per key, not conversations per person. Adding logging to every
agent is repetitive, easy to forget, and puts the provider key in every agent's environment.

## Who it is for
- Primary: a developer or small team running a few LLM agents who wants to see and keep their traffic.
- Secondary: someone learning how agents talk to LLMs (tool calls, turns, tokens) by watching real
  traffic; builders of tools that read the log (for example llm-session-console).

## Success looks like
1. A fresh clone shows a dashboard of a recorded day of a four-person demo team in under a minute,
   with no API key (`python3 dashboard/server.py --demo`).
2. Pointing any OpenAI-compatible client at the proxy (base URL only) logs every call, with the user,
   department, agent and session it belongs to, in one SQLite file.
3. The provider key lives only in the proxy; it never appears in agents, in the log or in the demo data.
4. Another program can read the log without asking us: the schema and identity headers are a
   versioned contract (K-log-schema@1, K-agent-headers@1).
5. The whole system can be rebuilt from GOAL, SPEC and PROMPTS by a future model, in any language,
   and pass the same black-box tests.

## Non-goals
- Inspecting or blocking content. That is llm-proxy-firewall (a standalone copy of this repo plus a
  firewall).
- A rich drill-down console with per-user timelines and 3D views. That is llm-session-console, which
  reads this log. The dashboard here stays small.
- Multi-tenant hosting, authentication of agents, or log shipping to a cloud service.
- Being a general API gateway (load balancing across providers, prompt rewriting).

## Related systems
- **Upstream:** any OpenAI-compatible chat completions API (K-openai-chat@1); OpenRouter by default.
- **Downstream:** llm-session-console reads `logs/proxy.db` (K-log-schema@1) and tests against
  `demo/data/demo.db`.
- **Siblings:** llm-proxy-firewall provides K-log-schema@2 (this schema plus firewall tables);
  vxc-motors-sim sends traffic with the K-agent-headers@1 headers.
