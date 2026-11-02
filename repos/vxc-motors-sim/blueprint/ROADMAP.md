# Roadmap · vxc-motors-sim

Status: ✅ done · 🔜 in progress · ⏳ planned · 💤 parked

| Milestone | Delivers | Status |
|---|---|---|
| M1 · Company and data (lesson 4–5 of the parent project) | R-024, R-025, R-103 | ✅ 2026-10-27 |
| M2 · First live workdays, in-process tools (lesson 6–9) | day 1 and day 2 runs, firewall v2 | ✅ 2026-10-27 |
| M3 · Agents and tools, split into its own repo | R-002…R-007, R-010…R-023, R-026, R-027 | ✅ 2026-10-30 |
| M4 · Recorded day 3 on the new architecture, explainer published | R-001, R-008, R-009, R-101 | ✅ 2026-10-31 |
| M5 · More judgment: warranty claims and goodwill decided by BMW agents; customer agents that remember earlier emails | new R-ids | ⏳ |
| M6 · Several days in a row (the clock rolls over, open work carries on, a week of traffic for the console's day/week charts) | new R-ids | ⏳ |
| M7 · Each application as its own process and port (one DuckDB file each) | K-vxc-tools@2 | 💤 |

## Next
- Re-record with the sharper Aisha goal (fault code given) so the shipped day shows the BMW tech-support judgment agent (D-019).
- Run 2 of day 3 (not shipped) had flag precision 0.70: warnings on Sofia reading the recruiter's first email, a chat
  quoting "without your approval", and Victor asking Aisha to raise a claim "from her own login". Watch these.
- Re-record the day on the free model when it is answering again, and compare with the GLM day.
- Score day 3 with `python -m sim.evaluate demo/data` and tune the firewall topic file (lessons from days 1–2: refusals must not be blocked, approval claims need grounding).
- Feed the people/ identity files (resume, job, persona, soul) from the off-site thread into the staff prompts.

## Ideas, not commitments
- A second dealership (a competitor) so poaching becomes a real cross-company conversation.
- Agents with memory across tasks (a notes application they write to).
- A "manager view" agent that summarises the day for Victor from the applications' audit tables.
