# echo-log (example)

The smallest repo that passes `prax_check.py --level silver`. Two components: an echo function and
an append-only JSONL log. It exists so the checker has a known-good input.

```bash
python3 src/echo.py hello          # prints hello, appends a line to log.jsonl
python3 -m unittest discover -s tests
```
