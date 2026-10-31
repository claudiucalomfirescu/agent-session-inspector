# Morning report · 31 October 2026

The project has been split into five repositories. Each one passes the Prax Systems **Silver** check
(spec with numbered requirements, every requirement proven by a test or a demo step, rebuild prompts,
recorded demo data, an animated explainer). Its offline tests pass too. Everything is on branch
`split` in `repos/`, and [PR #6](https://github.com/claudiucalomfirescu/agent-session-inspector/pull/6)
brings `split` into `main`.

## What needs you

1. **Create five empty GitHub repositories**: `prax-systems`, `llm-proxy-log`, `llm-proxy-firewall`,
   `vxc-motors-sim` and `llm-session-console`. Leave README, licence and .gitignore unticked. Then tell
   the project chat which account owns them. I can push them all, or you can run one command per repo.
   Both routes are in [PUBLISHING.md](PUBLISHING.md).
2. **Review the decisions made overnight.** Each repo's `DECISIONS.md` marks the autonomous ones
   "review". The ones most worth a look are listed [below](#decisions-to-review).
3. **Look at the explainers** (links below) and say what to change.

## Status

| Repo | What it is | Silver | Tests | Explainer |
|---|---|---|---|---|
| `prax-systems` | The method: six layers, workflow, seven rules, Bronze/Silver/Gold levels, templates, a stdlib checker, a worked example | ✅ 12/12 R-ids | 10 ✅ | [open](https://claude.ai/artifact/UTh6wAi3B7iQc4dyAj7MPP) |
| `llm-proxy-log` | OpenAI-compatible proxy that holds the real key, logs every call to SQLite with user/dept/session, has a gateway (rate limit, fallback, spend cap) and a small dashboard. Demo: the "Brightleaf" 4-person software team, 125 recorded calls over a week | ✅ 34/34 | 41 ✅ | [open](https://claude.ai/artifact/B6okrEHnusms6PxDMCbbGY) |
| `llm-proxy-firewall` | The same proxy plus the session firewall (info/warning/block, intent check, answers as the LLM when it blocks), with the firewall tables in the log. Demo: Brightleaf week with incidents, 50 signals, 10 sessions closed | ✅ 57/57 | 64 ✅ | [open](https://claude.ai/artifact/9B6TSTeeKKVG2z3yT3fYYN) |
| `vxc-motors-sim` | VXC Motors reworked: 12 employees are agents, apps are tools backed by small real HTTP + DuckDB services, mail and chat land in real mailboxes. [TOOLS.md](vxc-motors-sim/TOOLS.md) explains what is behind each tool. Also gives every person a resume, job description, persona and private "soul", and adds an all-staff off-site | ✅ 30/30 | 84 ✅ (2 skipped) | [open](https://claude.ai/artifact/8wC8ce5VHxeCewFyGd2izD) · [off-site replay](https://claude.ai/artifact/633ekHw6p5L5KiCf6KzMRD) |
| `llm-session-console` | Local web console over any proxy log: global → user → day/week charts → sessions → messages → firewall events, plus a Three.js galaxy view. Stdlib only, works offline, ships four weeks of demo history | ✅ 28/28 | 26 ✅ | [open](https://claude.ai/artifact/PezDkCy9QLtZon76eJiGnT) |

Checked at 00:30 UTC on `split` (`df3d9c6`) with `python3 tools/prax_check.py . --level silver` and
`python3 -m unittest discover -s tests` in each folder, after `pip install -r requirements.txt`.
The repos share contracts defined once in [CONTRACTS.md](CONTRACTS.md): the `X-Agent-User` headers,
and log schema @1 (proxy-log) and @2 (proxy-firewall). The console's tests load both proxies' demo
databases, so a breaking schema change fails its build.

## How the night went

- **Live LLM runs.** The free Nemotron model hung most of the evening. Answers took over 90 seconds
  while the quota was untouched. The recorded runs therefore used the paid `glm-5.3-flash` fallback.
  The proxy-log demo week cost about $0.0075, the off-site about $0.07 and the first VXC live day
  (489 calls) about $0.17. Total paid spend was well under the $3 target.
- **Fix that came out of it.** The gateway in all three proxies now falls back to the paid model when
  the free one *hangs*, not only when it refuses.
- **VXC live day.** The first full day scored 100% firewall precision and recall against the staged
  incidents. Thirteen tasks timed out because of the hanging free model, so the day is being re-run.
  Its recording (about 28 MB) lands on `split` in one more commit. Until then, `demo/data/` holds the
  first run.
- **Off-site meeting** (a fifth workstream you asked for at 21:32). A facilitator agent ran an
  all-staff group chat through the proxy: the GM's business review from real data, two truths and a
  lie, a brainstorm with a vote, a story game and commitments. It produced 85 messages. The replay is
  linked above.

## Follow-ups found overnight

1. **False firewall warning on Victor** (`vxc-motors-sim`, rule `discount-avoid-approval`). It fired
   on "no car leaves the bay *without that sign-off*". That sentence enforces an approval rather than
   dodging one, and the keyword rule cannot tell the two apart. Fix: add an enforcement/negation guard,
   or let the intent check downgrade this rule.
2. **Intent checks on info-level hits roughly doubled the off-site traffic** (72 extra LLM calls,
   mostly `customer_pii_leak` matching on first names). Fix: skip the intent check on info-level hits.
3. **Gold level for one repo**: rebuild `llm-proxy-log` from its P-REBUILD prompt in another
   language and pass P-VERIFY. This proves the rebuild promise. It is on the prax-systems roadmap.

## Decisions to review

All the choices you made last night (questions 1–13, all the recommended options) are in
[MASTER_PLAN.md](MASTER_PLAN.md#decisions-taken-summary-details-in-each-repos-decisionsmd). These are
the ones the threads made on their own:

| Repo | Decision | Why it matters |
|---|---|---|
| prax-systems | Six-layer model; requirements as R-ids cited by tests; P-REBUILD + P-VERIFY; Bronze/Silver/Gold with a checker | This is the method itself ([DECISIONS](prax-systems/DECISIONS.md) D-003…D-007) |
| all | Log schema adds `user` and `dept` columns, with a hashed-key fallback for unnamed callers | Every repo depends on it ([CONTRACTS](CONTRACTS.md)) |
| llm-proxy-log | D-006 token counts copied into their own columns; D-009 an offline fake LLM; D-011 demo sessions re-dated across a week | Makes charts plain SQL, tests offline, and the week view meaningful |
| llm-proxy-firewall | D-105 a generic Brightleaf policy (dealership topics stay in vxc); D-107 grounding optional; D-110 harassment capped at warning when only the LLM flags it | Changes what gets blocked |
| vxc-motors-sim | D-005 mail/chat as a "doorbell" plus read-by-tool; D-008 one judgment tool (BMW tech case); D-011 vendored firewall proxy; D-015 folders renamed `apps/`, `agents/`, `sim/` | Shapes how the company behaves |
| vxc-motors-sim/offsite | D-OFF-002 the "soul" is private; D-OFF-003 risk personas get an inner tension, not a script; D-OFF-004 an outside facilitator | Shapes the personalities |
| llm-session-console | D-004 stdlib only, no framework; D-007 firewall/console traffic hidden by default; D-008 history rebuilt from real sessions; D-011 no LLM summaries | Keeps it offline and read-only |

## PR #6

You asked to accept the PRs. PR #6 is the only one, and it brings everything above into `main`. All
five repos pass, so I merge it as soon as the VXC re-run recording lands on `split`. That way `main`
gets the complete set in one merge. The status line at the top of the thread says when it is merged.
