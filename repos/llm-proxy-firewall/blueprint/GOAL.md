# Goal · llm-proxy-firewall

## Pitch
The same logging proxy as llm-proxy-log, plus a firewall that reads every conversation between your
agents and the LLM, flags policy breaches, and can close a session by answering in the LLM's place.

## The problem
Once staff work through AI agents, the agent is where policy gets broken: a customer list pasted
into a chat "for my side project", a password typed in clear text, an insult drafted into an email,
the roadmap sent to a recruiter. The LLM provider sees all of it but enforces nothing of yours, and
each agent would need its own checks. A log alone tells you afterwards; it does not stop the
request or tell an administrator in time.

## Who it is for
- Primary: a team that runs LLM agents for staff and needs a first line of defence plus an audit
  trail (who tried what, what was blocked, who unblocked it).
- Secondary: people learning how content inspection on LLM traffic works and where it fails
  (keywords, co-occurrence rules, an LLM judge, the author's stance).

## Success looks like
1. A fresh clone shows a recorded week of a four-person team with info, warning and block events in
   the dashboard, with no API key (`python3 dashboard/server.py --demo`).
2. A blocked request never reaches the provider; the agent gets a normal-looking answer that says
   the session is closed and gives a reference an administrator can look up.
3. Every finding is explainable: topic, rule or detector, what matched, the LLM's rationale.
4. The policy is a YAML file a non-programmer can read and change; nothing about the demo company is
   hard-coded.
5. Everything llm-proxy-log promises still holds (same tests), and the log stays readable by
   llm-session-console (K-log-schema@2 only adds).

## Non-goals
- Guaranteed prevention. Regexes and an LLM classifier miss paraphrases and misjudge intent; this is
  a tripwire with an audit trail.
- Redacting or rewriting content on the fly (it notes, warns, or blocks the whole turn).
- A full admin console (llm-session-console shows the findings in depth; here: small dashboard + HTTP
  admin routes).
- Authentication of agents or administrators beyond an optional shared admin token.

## Related systems
- **Base:** llm-proxy-log (this repo is a standalone copy of it plus the firewall).
- **Downstream:** llm-session-console reads K-log-schema@2 (`signals`, `admin_actions`) and tests
  against `demo/data/demo.db`.
- **Siblings:** vxc-motors-sim vendors this proxy with its own topics file (dealership policies).
