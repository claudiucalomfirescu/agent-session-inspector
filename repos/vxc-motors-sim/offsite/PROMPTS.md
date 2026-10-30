# Off-site meeting · PROMPTS (the recipe)

Ordered prompts that rebuild `people/` and `offsite/` from an empty folder inside vxc-motors-sim. Every prompt
assumes the model first reads [SPEC.md](SPEC.md) and `company/personas/*.md`.

## P-01 · Identities
**Goal:** `people/<id>/{resume,job,persona,soul}.md` for the 12 staff. **Delivers:** R-OFF-001.
**Prompt:**
> Read company/personas/*.md and company/README.md (business rules). For each employee write four files per
> K-people@1. Resume: profile, experience consistent with the CV table, with 1-3 concrete achievements per role,
> education, skills, a one-line quote from a former boss. Job: purpose, responsibilities, decision rights (use
> the discount/goodwill/stock thresholds), KPIs, who they work with, systems. Persona: 5-7 bullets on how they
> behave in public at work, including how they write in chat, with a sample line in their voice. Soul: values,
> what they are looking for, when they are happy, what worries them, one private truth. For the three monitored
> risk personas (Tom: discount fraud, James: customer data, Mark: credential sharing) add an "Inner tension"
> section that explains the temptation humanely, and say what makes it weaker. Keep each file under 40 lines.
> Make the twelve people distinct from each other and give them relationships (who mentors whom, who rivals whom).
**Done when:** `python3 -m people.load` lists 12 people at roughly 1,000 tokens each.

## P-02 · Loader
**Goal:** `people/load.py`. **Delivers:** R-OFF-002.
> Write a stdlib module with list_people(), read_part(), name_and_role() (from company/personas frontmatter, fall
> back to the resume heading) and load_identity() returning the K-people@1 block.

## P-03 · Agenda, facilitator and fact sheet
**Goal:** `offsite/agenda.py`, `offsite/moderator.md`, `offsite/factsheet.py`. **Delivers:** R-OFF-009.
> Write the off-site agenda as data: welcome; two truths and a lie; business review (3 GM messages with the fact
> sheet, then 4 Q&A pairs picked by the facilitator with a NEXT: line); brainstorm (one IDEA each), vote (VOTES:
> two numbers), top 3, GM response; lunch scene; story chain (one sentence each); commitments (COMMIT/THANKS);
> GM and facilitator close. Each step carries the exact instruction the speaker gets. Write a facilitator
> identity (external, neutral, keeps time, invites quiet people, ends hand-overs with NEXT: ids). Compute the
> fact sheet with DuckDB from data/parquet/internal: units by salesperson and month, average discount, deals
> over 8%, invoiced net by kind, unpaid invoices, job cards and warranty share, jobs by technician, leads by
> status, lost reasons, lead sources, stock in hand.

## P-04 · Runner
**Goal:** `offsite/run.py`. **Delivers:** R-OFF-003…R-OFF-008, R-OFF-010, R-OFF-011.
> Implement the runner per SPEC: one LLM call per message via llm.make_client/chat through the proxy with the
> identity headers; system = identity + setting + roster (+ fact sheet for GM review steps); user = segment
> title, last 40 room events, the instruction. Parse the game formats tolerantly, hide the lie, score guesses
> and votes in code, post results as scene lines. Free model first, paid fallback after two failures, 3 calls
> per minute, 90 s timeout, ask for low reasoning effort. Provide --fake with deterministic canned answers.

## P-05 · Replay
**Goal:** `offsite/replay.py`. **Delivers:** R-OFF-012.
> Build a single self-contained HTML replay: agenda rail with progress, chat column with avatars
> (company/avatars, embedded as data URIs), an oval table with seats that light up and a speech bubble,
> an icebreaker board and a vote board with animated bars, play/pause/step/speed/show-all, light/dark tokens,
> reduced-motion support, no network.

## P-06 · Tests, run, record
> Write offline tests (tests/test_offsite_people.py) naming the R-ids. Then start the proxy with logging to
> offsite/runs/<date>/proxy.db, run the meeting live, build the replay and commit the run folder.

## P-REBUILD
> You are given GOAL (top of SPEC.md), SPEC.md, these PROMPTS and the people/*.md files. Rebuild offsite/ and
> people/load.py in <language>, keeping every contract in SPEC.md (file formats, headers, CLI). Reuse the
> identity Markdown files as they are. Do not copy the old code.

## P-VERIFY
> Run the offline tests and a --fake run against the rebuild, then a short live run (first two segments).
> Report each R-OFF id as pass/fail with evidence (test name, file, or transcript line).
