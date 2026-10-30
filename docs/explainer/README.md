# Agent session explainer

[`index.html`](index.html) is an animated, step-by-step walk through one real multi-turn agent session:
the user's question, each model call going agent → proxy → OpenRouter, the proxy writing its log row,
the tool runs between calls, and the final reply. Open the file in a browser; it needs no network.

**Data.** The page replays proxy log session `c5300e26f24a` (agent `support-bot`,
model `nvidia/nemotron-3.5-super-vl:free`, 27 Oct 2026, log rows #1–#5) from
[`viz/data/lesson3-sample-log.json`](../../viz/data/lesson3-sample-log.json), the run from the
order A-1001 example in [lesson 3](../lessons/03-proxy-logging.md). The rows are embedded in the page.
Every number, message, reasoning excerpt and tool call on screen is read from those rows; tool results
come from the next request's messages, because the proxy only sees model calls.

Controls: Play/Pause, previous/next, the step slider, ← → keys, space to play, Home/End.
`?session=<id>` picks another session when the embedded data has several.

**Use another session.** `viz/embed_log.py` rewrites the embedded rows:

```
python3 viz/embed_log.py viz/data/lesson3-sample-log.json --session c5300e26f24a --out docs/explainer/index.html
python3 viz/embed_log.py logs/proxy.db --session <id> --out docs/explainer/index.html
```

The source line in the page names `viz/data/lesson3-sample-log.json`; change the `source-path`
block in `index.html` if you embed from somewhere else.
