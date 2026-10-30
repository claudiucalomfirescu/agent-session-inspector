# Decisions · Prax Systems

| Id | Date | Decision | Why | Alternatives | Decided by |
|---|---|---|---|---|---|
| D-001 | 2026-10-30 | Name it **Prax Systems**, in its own repo `prax-systems` | Sits beside Prax Analytics and Prax App; what we build are systems, not apps or pipelines | "Prax Ecosystems", per-repo copies | user (picked recommended option) |
| D-002 | 2026-10-30 | Spec is the source of truth; code is "one rendering" | User's hard rule: repos must be rebuildable by future models, possibly in another language | Code-first with docs after | user rule, wording by agent |
| D-003 | 2026-10-30 | Six layers: Intent, Contract, Proof, Recipe, Shape, Rendering | Orders files by how long they stay true; tells a rebuild what it may replace | Flat list of required files | agent (autonomous, review) |
| D-004 | 2026-10-30 | Requirements as R-ids with acceptance checks; tests cite R-ids | Traceability is what makes "rebuild and verify" mechanical | Prose spec | agent (autonomous, review) |
| D-005 | 2026-10-30 | PROMPTS.md has step prompts plus one-shot P-REBUILD and P-VERIFY | Future models can likely one-shot; step prompts are the fallback and the history | Only step prompts | agent (autonomous, review) |
| D-006 | 2026-10-30 | Versioned contracts with a single owner for the ecosystem (K-log-schema, K-agent-headers) | Lets repos split now and recombine later without a monorepo | Shared library package | agent (autonomous, review) |
| D-007 | 2026-10-30 | Bronze / Silver / Gold levels and a stdlib-only checker | Keeps the user honest automatically; Silver is the bar for first publication | Manual checklist only | agent (autonomous, review) |
| D-008 | 2026-10-30 | Explainer is one self-contained HTML file per repo, also published as an artifact | Works from a clone offline and as a link | Video/GIF | user (picked recommended option) |
