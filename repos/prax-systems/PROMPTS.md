# Rebuild prompts · Prax Systems

These prompts rebuild this methodology repo. Give the model `prax.yaml`, `GOAL.md` and `SPEC.md`
first. The method text itself (METHOD.md) is prose: a rebuild may reword it but must keep every
layer, file, rule and level it names.

## P-REBUILD — one shot
```text
You are rebuilding "Prax Systems", a methodology repository, from GOAL.md and SPEC.md (attached).
Produce:
1. METHOD.md explaining: what counts as a system; the six layers (Intent/GOAL, Contract/SPEC,
   Proof/tests+demo, Recipe/PROMPTS, Shape/ARCHITECTURE, Rendering/code) plus DECISIONS, ROADMAP,
   explainers; the exact content of each required file; the 6-step workflow
   (Frame, Spec, Prove, Render, Show, Seal); the 7 rules; ecosystems with versioned contracts and
   one owner each; how to rebuild with a future model; Bronze/Silver/Gold levels. Under 400 lines.
2. templates/ with one template per file in K-prax-repo@0.1 plus DEMO.md and EXPLAINER_GUIDE.md.
3. tools/prax_check.py in <LANGUAGE, default Python stdlib only> implementing R-001…R-011.
4. examples/minimal: the smallest repo that passes --level silver.
5. tests/ proving each R-id, named test_R0xx.
6. explainers/index.html: a self-contained animated explainer (see templates/EXPLAINER_GUIDE.md).
Keep K-prax-repo@0.1 and K-prax-manifest@0.1 exactly as in SPEC.md.
```

## P-VERIFY
```text
Run `python3 -m unittest discover -s tests` and `python3 tools/prax_check.py examples/minimal
--level silver`. Then run the checker on every sibling repo and list each R-id in SPEC.md with
pass/fail/manual and evidence. Do not edit SPEC.md to make something pass.
```

## Step-by-step prompts (as actually used, 2026-10-30)

### P-01 · Frame the method
- **Delivers:** GOAL.md, README.md, D-001…D-002
- **Read first:** the user's brief (split the project into repos; every repo ships code AND
  specifications, goals and prompts so a future model can rebuild it, possibly in another language;
  methodology like Prax Analytics / Prax App but for systems)

```text
Our Prax family has Prax Analytics (pipelines) and Prax App (apps). We now build systems: agents,
a proxy, a firewall, local services, a console, recorded traffic, split across repos that may be
recombined. Name the new method "Prax Systems". Write README.md that contrasts it with the other
two in a table, states the hard rule "code is one rendering; the spec is the system", and lists the
repository contract. Write GOAL.md (pitch, problem, audience, success criteria, non-goals).
```

### P-02 · Write the method
- **Delivers:** METHOD.md, R-101, D-003…D-007

```text
Write METHOD.md: when to use it; six layers ordered by durability with a table of what survives a
rewrite; each required file precisely (prax.yaml, GOAL, SPEC with glossary/components/contracts/
R-ids with acceptance checks, ARCHITECTURE with requirement→code map, PROMPTS with P-xx entries
and P-REBUILD/P-VERIFY, ROADMAP, DECISIONS, demo/ with recorded data + generator + DEMO.md,
explainers/index.html scenes, tests tagged with R-ids); a 6-step workflow diagram; 7 rules;
ecosystems (versioned contracts K-name@v with one owner, consumers cite by version and test
against the owner's fixture); rebuilding with a future model; Bronze/Silver/Gold.
```

### P-03 · Templates
- **Delivers:** R-010

```text
Create templates/ with prax.yaml, README.md, GOAL.md, SPEC.md, ARCHITECTURE.md, PROMPTS.md,
ROADMAP.md, DECISIONS.md, DEMO.md, EXPLAINER_GUIDE.md. Use angle-bracket placeholders such as the repo name the checker
can detect.
```

### P-04 · Checker, example and tests
- **Delivers:** R-001…R-006, R-009, R-011
- **Done when:** `python3 -m unittest discover -s tests` passes

```text
Write tools/prax_check.py (stdlib only): bronze checks required files, non-trivial size, leftover
placeholders, manifest keys, P-REBUILD/P-VERIFY/P-01 in PROMPTS, R-ids in SPEC, a quickstart code
block in README; silver adds demo/DEMO.md, non-empty demo/data, explainers/index.html, tests/, and
every R-id cited in tests (R004 or R-004) or marked manual in its SPEC row. Exit 0/1, --json.
Build examples/minimal (echo + JSONL log) that passes silver. Write tests/test_checker.py with one
test per R-id that mutates a copy of the example.
```

### P-05 · Explainer
- **Delivers:** R-007

```text
Build explainers/index.html per templates/EXPLAINER_GUIDE.md: scenes What (the Prax family and a
system as a graph of parts), Problem (code outlives nothing; knowledge lost in chat), How (the six
layers stacking; the 6-step workflow animating; a rebuild: a new model reads GOAL+SPEC+tests and
renders new code that passes the same tests), Ecosystem (4 repos sharing versioned contracts),
Replicate (copy templates, run the checker). Self-contained, light/dark, reduced motion, keyboard.
```
