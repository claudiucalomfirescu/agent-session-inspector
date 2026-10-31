# Demo · llm-session-console

## Recorded (no key, 1 minute)
```bash
python3 -m console          # first run unpacks demo/data/*.db.xz (~1 MB -> ~180 MB), then:
# open http://127.0.0.1:8095/
```
What you should see: four weeks of VXC Motors traffic (5–29 Oct 2026): ~4,400 LLM calls, ~1,100
sessions, 27 users (12 employees, simulated customers, the BMW desk), with firewall findings.

## The demo logs
| Log (picker top right) | What it is | Schema |
|---|---|---|
| `vxc-4-weeks` (default) | VXC Motors, a BMW dealership whose 12 employees are AI agents. Wed 28 and Thu 29 Oct are two **real recorded workdays** (nemotron via OpenRouter, every call genuine). The 17 earlier days are **rebuilt from those real sessions**: a seeded sample copied onto earlier dates with new session ids (`labels.replay_of` names the original). Volumes vary by weekday, Priya is on holiday the week of 12 Oct, 14 Oct has an incident cluster. | @2 (with firewall) |
| `vxc-recorded-day` | The first recorded workday exactly as the learning project's proxy wrote it, before `calls.user` existed: users come from `X-Agent-Id`. | legacy |
| `vxc-agents-tools-day` | The reworked VXC Motors sim (repos/vxc-motors-sim, 31 Oct 2026): employees are agents, enterprise apps are tools backed by local services; 506 real calls, 104 sessions, 9 blocks. Users come from the `user` label. | @2 |
| `brightleaf-team-week` | The llm-proxy-log demo team (maya engineering, omar support, lena sales, raj ops), 125 real calls over a week. | @1 (no firewall) |
| `brightleaf-firewall-week` | The same team behind llm-proxy-firewall: 109 agent calls plus 21 intent checks by the firewall itself (system traffic, hidden by default), 50 findings, 10 admin actions. | @2 |

## Live traffic
With a real proxy, point the console at its log while it runs; new calls appear on the next click:
```bash
python3 -m console --db ../llm-proxy-firewall/logs/proxy.db
```
Without a proxy or key, replay a recorded day into a fresh file at 20× speed:
```bash
python3 demo/live_replay.py --speed 20 &
python3 -m console --db demo/data/.cache/live.db --port 8096
```

## Ten-step walkthrough
1. **All traffic.** KPI tiles, the over-time chart, users, departments, models and the weekday × hour
   heatmap. The breadcrumb says users come from `X-Agent-User`. (R-005, R-007, R-021)
2. **Switch the chart metric** to *tokens*, then *firewall*; toggle **Week**. (R-006, R-024)
3. **Click the 14 Oct bar.** The range narrows to that day (chip 📅 in the breadcrumb), the chart
   switches to hours. Remove the chip with ✕. (R-021, R-024)
4. **Click `james-okafor`** in the users table: his days, the tools the LLM called for him
   (`crm_*`, `mail_*`…), his hours, and his sessions. Filter sessions to **≥ block**. (R-008, R-009)
5. **Open a blocked session.** Each call shows only what it added (the instruction, the tool results),
   then the LLM's answer; the blocked call shows the proxy answering *as the LLM*, the findings that
   triggered it (keyword, intent classifier with confidence) and the firewall's block action.
   Click **{ } raw** for the exact JSON. (R-010, R-011)
6. Use the breadcrumb to go back up to the user, then to **All traffic**. Every view is a URL you can
   bookmark or share. (R-021)
7. **Firewall tab.** Findings over time, the topic × level matrix (click a cell), detectors, every
   finding and admin action; click a row to land on that call inside its session. (R-012)
8. **Galaxy 3D tab.** Stars are users grouped by department, planets their sessions, red/amber halos
   flag warnings and blocks. Drag, zoom, click `tom-becker`, then one of his flagged sessions in the
   panel: the orbits stop, the session's calls appear as moons; click a moon, then *Open this call in
   drill-down*. Esc returns to the overview. (R-013, R-022)
9. **Switch the log** to `brightleaf-team-week`: no firewall tiles; the Firewall tab explains that a
   K-log-schema@1 log has no firewall tables. Switch to `vxc-recorded-day`: users now come from
   `X-Agent-Id`. (R-002, R-003, R-023)
10. **Search** "discount" from the header. Toggle the ◐ theme; with the OS set to reduce motion the
    galaxy stops spinning. Everything above works with the network unplugged. (R-014, R-102, R-104)

## The demo cast (vxc-4-weeks)
Victor Hale (general manager), Maria Santos (reception), Daniel Reed, Tom Becker, Sofia Marin (sales),
James Okafor, Elena Popescu, Nina Kovac (service), Lucas Meyer, Priya Nair (workshop), Mark Doyle
(parts), Aisha Rahman (finance) — each an agent whose only channel is the LLM; plus simulated
customers and the BMW dealer desk. The incidents seeded in their scripts (a PII leak to a personal
address, discount fraud, poaching for a competitor, harassment, credential sharing) are what the
firewall catches.
