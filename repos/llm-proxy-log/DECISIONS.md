# Decisions · llm-proxy-log

All entries dated 2026-10-30 were taken autonomously overnight while the user slept, inside the
choices the user made that evening (questions 1–13, all "recommended"). They are flagged for review.

| Id | Date | Decision | Why | Alternatives | Decided by |
|---|---|---|---|---|---|
| D-001 | 2026-10-27 | The proxy holds the only provider key; agents send a dummy key and change only their base URL. | One place to protect and rotate the key; zero agent changes. | Key in every agent. | user (learning project) |
| D-002 | 2026-10-27 | SQLite, one file, one row per call, bodies stored as JSON text. | No server to run; any language can read it; easy to ship as demo data. | JSONL files; Postgres. | user + agent |
| D-003 | 2026-10-30 | Repo is a standalone copy extracted from agent-session-inspector, not a package depended on by the firewall repo. | User answer 4a: each repo clonable and runnable alone. | Shared library. | user |
| D-004 | 2026-10-30 | Identity via `X-Agent-User` / `X-Agent-Dept` / `X-Agent-Id` / `X-Session-Id`, fallback `key:<8 hex>` then `anonymous`; agent defaults to user; missing session derived from agent + first user message. | User answer 7a; CONTRACTS.md proposal; deriving the session keeps multi-turn conversations together for clients that send no session header. | Separate key per user; field in the body. | user (7a) + agent (derivation rule, autonomous, review) |
| D-005 | 2026-10-30 | Keep a `key_id` column (8 hex) besides the `key:` fallback in `user`. | The console thread asked for it; lets a reader group by key even when users are named. | Only the fallback in `user`. | agent (with console thread), review |
| D-006 | 2026-10-30 | Copy token counts into `prompt_tokens` / `completion_tokens` / `total_tokens` columns. | Charts by day and user become plain SQL; `usage` JSON is kept as is. | Parse JSON in every reader. | agent, review |
| D-007 | 2026-10-30 | Keep the gateway (rate limit, fallback, spend cap, cache) in this repo. | The demo runs on OpenRouter's free tier, which needs a limiter; it is generic enough for any OpenAI-compatible provider and can be switched off. | Drop it for a smaller repo. | agent, review |
| D-008 | 2026-10-30 | Demo company "Brightleaf Software", four people and agents (maya/dev, omar/support, lena/sales, raj/ops), tools over a JSON file. | User answer 6a: a generic small team, not VXC Motors. Tools are deliberately trivial so the traffic is the subject. | Reuse VXC staff. | user (6a) + agent (cast) |
| D-009 | 2026-10-30 | An offline fake LLM (`demo/fake_llm.py`) for tests and the no-key demo. | Rule "clone-and-see" and offline tests; deterministic. | Only recorded data. | agent, review |
| D-010 | 2026-10-30 | The recorded demo day was generated with `z-ai/glm-5.3-flash` (paid, about $0.0075 for 125 calls), not the free Nemotron model. | The free model hung for over a minute per call that evening; GLM answered in about 3 s. The cost is negligible and within the $1.50 thread budget. | Wait for the free model. | agent, review |
| D-011 | 2026-10-30 | `demo/data/demo.db` spreads the recorded sessions over the 7 days ending 2026-10-30 and marks them `redated: true`; `team-day.json` keeps the true timestamps. | The console needs several days to show day/week charts; honesty requires the mark. | Record over 7 real days. | agent, review |
| D-012 | 2026-10-30 | Small dashboard is one static page over two JSON routes, no build step, no CDN. | User answer 5a: small dashboard here, rich drill-down in llm-session-console. | Port the six boards of the learning project. | user (5a) + agent |
| D-013 | 2026-10-30 | `GET /healthz` answered by the proxy itself and not logged. | Health checks (tests, demo runner) must not pollute the log. | Probe `/v1/gateway/status`, which is forwarded when the gateway is off. | agent |
