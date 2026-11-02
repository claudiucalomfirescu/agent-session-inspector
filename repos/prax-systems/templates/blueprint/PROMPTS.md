# Rebuild prompts · <name>

These prompts rebuilt this repository from an empty folder. They are written for a capable coding
model; they say *what* and cite the spec, and say *how* only where the how is a contract.

**Always give the model first:** `prax.yaml`, `GOAL.md`, `SPEC.md`, and for later steps the files
it already produced.

## P-REBUILD — one shot
```text
You are rebuilding the system described in GOAL.md and SPEC.md (attached), whose current shape is
in ARCHITECTURE.md. Target language/runtime: <LANGUAGE>. Implement every requirement R-xxx in
SPEC.md and every contract K-… exactly as specified (routes, headers, schemas, file formats are not
negotiable; internal structure is yours). Port the acceptance tests in tests/ to <LANGUAGE>
keeping their R-ids, and keep demo/data/ byte-compatible. Finish with a README quickstart that
works offline from demo/data/. Report which R-ids you could not satisfy and why.
```

## P-VERIFY
```text
Run the acceptance tests and the walkthrough in demo/DEMO.md against the rebuild. Produce a table
of every R-id in SPEC.md with pass/fail/manual and the evidence. Do not change SPEC.md to make a
test pass.
```

## Step-by-step prompts

### P-01 · <title>
- **Goal:** what exists after this step
- **Delivers:** R-001, R-002
- **Read first:** GOAL.md, SPEC.md §2–3
- **Done when:** `python3 -m unittest tests.test_x`

```text
<the exact prompt>
```

### P-02 · …
