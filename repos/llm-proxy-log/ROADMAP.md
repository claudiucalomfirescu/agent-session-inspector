# Roadmap · llm-proxy-log

Status: ✅ done · 🔜 in progress · ⏳ planned · 💤 parked

| Milestone | Delivers | Status |
|---|---|---|
| M1 · Pass-through proxy holding the key | R-001…R-003, R-010, R-103 | ✅ (learning project lesson 2) |
| M2 · SQLite log of every call | R-004, R-009, R-011…R-014 | ✅ (lesson 3) |
| M3 · Gateway: rate limit, retry, fallback, spend cap, cache | R-020…R-025 | ✅ (lesson 3b) |
| M4 · Identity contract K-agent-headers@1 (user, dept, session, labels) | R-005…R-008 | ✅ 2026-10-30 |
| M5 · Small dashboard | R-030…R-034 | ✅ 2026-10-30 |
| M6 · Demo team, offline fake LLM, recorded data, fixture for the console | R-040…R-044 | ✅ 2026-10-30 |
| M7 · Prax Systems Silver: docs, explainer, self-containment tests | R-100…R-102 | ✅ 2026-10-30 |
| M8 · Published as its own GitHub repo | — | ⏳ waits for the user to create the repo |
| M9 · Gold: P-REBUILD replayed by another model or in another language | — | ⏳ |

## Next
- Publish as a standalone repo (`git subtree split --prefix repos/llm-proxy-log`, see ../PUBLISHING.md).
- Replay P-REBUILD in Go or TypeScript to reach Gold and prove the contracts are enough.
- Streaming: log the assembled text and usage of streamed answers (today the raw SSE body is stored).

## Ideas, not commitments
- Per-user budgets and rate limits in the gateway (the identity is already there).
- Log retention: a `prune --older-than 30d` command, and optional body truncation.
- Export to OpenTelemetry spans for teams that already run a tracing stack.
- A `--read-only-replay` mode that serves a recorded day back to agents for regression tests.
