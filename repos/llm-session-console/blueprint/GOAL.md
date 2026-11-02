# Goal · llm-session-console

## Pitch
Open the log your LLM proxy wrote and, in three clicks, go from "all our agents this month" to the
one message that tripped the firewall last Tuesday.

## The problem
When a team routes its agents through a logging proxy (llm-proxy-log, llm-proxy-firewall), every
conversation lands in a SQLite file. That file is complete but unreadable: each row is one HTTP call
carrying the *whole* conversation so far, thousands of rows a day, JSON inside JSON. The questions
people actually ask — who uses the LLM, how much, when, for what, and what did the firewall catch —
need a SQL session and a lot of patience. The earlier console in this project showed one day as a
company org chart; it did not let you move between the big picture and the detail, or across days.

## Who it is for
- Primary: the person running the proxy for a team (an admin, a lead, a security reviewer) who needs
  to understand usage and investigate incidents.
- Secondary: a learner or presenter who wants to *see* multi-agent traffic (the 3D galaxy view).

## Success looks like
1. A fresh clone shows four weeks of real multi-agent traffic within one minute: `python3 -m console`,
   no API key, no network, no install beyond Python 3.10+.
2. From the global view a reader reaches any single LLM call in at most four clicks
   (all → user → day → session → call), and every step has a breadcrumb back.
3. Per user and globally: calls, sessions, tokens, active users, by day or week, plus a weekday × hour
   heatmap; firewall findings (info / warning / block) wherever the log has them.
4. A session reads like a conversation (each message once), with firewall findings and admin actions
   on the message they concern.
5. Pointing it at a live proxy log shows new calls without restarting, and never slows the proxy down.

## Non-goals
- Writing to the log, blocking or unblocking sessions (the firewall's admin API does that; see
  llm-proxy-firewall).
- Authentication or multi-tenant hosting: it binds to localhost and is for the person who already has
  the log file.
- Calling an LLM (no summaries, no classification): the console must work offline.
- Running agents or generating traffic (vxc-motors-sim and the proxy repos' demo teams do that).

## Related systems
- **llm-proxy-log** owns `K-log-schema@1` and `K-agent-headers@1`: what we read.
- **llm-proxy-firewall** owns `K-log-schema@2` (adds `signals`, `admin_actions`): the firewall layer.
- **vxc-motors-sim** produces the richest logs (12 employee agents and their customers).
- **prax-systems** is the method this repo follows.
