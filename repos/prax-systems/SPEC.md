# Specification · Prax Systems

> Version 0.1 · Contracts provided: `K-prax-repo@0.1` (the repository contract),
> `K-prax-manifest@0.1` (prax.yaml). The explanation lives in [METHOD.md](METHOD.md); this file is
> the testable core.

## 1. Glossary
| Term | Meaning |
|---|---|
| System | Several cooperating components whose important behaviour happens between them |
| Ecosystem | Several systems (repos) that share versioned contracts |
| Component (C-xx) | A part with one responsibility: a process, a store, an agent group, a UI |
| Contract (K-name@v) | An interface another part depends on: routes, headers, schemas, file formats |
| Requirement (R-xxx) | One testable behaviour with an acceptance check |
| Prompt (P-xx) | One recorded instruction to a coding model that produced part of the repo |
| Rendering | The code: one implementation of the spec |

## 2. Components
| Id | Component | Responsibility |
|---|---|---|
| C-01 | METHOD.md | Explains the layers, files, workflow, rules, ecosystems, rebuilds |
| C-02 | templates/ | One template per required file |
| C-03 | tools/prax_check.py | Checks a repo against K-prax-repo (bronze, silver) |
| C-04 | explainers/index.html | Animated explainer of the method |

## 3. Contracts

### K-prax-repo@0.1 — files every Prax System repo contains
`prax.yaml`, `README.md`, `GOAL.md`, `SPEC.md`, `ARCHITECTURE.md`, `PROMPTS.md`, `ROADMAP.md`,
`DECISIONS.md`; for Silver also `demo/DEMO.md`, non-empty `demo/data/`, `explainers/index.html`,
`tests/`.

### K-prax-manifest@0.1 — prax.yaml
Top-level keys: `prax`, `name`, `kind` (`system` | `method`), `one_liner`, `status`, `run` (with
`demo`, `tests`), `docs`, `explainer` (`file`, `published`), optional `components`, `contracts`
(`provides`, `depends_on`), `built_with` (`model`, `date`, `language`), `level_target`.

## 4. Requirements
| Id | Requirement | Acceptance check |
|---|---|---|
| R-001 | Every repo MUST contain the K-prax-repo bronze files | test_R001 (checker flags a missing file) |
| R-002 | SPEC.md MUST define numbered requirements R-xxx, each with an acceptance check | test_R002 |
| R-003 | PROMPTS.md MUST contain step prompts P-01… plus P-REBUILD and P-VERIFY | test_R003 |
| R-004 | prax.yaml MUST carry the K-prax-manifest required keys | test_R004 |
| R-005 | Silver: every R-id MUST be cited by a test or marked manual in SPEC.md | test_R005 |
| R-006 | Silver: demo/data MUST hold recorded data so a clone works without secrets | test_R006 |
| R-007 | Silver: explainers/index.html MUST exist and be self-contained (no external URLs) | manual: open from file:// offline |
| R-008 | Contracts shared across repos MUST have a versioned id and one owner | manual: ecosystem table in MASTER_PLAN |
| R-009 | The checker MUST run on the Python standard library only | test_R009 |
| R-010 | Templates MUST exist for every bronze file plus DEMO.md and the explainer guide | test_R010 |
| R-011 | Template placeholders left in a repo MUST be reported | test_R011 |

## 5. Quality bars
| Id | Bar | Check |
|---|---|---|
| R-101 | The method fits in one read (METHOD.md under ~400 lines) | manual: line count |

## 6. Out of scope
Code generation, CI wiring, hosting of explainers.
