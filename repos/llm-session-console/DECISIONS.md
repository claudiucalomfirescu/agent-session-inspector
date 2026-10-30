# Decisions · llm-session-console

Decisions marked *autonomous* were taken overnight on 2026-10-30 while the user slept, under their
instruction to proceed and review in the morning.

| Id | Date | Decision | Why | Alternatives | Decided by |
|---|---|---|---|---|---|
| D-001 | 2026-10-30 | The console is its own repo, separate from the proxies, reading their SQLite log over a versioned contract | User wants small pieces that can be recombined; the log file is the natural seam | Console inside each proxy repo | user (split brief, 5a) |
| D-002 | 2026-10-30 | 2D drill-down is the main UI; one Three.js galaxy view on top | 2D answers questions fast; 3D is for seeing the whole and presenting | 3D as main UI; no 3D | user (8a) |
| D-003 | 2026-10-30 | User identity = `X-Agent-User` → `calls.user`, fallback `key:<hash>`, then agent id | Agreed with the llm-proxy-log thread (owner of K-agent-headers@1); agent id fallback keeps old logs readable | Per-user API keys only; body field | user (7a) + agent (fallback chain) |
| D-004 | 2026-10-30 | Python standard library only, no framework; plain SVG charts; Three.js vendored | Clone-and-see with zero installs and no network (Prax rule 4); the UI is small enough | Flask/FastAPI + React + chart lib | agent (autonomous, review) |
| D-005 | 2026-10-30 | Keep a light in-memory index (`facts`) instead of querying the log's JSON on every request | The request/response columns are ~95% of the file; aggregates over 4.4k calls stay in milliseconds | Query JSON directly; build a sidecar DB on disk | agent (autonomous, review) |
| D-006 | 2026-10-30 | Read-only connection in autocommit mode | Found in testing: an open read transaction blocked the proxy's writes ("database is locked") | Copy the log first | agent (autonomous) |
| D-007 | 2026-10-30 | Firewall calls (`firewall` agent) and `console-*` agents are "system traffic", hidden by default with a toggle | They are real LLM calls but not anyone's work; mixing them in inflated one "user" | Always show; never show | agent (autonomous, review) |
| D-008 | 2026-10-30 | Demo data = the real recorded VXC Motors day (old schema) + a 4-week history rebuilt only from real recorded sessions (copied, re-dated, marked `labels.replay_of`) | Day/week charts need weeks of data; only two real days exist and a new 4-week live run would cost thousands of LLM calls. Rebuilding from real sessions keeps every message genuine and says so | Synthetic text; a long live run | agent (autonomous, review) |
| D-009 | 2026-10-30 | Demo logs ship xz-compressed (~1 MB) and unpack on first run to `demo/data/.cache/` (git-ignored) | The 4-week log is ~160 MB raw because every call repeats the conversation and tool list; xz shrinks it ~200× | Ship raw; strip tool schemas | agent (autonomous) |
| D-010 | 2026-10-30 | Sessions are shown as *steps*: only the messages each call added, plus the answer | Reading raw calls repeats the whole conversation on every row; this was the main readability complaint | Show last call only (loses per-call firewall context) | agent (autonomous, review) |
| D-011 | 2026-10-30 | No LLM summaries in this console | Keeps it offline and read-only; the old console needed a firewall exemption for its summariser | Port `summarize.py` | agent (autonomous, review) |
| D-012 | 2026-10-30 | Default port 8095 | 8080 proxy, 8090 old console, 8091 dashboard are taken in the sibling repos | — | agent (autonomous) |
