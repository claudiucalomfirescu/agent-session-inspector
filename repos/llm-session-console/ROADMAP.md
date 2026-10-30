# Roadmap · llm-session-console

Status: ✅ done · 🔜 in progress · ⏳ planned · 💤 parked

| Milestone | Delivers | Status |
|---|---|---|
| M1 · Read any proxy log, read-only | R-001…R-004, R-015…R-017 | ✅ 2026-10-30 |
| M2 · Drill-down: global → user → day → session → call | R-005…R-011, R-021, R-024 | ✅ 2026-10-30 |
| M3 · Firewall layer (K-log-schema@2) | R-012, R-023 | ✅ 2026-10-30 |
| M4 · Galaxy 3D | R-013, R-022 | ✅ 2026-10-30 |
| M5 · Clone-and-see: bundled demo logs, live replay, explainer | R-018, R-101, R-102 | ✅ 2026-10-30 |
| M6 · Contract tests against the owners' demo DBs | R-002 on llm-proxy-log and llm-proxy-firewall fixtures | 🔜 (test written; runs once the fixtures land next to this repo) |
| M7 · Compare and export | ⏳ R-2xx to be specified | ⏳ |

## Next
- Load the Brightleaf demo team logs from llm-proxy-log / llm-proxy-firewall as extra bundled demos
  once those repos publish them.
- Compare two periods or two users side by side (e.g. this week vs last).
- Export the current view as CSV / a static HTML snapshot for sharing without the log.
- Tool executions as their own layer if a proxy starts logging them (today the console only sees
  that the LLM *asked* for a tool, and the result the agent sent back next turn).

## Ideas, not commitments
- Galaxy time-lapse: replay a day and watch planets appear as sessions start.
- Cost estimates from a price table for models that do not report cost.
- Optional read-only link to the firewall's admin API (block / unblock from the console) — kept
  out for now so the console stays strictly read-only.
- Per-user anomaly hints (a user suddenly 5× their usual volume, an unusual hour).
