# Roadmap · Prax Systems

| Milestone | Delivers | Status |
|---|---|---|
| M1 · v0.1 method, templates, checker | R-001…R-011 | ✅ 2026-10-30 |
| M2 · Applied to 4 repos (proxy-log, proxy-firewall, motors-sim, session-console) | Silver for each | 🔜 2026-10-31 |
| M3 · Animated explainer of the method, published | R-007 | 🔜 |
| M4 · First Gold: rebuild llm-proxy-log from P-REBUILD in another language (e.g. Go or TypeScript) and pass P-VERIFY | Gold | ⏳ |
| M5 · Language-neutral acceptance tests (HTTP/SQL fixtures run by a tiny harness, so a rebuild in any language reuses them unchanged) | | ⏳ |

## Ideas, not commitments
- A catalogue page generated from every repo's prax.yaml.
- `prax_check.py --fix` that copies missing templates in.
- Prompt "lineage": record model + date per P-xx when it is re-run.
