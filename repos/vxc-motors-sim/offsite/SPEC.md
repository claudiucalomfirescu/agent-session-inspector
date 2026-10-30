# Off-site meeting · SPEC

Part of [vxc-motors-sim](../README.md). Prax Systems contract layer for the people identities and the
all-staff off-site. If it is not in this file, a rebuild may drop it.

## Goal
Give each of the 12 VXC Motors employee agents a stable inner life (history, job, public persona, private
soul) and show it working in one shared, observable event: an all-staff off-site held in a group chat,
where every message is an LLM call made as that person through the logging proxy.

Success looks like: (1) a reader can tell who is speaking from the message alone; (2) the General Manager's
review quotes the dealership's real figures; (3) games and votes have exact, reproducible results; (4) the
whole meeting can be replayed offline from committed files; (5) the proxy log attributes every call to the
right person.

## Glossary
- **Identity** · the four files in `people/<id>/` (resume, job, persona, soul).
- **Room** · the ordered list of events of one meeting (`transcript.jsonl`).
- **Event** · a *message* (spoken by an attendee or the facilitator, one LLM call) or a *scene* line (written
  by the meeting software: agenda changes, lunch, game results). Scene lines never come from an LLM.
- **Facilitator** · `offsite-moderator`, Hannah Brooks, an external agent defined in `offsite/moderator.md`.
- **Fact sheet** · figures computed from `data/parquet/internal/*.parquet` (`offsite/factsheet.py`).

## Components
| id | Component | Responsibility |
|---|---|---|
| C-OFF-1 | `people/` + `people/load.py` | Identity files; `load_identity(id) -> str`, `list_people() -> [id]` |
| C-OFF-2 | `offsite/agenda.py` | Setting text and segments/steps (data, not code paths) |
| C-OFF-3 | `offsite/run.py` | Walks the agenda, makes one LLM call per message, scores games, writes outputs |
| C-OFF-4 | `offsite/factsheet.py` | Business-review figures from the dealership data |
| C-OFF-5 | `offsite/replay.py` | Self-contained animated HTML replay of a run |

## Contracts
**K-people@1 · identity files.** `people/<id>/{resume,job,persona,soul}.md`, UTF-8 Markdown, each starting with
frontmatter containing at least `id: <id>` and `kind: <resume|job|persona|soul>`; `job.md` also has `title`,
`department`, `reports_to`. Ids equal `company/personas/<id>.md` ids. `load_identity` output = preamble
(name, role, "persona is public, soul is private, stay in character") + `=== YOUR PERSONA|SOUL|JOB|RESUME ===`
sections in that order, frontmatter stripped.

**Identity headers (K-agent-headers@1).** Every call: `X-Agent-User` = `X-Agent-Id` = staff id (or
`offsite-moderator`), `X-Agent-Dept` = department (`External` for the facilitator), `X-Session-Id` =
`offsite-20261031-<id>` (one session per attendee), labels `X-Agent-Event: offsite-2026`,
`X-Agent-Role: <role>`, `X-Agent-Segment: <segment id>`.

**transcript.jsonl.** One JSON object per event: `seq`, `time` (meeting clock HH:MM), `segment`, `kind`
(`message|scene`), `speaker` (staff id, `offsite-moderator` or `scene`), `name`, `role`, `text`, optional
`hidden` (data the room must not see, e.g. `{"lie": 3}`), optional `call` (`model`, `ms`, token counts or `error`).

**results.json.** `two_truths` {`turns`[{who, statements[3], lie}], `guesses`[{by, of, guess, correct}],
`detectives`, `fooled_everyone`}, `ideas`[{who,text}], `idea_list`[{n, who, title}], `votes`[{who,text}],
`vote` {`ballots`[{who, votes[]}], `ranking`[{n, who, title, votes}]}, `story`[], `commitments`[].

**CLI.** `python3 -m offsite.run --out DIR [--fake] [--seed N] [--min-gap S] [--model M] [--timeout S] [--facts FILE]`;
`python3 -m offsite.replay DIR` writes `DIR/replay.html`. Env: `OFFSITE_PRIMARY_MODEL`, `OFFSITE_FALLBACK_MODEL`,
`OFFSITE_MIN_GAP_S`, plus the `llm/` client's `LLM_BASE_URL`, `LLM_API_KEY`.

## Requirements
- **R-OFF-001** Each of the 12 employees MUST have resume, job, persona and soul files per K-people@1, each with
  substantive content. *Check:* test lists files and sizes.
- **R-OFF-002** `load_identity` MUST return the four parts in the order persona, soul, job, resume, with
  frontmatter stripped and the name present. *Check:* test.
- **R-OFF-003** The runner MUST run the segments in agenda order and record each event with its segment. *Check:* test.
- **R-OFF-004** Every employee and the facilitator MUST speak at least once; the facilitator opens the meeting.
  *Check:* test.
- **R-OFF-005** In "two truths and a lie", each player's chosen lie MUST be hidden from the room (removed from
  the message, kept in `hidden`) and guesses MUST be scored by the software, including the first player
  guessing the last. *Check:* test.
- **R-OFF-006** Brainstorm votes MUST ignore votes for one's own idea and anything not on the list, at most two
  per voter; the ranking MUST equal the count of valid votes. *Check:* test.
- **R-OFF-007** A run MUST write transcript.jsonl, transcript.md, results.json, factsheet.json and meta.json,
  and the replay MUST be a single HTML file that needs no network. *Check:* test.
- **R-OFF-008** Every live call MUST go through the proxy with the identity headers above, so the proxy log
  attributes it to the speaker. *Check:* `proxy.db` of the recorded run: one session per attendee.
- **R-OFF-009** The General Manager's review steps MUST receive the fact sheet and be told to quote only it.
  *Check:* read the review messages against `factsheet.json`.
- **R-OFF-010** A failed or empty call MUST NOT stop the meeting: up to 3 attempts, then a scene line says the
  message did not come through. Free model first; after 2 consecutive free failures the paid fallback is used
  for the next 15 calls, then one probe of the free model (a failed probe switches back at once). Calls start at least `--min-gap` seconds apart (default 20 s = 3 per minute).
- **R-OFF-011** Each message's model output MUST be cleaned: reasoning blocks, a leading "Name:" and wrapping
  quotes removed; a trailing `NEXT:` line removed from the text and used only to pick speakers.
- **R-OFF-012** The replay MUST play events in order with play/pause/step/speed/show-all, light and dark themes,
  and show everything at once under `prefers-reduced-motion`.

## Out of scope
Tools during the meeting (no CRM lookups mid-chat); private side chats; memory of the off-site in later
workdays (see roadmap idea in DECISIONS).
