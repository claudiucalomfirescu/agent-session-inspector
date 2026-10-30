# Off-site meeting · DECISIONS

All decided autonomously overnight on 2026-10-30 while the user slept; please review.

- **D-OFF-001 · Four files per person, on top of the existing personas.** `company/personas/<id>.md` stays the
  source of truth for facts (owned by the main sim thread); `people/<id>/` adds resume, job, persona, soul.
  *Alternative:* extend the persona frontmatter. Rejected: it would mix facts with prose and conflict with the
  thread reworking the sim. *Consequence:* any agent can load the identity with one import.
- **D-OFF-002 · The soul is private.** The preamble tells the agent to follow its persona in public and let the
  soul shape reactions without reciting it. This is what makes the off-site feel human rather than a list of
  self-descriptions.
- **D-OFF-003 · Risk personas get an "inner tension", not a script.** Tom, James and Mark's souls explain *why*
  they are tempted and what weakens the temptation. Nothing in the off-site pushes them towards misconduct.
- **D-OFF-004 · External facilitator.** The user asked for "a moderator in the chat". A neutral outsider (Hannah
  Brooks) keeps the GM from also chairing, and can pick quiet people for Q&A.
- **D-OFF-005 · Games are scored by code.** The lie is hidden in a separate `LIE:` line the runner strips; votes
  are tallied by the runner. LLMs judge nothing that has a right answer.
- **D-OFF-006 · Real numbers for the business review.** Victor gets a fact sheet computed from the sim's seed data
  and is told to quote only it; the fact sheet is saved with the run so claims can be checked.
- **D-OFF-007 · One session per attendee.** `X-Session-Id = offsite-20261031-<id>` so the console's
  user → sessions → messages drill-down shows each person's off-site as one conversation; the shared meeting is
  identified by the label `event=offsite-2026` and `segment`.
- **D-OFF-008 · Model and budget.** Budget for this thread: free model at most 3 requests/minute, GLM fallback,
  paid ≤ $1.50. During the run the free model (`nvidia/nemotron-3.5-super-vl:free`) did not answer within 90 s
  (OpenRouter hung), so the runner's circuit breaker switched to `z-ai/glm-5.3-flash` for blocks of 15 calls and
  probed the free model once between blocks. GLM needs reasoning enabled; the runner asks for `effort: low` and
  excludes the reasoning text. See `runs/2026-10-31/meta.json` for the model split and token counts.
- **D-OFF-009 · No tools in the meeting.** It is a conversation, not a workday; keeping tools out makes the run
  cheap and the transcript readable. *Idea, not commitment:* feed each person's commitments into their next
  workday prompt so the off-site has consequences.
