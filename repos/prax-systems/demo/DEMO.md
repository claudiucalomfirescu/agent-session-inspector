# Demo · Prax Systems

## Check a repo (no setup)
```bash
python3 tools/prax_check.py examples/minimal --level silver   # PASS: a tiny compliant repo
python3 tools/prax_check.py ../llm-proxy-log --level silver   # the real thing
```

## Check the whole ecosystem
```bash
for r in ../llm-proxy-log ../llm-proxy-firewall ../vxc-motors-sim ../llm-session-console; do
  python3 tools/prax_check.py "$r" --level silver; done
```

## Walkthrough
1. Read [METHOD.md](../METHOD.md) §2 (six layers): proves the method fits in one read (R-101).
2. Run the checker on `examples/minimal`: PASS (R-001…R-006).
3. Delete `examples/minimal/PROMPTS.md` in a scratch copy and rerun: FAIL "missing PROMPTS.md" (R-001, R-003).
4. Open [explainers/index.html](../explainers/index.html) offline (R-007).
