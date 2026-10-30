# Rebuild prompts · llm-session-console

These prompts rebuild this repository from an empty folder. They are the prompts this rendering was
built from on 2026-10-30, tidied so a future model can replay them. They say *what* and cite the
spec; they say *how* only where the how is a contract (routes, JSON shapes, identity rules).

**Always give the model first:** `prax.yaml`, `GOAL.md`, `SPEC.md`, and for later steps the files it
already produced. Keep `demo/data/*.db.xz` and `tests/fixtures.py`: they are the proof.

## P-REBUILD — one shot
```text
You are rebuilding llm-session-console, described in GOAL.md and SPEC.md (attached); its current
shape is in ARCHITECTURE.md. Target language/runtime: <LANGUAGE / RUNTIME>.

Build a local, read-only web console over an LLM proxy's SQLite log:
- Implement every requirement R-0xx and R-1xx in SPEC.md. The API K-console-api@1 (routes, query
  parameters, JSON field names) and the identity rules in SPEC §3.3 are not negotiable; internal
  structure is yours.
- Read logs in the shapes K-log-schema@1 and @2 and the legacy shape (tests/fixtures.py builds all
  three). Never write to a log and never hold a read transaction open.
- The UI is a single page with hash routes (#/, #/u/<user>, #/s/<session>?call=, #/fw, #/galaxy,
  #/search) where every filter is in the URL; charts are plain SVG; the galaxy uses a vendored copy
  of Three.js. No CDN, no network at runtime.
- With no arguments the program serves demo/data/*.db.xz (unpack them to demo/data/.cache/).
- Port tests/ to <LANGUAGE> keeping every test name and the R-id it proves; keep demo/data/ as is.
Finish with a README quickstart that works offline from demo/data/. Report which R-ids you could not
satisfy and why.
```

## P-VERIFY
```text
Against the rebuild:
1. Run the ported tests (and `python3 tools/prax_check.py . --level silver`).
2. Start the server with no arguments and walk demo/DEMO.md steps 1–10 in a browser; take a
   screenshot at each step.
3. Point it at the owners' fixtures if present (../llm-proxy-log/demo/data/demo.db,
   ../llm-proxy-firewall/demo/data/demo.db).
Produce a table of every R-id in SPEC.md with pass / fail / manual and the evidence (test name or
screenshot). Do not change SPEC.md to make a test pass.
```

## Step-by-step prompts
Replay these in order if a one-shot rebuild drifts. Each step ends green before the next starts.

### P-01 · Fixtures and the read-only store
- **Goal:** a `Store` that opens any log shape read-only and resolves users, depts and sessions.
- **Delivers:** R-001, R-002, R-003, R-004, R-015, R-016, R-017
- **Read first:** GOAL.md, SPEC.md §1, §3
- **Done when:** `python3 -m unittest tests.test_store -k R001 -k R002 -k R003 -k R004 -k R015 -k R016 -k R017`

```text
Read GOAL.md and SPEC.md. Write tests/fixtures.py that builds three tiny logs (legacy, K-log-schema@1,
@2) with fixed content: 4 users (maya engineering, omar support, lena sales, plus the system agent
"firewall"), 6 calls over 26 and 28 Oct 2026, one call without a session id, one tool-calling session,
one blocked session with signals and admin actions, one session-level escalation and one admin note.
Then write console/store.py: open the log with SQLite URI mode=ro and autocommit; detect columns;
copy the light columns of every call into an in-memory table using the identity rules of SPEC §3.3;
load signals/admin_actions with a resolved user; refresh incrementally by id when the file changes.
Write the R-001…R-004, R-015…R-017 tests from SPEC §4 and make them pass.
```

### P-02 · Aggregates
- **Goal:** every number the UI shows, computed in SQL over the light index.
- **Delivers:** R-005, R-006, R-007, R-008, R-009, R-012, R-013, R-014
- **Read first:** SPEC.md §3 (K-console-api@1 shapes), §4
- **Done when:** `python3 -m unittest tests.test_store`

```text
Add to the store: overview (totals with firewall counts and blocked calls), series by day / week
(Monday) / hour with zero-filled days, a weekday x hour heatmap, users with per-day counts and
firewall counts, one user's detail with the tools the LLM called for them (count tool_calls in the
responses), sessions with title and worst level and a level filter, firewall findings with topic x
level, detectors and admin actions, compact galaxy nodes, and substring search with a snippet.
Every function takes the shared filter (from, to, user, dept, system). Field names exactly as in
SPEC K-console-api@1. Add the tests from SPEC §4 for these R-ids.
```

### P-03 · Transcript
- **Goal:** a session reads like a conversation.
- **Delivers:** R-010, R-011, R-103
- **Read first:** SPEC.md R-010, K-openai-chat@1
- **Done when:** `python3 -m unittest tests.test_store -k R010 -k R011 -k R103`

```text
Write console/transcript.py. Each call's request repeats the whole conversation; for each call keep
only the messages added since the previous request plus its answer (if the client rewrote history,
show all but the system prompt). Parse responses stored as JSON or as an SSE stream (reassemble
content and tool_calls by index). Attach signals and admin actions to their call_id; keep the others
as session-level. Return system prompt, tool names offered, steps, totals. Add the raw call view.
```

### P-04 · Server and demo data
- **Goal:** `python3 -m console` serves the API and the bundled demo logs offline.
- **Delivers:** R-018, R-019, R-020, R-101
- **Read first:** SPEC.md §3 CLI, ARCHITECTURE.md Runtime
- **Done when:** `python3 -m unittest tests.test_server`

```text
Write console/server.py with the standard library only: ThreadingHTTPServer on 127.0.0.1:8095,
GET /api/* per K-console-api@1 (db= selects among several --db logs; unknown -> 404; exceptions ->
500 JSON), static files from web/ with no path escape, refresh a log when its mtime (or -wal) changes.
Without --db, unpack demo/data/*.db.xz to demo/data/.cache/ (only when newer) and serve them.
Write tools/make_samples.py to build the demo logs from two recorded proxy logs: the real days as
recorded, and a 4-week history rebuilt deterministically from those real sessions (new session ids,
shifted times, labels.replay_of), compressed with xz. Write demo/live_replay.py.
```

### P-05 · Drill-down UI
- **Goal:** the 2D console.
- **Delivers:** R-021, R-023, R-024, R-104
- **Read first:** GOAL.md success criteria, SPEC.md R-021…R-024, the API output of the demo log
- **Done when:** DEMO.md steps 1–7 and 9–10 work in a browser with no console errors

```text
Write web/index.html, app.css, charts.js and app.js, no framework and no CDN. Header: view tabs
(Drill-down, Firewall, Galaxy 3D), log picker, date range (all / 7 / 14 / 30 days / custom), Day/Week
toggle, "system traffic" checkbox, message search, theme toggle. Breadcrumb with removable filter
chips and the identity source. Views: global (KPI tiles; stacked bars over time with a metric picker
and clickable bars that narrow to that day or week; sortable users table with sparkline and firewall
badges; departments; models; weekday x hour heatmap), user (same charts for one user, tools the LLM
called, sessions table filterable by level), session (conversation steps, tool calls with arguments,
findings and admin actions on their call, raw JSON dialog, ?call= scrolls to and highlights a call),
firewall (level tiles, findings over time, topic x level matrix, detectors, findings and actions
tables opening the session at the call; an explanation when the log has no firewall), search.
Light and dark via CSS variables; respect prefers-reduced-motion.
```

### P-06 · Galaxy 3D
- **Goal:** the same hierarchy in a 3D space you can fly through.
- **Delivers:** R-013, R-022
- **Read first:** SPEC.md R-022
- **Done when:** DEMO.md step 8 works; no console errors

```text
Write web/galaxy.js as an ES module using the vendored three.module.min.js and OrbitControls (import
map). Users are stars grouped by department around a central "LLM proxy" glow, size by calls,
colour by department, halo red/amber for blocks/warnings, labelled. Sessions are planets on tilted
orbits around their user, size by tokens, colour by worst firewall level. Hover shows a tooltip;
click a star flies the camera to it and opens a side panel (stats, flagged sessions, link to the
user view); click a planet stops the orbits, isolates it, loads its calls as moons coloured by
level and lists them in the panel; click a moon shows that call. Esc / Overview flies home; spin
toggle; reduced motion = no spin and instant flights. Clean up on leaving the view.
```

### P-07 · Docs, explainer, seal
- **Goal:** Prax Systems Silver.
- **Delivers:** all R-ids traced; explainer published
- **Done when:** `python3 tools/prax_check.py . --level silver` passes

```text
Write README (60-second quickstart), GOAL, SPEC, ARCHITECTURE (requirement -> code map), ROADMAP,
DECISIONS, demo/DEMO.md (10-step walkthrough citing R-ids) and explainers/index.html: one
self-contained animated page (what / problem / how a call becomes a drill-down / what you get /
replicate it) with play, pause, step and keyboard controls, light and dark, reduced motion.
```
