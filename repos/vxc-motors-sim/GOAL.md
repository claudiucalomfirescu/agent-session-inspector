# Goal · vxc-motors-sim

## Pitch
A whole BMW dealership, VXC Motors, where every employee is an LLM agent, every enterprise
application is a tool backed by a small real service, and every word anyone says passes through one
logging, firewalled LLM proxy.

## The problem
Companies are about to give each employee an AI agent that reads mail, updates the CRM and talks to
suppliers. Nobody can watch that yet: the traffic is spread over many agents, many tools and many
conversations, and the risky moments (a discount hidden as accessories, a customer list sent to a
friend, a password pasted into chat) look like ordinary work. People building the watching tools
(proxies, firewalls, consoles) need **realistic, repeatable agent traffic** with known incidents in
it, and they need to see *how* agents reach systems: what is an agent, what is a tool, what is
behind the tool. Toy demos with one chatbot do not show any of that.

## Who it is for
- Primary: people building or evaluating LLM gateways, session firewalls and agent-monitoring
  consoles (the sibling repos `llm-proxy-log`, `llm-proxy-firewall`, `llm-session-console`).
- Secondary: anyone learning how a multi-agent "company" works end to end: tool calling, mailboxes,
  chat, outside parties, a judgment tool backed by another agent.

## Success looks like
1. A fresh clone shows a recorded workday (sessions, emails, chats, firewall blocks) in under a
   minute, with no API key.
2. One command runs the whole day offline against a fake LLM, and the same command with a key runs
   it live through the proxy, paced to the free tier.
3. It is unambiguous what is an agent (12 employees, customers, BMW desks) and what is a tool
   (74 tools in 8 applications), and for every tool what is really behind it ([TOOLS.md](TOOLS.md)).
4. Every message between people is a tool call the LLM asked for, so the proxy log contains every
   email and chat message, and the console can attribute each call to a user and department.
5. The six staged incidents are caught by the firewall in the recorded day, and the day can be
   scored against hand-written ground truth.

## Non-goals
- Not a real dealer management system: the applications are small, deterministic and local.
- Not the proxy, firewall or console: those are sibling repos. This repo ships a copy of the proxy
  so it runs alone, but the proxy's own spec lives in `llm-proxy-firewall`.
- Not a benchmark of model quality. Agents use the free model when it answers, a cheap model when
  not; the point is the traffic and the plumbing, not the best answers.

## Related systems
- **llm-proxy-log** owns `K-agent-headers@1` (who is calling). We send it on every request.
- **llm-proxy-firewall** owns `K-log-schema@2` and `K-firewall-rules@1`. We ship our own VXC rule file
  in that format and a copy of the proxy.
- **llm-session-console** reads our recorded `demo/data/proxy.db` as rich demo data.
- We own **`K-vxc-tools@1`**: the applications as HTTP services and their tools.
