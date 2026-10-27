# VXC Motors · Agent Session Inspector — master plan

This repository is a learning project. It starts from one agent talking to an LLM and ends with a
whole simulated company, **VXC Motors** (a single-site BMW dealership with 12 staff), whose AI agents
talk to the LLM through a proxy that logs, inspects and, when needed, blocks their conversations,
while an administrator watches it all from a console.

Every step is a **lesson**. Each lesson has its own page under [`docs/lessons/`](lessons/) with the
same five parts: **summary**, **explanation**, **learnings**, **flowchart** (Mermaid) and a link to
its **visualization** (a self-contained HTML page under [`viz/`](../viz/), also published as an
artifact). The template is [`docs/templates/LESSON_TEMPLATE.md`](templates/LESSON_TEMPLATE.md).

## Lesson sequence

| # | Lesson | What it adds | Status | Page |
|---|---|---|---|---|
| 1 | Agent → OpenRouter | One agent with tools, calling the LLM directly in a loop | ✅ done | [01](lessons/01-agent-to-openrouter.md) |
| 2 | Agent via proxy | A pass-through proxy holds the real key; the agent only changes its base URL | ✅ done | [02](lessons/02-agent-via-proxy.md) |
| 3 | Proxy logging | Every exchange recorded in SQLite and readable turn by turn | ✅ done | [03](lessons/03-proxy-logging.md) |
| 3b | LLM gateway | Shared budget rules in the proxy: rate limit, backoff, daily-cap fallback, spend cap, replay cache | ✅ done | [03b](lessons/03b-llm-gateway.md) |
| 4 | Company & personas | VXC Motors: org chart, 12 personas (CV, background, illustrated avatar), Markdown + YAML as source of truth, loaded into a DB | 🔜 wave 1 | 04-company-and-personas.md |
| 5 | Mock systems & BMW portal | Internal systems (CRM, service workshop, inventory, parts, finance) in DuckDB + Parquet with history from Jan 2026, and an external BMW portal for ordering cars and parts | ⏳ wave 2 | 05-mock-systems.md |
| 6 | Multi-agent workday | One agent per persona, each with its tools, running a simulated workday through the proxy; each agent keeps its own client-side log | ⏳ wave 2 | 06-multi-agent-workday.md |
| 7 | Admin console | Web console over the logs: company → department → person → session → conversation, with LLM-written (cached) or rule-based summaries at every level, alert rail, block / unblock / note | ✅ done | [07](lessons/07-admin-console.md) |
| 8 | Sensitive topics | Five topic definitions detected by keywords **and** intent, levels info / warning / block, signals stored in their own table and highlighted in the console | ✅ done | [08](lessons/08-sensitive-topics.md) |
| 9 | Proxy firewall | Deep session inspection in the proxy: on *block* the proxy answers the agent itself, as if it were the LLM, and never forwards upstream; admin actions logged in their own table; agents keep their own log | ✅ done | [09](lessons/09-proxy-firewall.md) |
| 10 | Mission control, replay, demo | Live map of agent traffic (agent ↔ proxy ↔ LLM, agent ↔ systems, firewall flashes), replay of any log window at up to 900×, static export with a baked log snapshot, five-minute demo script | ✅ done (guided in-page tour: wave 5) | [10](lessons/10-mission-control.md) |
| side | Walkable dealership | Three.js HTML model of the showroom and workshop; click a person to open their persona | ✅ done | [side](lessons/side-3d-dealership.md) |

Status key: ✅ done · 🔜 in progress · ⏳ planned.

## Architecture (target)

```mermaid
flowchart LR
  subgraph Company["VXC Motors agents (one per persona)"]
    A1[Receptionist]
    A2[Sales]
    A3[Service advisor]
    A4[Parts]
    A5[...]
  end
  subgraph Systems["Mock systems (DuckDB + Parquet)"]
    CRM[(CRM)]
    WS[(Workshop)]
    INV[(Inventory)]
    BMW[[BMW portal]]
  end
  Company -- tool calls --> Systems
  Company -- "chat completions<br/>X-Agent-* headers, dummy key" --> P
  subgraph P["Proxy :8080"]
    FW{{Firewall<br/>info / warning / block}} --> GW[Gateway<br/>rate limit · fallback · spend cap · cache]
  end
  GW -- real key --> OR[(OpenRouter<br/>nemotron :free / glm-5.3-flash)]
  P --> LOG[(logs/proxy.db<br/>calls · signals · admin_actions)]
  LOG --> CON[Admin console<br/>+ mission control]
  Company -. own client logs .-> CL[(agent logs)]
```

## Decisions

| Topic | Decision |
|---|---|
| Company | VXC Motors, single-site BMW dealership, 12 staff, two business areas (sales, service) plus admin and supply chain |
| LLM | `nvidia/nemotron-3.5-super-vl:free`; `z-ai/glm-5.3-flash` **only** once the free daily cap is used up |
| Budget | ≤ 16 req/min across all agents, 1,000 free req/day (account-wide), paid fallback capped at **$3** (see lesson 3b) |
| Proxy log | SQLite `logs/proxy.db`: `calls`, `signals` (what the firewall saw), `admin_actions` (what was done, by whom); schema in `proxy/logstore.py` |
| Detection | Keyword and co-occurrence rules in `proxy/firewall_topics.yaml`; an LLM intent check through the gateway only when a rule fired, skipped when the free budget is tight; the LLM can raise a level or dismiss a co-occurrence finding, never a keyword finding |
| Agent logs | Each agent writes `logs/agents/<agent_id>.jsonl` via `llm.AgentLog` (`chat(..., log=log)`) |
| Business data | DuckDB over Parquet files |
| Personas | Markdown with YAML frontmatter is the source of truth; loaded into the DB |
| Agent identity | `llm.make_client(agent_id, role=…, department=…)` sends `X-Agent-Id`, `X-Session-Id`, `X-Agent-*` labels; the proxy logs them as `labels` and strips them before forwarding |
| Sensitive topics | Customer PII leak, discount fraud, competitor poaching, harassment, credential sharing |
| Block behaviour | Proxy replies to the agent as if it were the LLM, with a "conversation blocked" message, and the session is not forwarded |
| Visualizations | Self-contained HTML under `viz/`, published as artifacts; log snapshots embedded with `viz/embed_log.py` |

## How the work is organised

- **Branches**: `main` is untouched. `vxc-motors` is the integration branch. Each piece of work uses
  its own feature branch off `vxc-motors`, commits and pushes often, and merges back when done.
- **Waves**: 1) foundation, docs, company and personas, 3D dealership · 2) mock systems and
  multi-agent runner · 3) sensitive topics and firewall · 4) console, mission control, replay ·
  5) demo tour, docs polish, final run.
- **Every agent uses the shared LLM layer** (`llm/`) and goes through the proxy, so the budget rules
  hold no matter how many agents run.
- **Each lesson is finished** when its page has all five parts, its visualization is in `viz/` and
  published, and this table says ✅.

## Visualizations so far

| Viz | Lesson | Repo | Published |
|---|---|---|---|
| Session sequence diagram (A2) | 3 | [`viz/sequence.html`](../viz/sequence.html) | https://claude.ai/artifact/6jZ5vsA2nbnXobh5YEwvMq |
| Topology map, steps 1–3 (B1) | 1–3 | [`viz/topology.html`](../viz/topology.html) | https://claude.ai/artifact/UXRUbzzXEv6XJGRBCA3ubP |
| Blocked session trace | 8–9 | [`viz/firewall.html`](../viz/firewall.html) | https://claude.ai/artifact/4uS3cdhTTx35MdJNMibbtF |
| Admin console (demo day) | 7 | [`viz/console.html`](../viz/console.html) | https://claude.ai/artifact/4qKXJBDNUJXZNcUJKNvipu |
| Mission control, replay (demo day) | 10 | [`viz/mission-control.html`](../viz/mission-control.html) | https://claude.ai/artifact/WbX69o9po7W8Dx9Pjx1iT4 |
| Walkable 3D dealership | side | [`viz/dealership/index.html`](../viz/dealership/index.html) | https://claude.ai/artifact/UVbFvg1v9YcCVqYUzNCivm |
