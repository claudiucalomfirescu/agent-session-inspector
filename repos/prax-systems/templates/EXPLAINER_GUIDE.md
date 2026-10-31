# Writing the animated explainer

One file: `explainers/index.html`. Self-contained (inline CSS/JS/SVG, no CDN, no fetch), opens from
`file://`, light and dark, respects `prefers-reduced-motion`, readable at 375px wide.

## Scenes (in this order)
1. **What** — the system in one picture: its components as labelled shapes.
2. **The problem** — the world without it (e.g. agents call the LLM directly; nobody sees what they say).
3. **How it works** — one real request (ideally from `demo/data/`) travels through every component;
   each hop highlights and a caption explains it. Controls: ▶ play / ❚❚ pause / step ← → / speed.
4. **What you get** — the output (dashboard, log rows, blocked reply), drawn from demo data.
5. **Replicate it** — the exact commands from README, and "build your own": what to change for your case.

## Rules
- Use real names from SPEC.md (headers, tables, routes). The explainer is documentation, not marketing.
- Each scene has a heading and a 1–3 sentence caption a non-engineer understands.
- Keyboard: space = play/pause, arrows = step.
- Publish it as an artifact and put the link in README and `prax.yaml`.
