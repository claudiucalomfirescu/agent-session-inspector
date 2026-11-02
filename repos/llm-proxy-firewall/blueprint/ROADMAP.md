# Roadmap · llm-proxy-firewall

Status: ✅ done · 🔜 in progress · ⏳ planned · 💤 parked

| Milestone | Delivers | Status |
|---|---|---|
| M1 · Everything in llm-proxy-log M1–M6 | R-001…R-044 | ✅ (copied 2026-10-30) |
| M2 · Detection: keywords and co-occurrence, signals table | R-201…R-204, R-213 | ✅ (learning project lesson 8) |
| M3 · Enforcement: answer as the LLM, blocked sessions, admin routes | R-208…R-212, R-214, R-216 | ✅ (lesson 9) |
| M4 · LLM intent check with stance, through the gateway | R-205…R-207, R-215 | ✅ (lesson 9 tuning, 2026-10-28) |
| M5 · Generic policy file, organisation in the prompt, optional grounding, LLM caps | R-217…R-219 | ✅ 2026-10-30 |
| M6 · Dashboard firewall view, demo with incidents, K-log-schema@2 fixture | R-230, R-231, R-242, R-243 | ✅ 2026-10-30 |
| M7 · Prax Systems Silver | docs, explainer | ✅ 2026-10-30 |
| M8 · Published as its own GitHub repo | — | ⏳ waits for the user |
| M9 · Evaluation harness: replay a labelled log through the current rules and report precision/recall | — | ⏳ (exists in the learning project as runner/refirewall.py + evaluate.py) |

## Next
- Port the evaluation harness (replay a recorded log through the firewall, score against labels) so
  policy changes are measured, not guessed.
- Tune the classifier prompt on the demo week: the LLM raised four of the risky requests from warning
  to block that evening (see D-010), which is defensible but strict.
- Notifications: a webhook on `block_session`.

## Ideas, not commitments
- Per-user or per-department topic sets (sales may discuss discounts, support may not).
- Redaction mode: mask the secret and forward, instead of blocking the whole turn.
- A second opinion: two different classifier models must agree before an LLM-only block.
