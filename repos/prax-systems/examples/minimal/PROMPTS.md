# Rebuild prompts · echo-log

## P-REBUILD
```text
Rebuild the system in GOAL.md and SPEC.md in <LANGUAGE>. Keep K-echo-log@1 exactly. Port tests/ keeping R-ids.
```

## P-VERIFY
```text
Run the tests and demo/DEMO.md; report pass/fail per R-id in SPEC.md.
```

## P-01 · Echo and log
- **Delivers:** R-001, R-002, R-003
- **Done when:** `python3 -m unittest discover -s tests`

```text
Write src/echo.py with echo(msg, log_path) that returns msg and appends {"ts","msg"} as one JSON line,
and replay(log_path) that prints each msg. Add a CLI. Write tests named test_R001…, test_R002….
```
