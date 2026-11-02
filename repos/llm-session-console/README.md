# llm-session-console

> Drill down into and replay LLM agent sessions.

<p align="center"><img src="explainers/readme-flow.svg" alt="Animated diagram of how llm-session-console works" width="100%"></p>

> [!IMPORTANT]
> **This repo publishes the blueprint, not just the code.** Most projects share only their code.
> This one also ships, in [`blueprint/`](blueprint/), the goal, the full specification, the
> architecture, every design decision and the ordered prompts an LLM followed to build it. Code is
> written by today's models and ages with them; the blueprint does not. When a more capable model
> arrives, anyone can hand it the blueprint, regenerate this project from scratch (in this language
> or another) and prove the result with the same tests and recorded demo data.
> [How to rebuild it ↓](#rebuild-it-from-the-blueprint)

## The problem it solves

A logging LLM proxy writes every agent conversation to a SQLite file. That file is complete but
unreadable: each row is one HTTP call carrying the *whole* conversation so far, thousands of rows a
day, JSON inside JSON. The questions people actually ask (who uses the LLM, how much, when, for what,
and what did the firewall catch) need a SQL session and a lot of patience, and nothing lets you move
between the big picture and the single message that matters.

llm-session-console opens that log read-only and takes you from all traffic to one user, one day,
one session read as a conversation, one call and the firewall finding on it, in a few clicks.

**Animated explainer:** [explainers/index.html](explainers/index.html) · [published](https://claude.ai/artifact/PezDkCy9QLtZon76eJiGnT)

## What it is
Your LLM proxy (e.g. [llm-proxy-log](../llm-proxy-log/) or [llm-proxy-firewall](../llm-proxy-firewall/))
writes every agent conversation into a SQLite file. That file is complete but unreadable: each row
repeats the whole conversation, JSON inside JSON. This console opens it **read-only** and lets you go
from the big picture to a single message in a few clicks:

**all traffic → one user → one day or week → one session → one LLM call → the firewall finding on it.**

Per user and globally you get calls, sessions, tokens and active users by day or week, a weekday × hour
heatmap, the tools the LLM called, and — when the log comes from the firewall proxy — every info,
warning and block. A Three.js **galaxy** shows the same hierarchy in 3D: users are stars, sessions are
planets, calls are moons; click to drill.

## 60-second quickstart (no API key, no install)
```bash
git clone <url> llm-session-console && cd llm-session-console
python3 -m console              # Python 3.10+, standard library only
# open http://127.0.0.1:8095/
```
It serves four bundled logs (picker top right): four weeks of the VXC Motors dealership (12 employee
agents + customers, real recorded LLM traffic, firewall on), the first recorded VXC day in the old
log format, and the Brightleaf demo team's week from llm-proxy-log (no firewall) and from
llm-proxy-firewall (with firewall). See [demo/DEMO.md](demo/DEMO.md) for
a ten-step walkthrough.

## Use it on your own log
```bash
python3 -m console --db /path/to/proxy.db                 # any K-log-schema@1 or @2 log, or older ones
python3 -m console --db a.db --db b.db --port 8100        # several logs, switch in the UI
```
The proxy can keep writing: new calls show up on the next click. The console never writes to the
log. To identify users, have your agents send `X-Agent-User` (and optionally `X-Agent-Dept`,
`X-Session-Id`) to the proxy; without it the console falls back to the hashed API key, then the agent id.

## How it works
```mermaid
flowchart LR
  A[agents] -- X-Agent-User, X-Session-Id --> P[LLM proxy] --> LLM[(LLM)]
  P -- appends --> L[(proxy.db<br/>calls · signals · admin_actions)]
  L -- read-only --> S[console server<br/>in-memory index] -- JSON API --> UI[drill-down UI<br/>+ galaxy 3D]
```
- Opens the log with SQLite `mode=ro` in autocommit, so the proxy is never blocked.
- Indexes the light columns of every call in memory (user, day, tokens, firewall level); charts never
  parse the big JSON.
- Rebuilds each session as a conversation: each call contributes only the messages it added.
- Shows the firewall layer only if the log has a `signals` table.
- Plain SVG charts, vendored Three.js, no CDN: works offline.
Details: [ARCHITECTURE.md](blueprint/ARCHITECTURE.md).

## Rebuild it from the blueprint

The code is one rendering of the specification; [`blueprint/`](blueprint/) is the system itself.

| File | What it holds |
|---|---|
| [GOAL.md](blueprint/GOAL.md) | why it exists, who it is for, what success looks like, non-goals |
| [SPEC.md](blueprint/SPEC.md) | the source of truth: components, versioned contracts and numbered requirements (R-…) |
| [ARCHITECTURE.md](blueprint/ARCHITECTURE.md) | how the parts fit, and where each requirement lives in the code |
| [PROMPTS.md](blueprint/PROMPTS.md) | the ordered prompts that built it (P-01…), plus P-REBUILD and P-VERIFY |
| [DECISIONS.md](blueprint/DECISIONS.md) | every design choice, with the alternatives and consequences |
| [ROADMAP.md](blueprint/ROADMAP.md) | milestones done and what comes next |

To regenerate the project, give a coding model the `blueprint/` folder and the **P-REBUILD**
prompt from PROMPTS.md, then run **P-VERIFY**. The tests in `tests/` cite the requirement ids
they prove and `demo/data/` holds recorded traffic, so you can tell whether the rebuild behaves
like this one. The method behind it is [Prax Systems](../prax-systems/README.md).

## Tests
```bash
python3 -m unittest discover -s tests -t .      # offline, ~2 s
python3 tools/prax_check.py . --level silver     # Prax Systems compliance
```

## Layout
```
blueprint/    GOAL · SPEC · ARCHITECTURE · PROMPTS · DECISIONS · ROADMAP (rebuild from these)
console/      store.py (read-only log + aggregates) · transcript.py (sessions as conversations) · server.py
web/          index.html · app.js (drill-down) · charts.js (SVG) · galaxy.js (Three.js) · vendor/
demo/         data/*.db.xz (recorded logs) · DEMO.md · live_replay.py
tools/        make_samples.py (builds demo/data) · prax_check.py
explainers/   index.html (animated, self-contained)
tests/        fixtures.py (logs in every schema) · test_store.py · test_server.py
```

Licence: Apache 2.0. Three.js: MIT (web/vendor/THREE-LICENSE).
