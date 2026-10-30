# Decisions · llm-proxy-firewall

Decisions D-001…D-013 of llm-proxy-log apply here unchanged (this repo is a standalone copy of it).
Entries dated 2026-10-30 were taken autonomously overnight within the user's answers of that evening
and are flagged for review.

| Id | Date | Decision | Why | Alternatives | Decided by |
|---|---|---|---|---|---|
| D-101 | 2026-10-27 | On block, the proxy answers as the LLM with a normal chat completion and drops the request upstream. | Agents need no special error handling; nothing sensitive reaches the provider. | Return an HTTP error; forward and only log. | user (learning project brief) |
| D-102 | 2026-10-27 | Three levels: info, warning, block; 3 warnings on a topic in a session escalate to block. | Most findings are mentions, not breaches; repeated probing should still end the session. | Block/allow only. | user + agent |
| D-103 | 2026-10-28 | An LLM intent check runs only when a rule fired, reads the author's stance, may raise any level, may lower co-occurrence findings and refusals, never request-side keywords or `hard` rules. | Words alone over-block refusals ("I can't share passwords"); an LLM alone is slow and costly on every call. | LLM on every call; rules only. | agent, reviewed by user in the learning project |
| D-104 | 2026-10-30 | Repo 2 is a full standalone copy of repo 1 plus the firewall. | User answer 4a. | Depend on repo 1. | user |
| D-105 | 2026-10-30 | Generic demo policy for Brightleaf Software (customer data leak, credential sharing, confidential leak, harassment); dealership topics (discount fraud, competitor poaching, approval grounding) stay with vxc-motors-sim via `FIREWALL_TOPICS`. | Repo must stand alone and not look like a car dealership; the engine is unchanged. | Ship the VXC topics. | agent, review |
| D-106 | 2026-10-30 | `organization:` in the topics file names the company in the classifier prompt (was hard-coded "VXC Motors"). | Generic engine. | Hard-coded text. | agent |
| D-107 | 2026-10-30 | Grounding layer kept but optional (only with a `grounding:` section). | It is valuable for systems with approval records (the dealership) and meaningless without them. | Remove it. | agent, review |
| D-108 | 2026-10-30 | `signals` and `admin_actions` gain a `user` column (K-log-schema@2). | CONTRACTS.md; the console groups findings by user. | Join through calls. | methodology thread + agent |
| D-109 | 2026-10-30 | No agents exempt by default (`FIREWALL_EXEMPT_AGENTS` empty; it was `console-summarizer` in the learning project). | Nothing in this repo needs an exemption. | Keep the old default. | agent |
| D-110 | 2026-10-30 | Topic option `llm_max_level`; harassment capped at warning for the LLM alone. | In the first live recording the classifier turned every warning into a block, including an insult about a customer; rudeness should be flagged, and only the threat rule should close a session. | Rewrite the classifier prompt; accept LLM blocks. | agent, review |
| D-111 | 2026-10-30 | The recorded demo used `z-ai/glm-5.3-flash` for the agents and the intent check. | The free model was hanging that evening; GLM costs a fraction of a cent for the whole week. | Wait for the free model. | agent, review |
| D-112 | 2026-10-30 | Offline demo runs the firewall with rules only (`FIREWALL_INTENT=heuristic`). | The fake LLM cannot judge intent; pretending it can would mislead. | Script fake verdicts. | agent |
| D-113 | 2026-10-30 | Rule id `cred-ask-or-offer` renamed `cred-request-or-offer`. | Its name contains "sk-or-", which the shipped-data secret scan (R-042) rightly refuses; keeping the scan strict matters more than the name. | Loosen the scan. | agent |
| D-114 | 2026-10-30 | Grounding reads JSON objects with a brace-balanced scanner (`_json_objects`) instead of a flat regex. | Bug found by the vxc-motors-sim thread: approvals inside nested tool results (a mail_read list) were missed. | Leave it, since grounding is off here. | vxc thread + agent |
