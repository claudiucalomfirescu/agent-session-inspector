# Goal · Prax Systems

## Pitch
A way of building multi-part systems so that the specification, not the code, is what you keep, and
any future model can rebuild the code from it.

## The problem
Our earlier methods (Prax Analytics for pipelines, Prax App for apps) assume one shape: a linear
data flow, or one UI over one backend. The agent-session-inspector project grew into something
else: agents, a proxy, a firewall, local enterprise services, a console, recorded traffic. The
behaviour that matters lives *between* parts, much of it is non-deterministic (LLMs), and we want to
split it into several repos that can be recombined later. Code written today by today's model will
be out of date in months; the intent and the contracts will not. Without a method, the knowledge of
*why* and *what exactly* lives only in chat history and is lost.

## Who it is for
- The project owner, who wants to publish small repos that strangers can clone, understand, run and rebuild.
- Future coding models asked to regenerate a system in a new language.
- Readers who learn from the repos (explainers, demo data, decisions).

## Success looks like
1. Every repo in the ecosystem has GOAL, SPEC (with numbered R-ids and versioned contracts), PROMPTS (with P-REBUILD and P-VERIFY), ARCHITECTURE, ROADMAP, DECISIONS, demo data and an animated explainer.
2. `tools/prax_check.py <repo> --level silver` passes for each published repo.
3. A fresh clone of any repo shows the system working from recorded demo data, with no API key.
4. Contracts shared between repos (log schema, headers) are defined once by an owner and cited by version by consumers.
5. At least one repo is rebuilt from its prompts by a different model or language (Gold), on the roadmap.

## Non-goals
- Not a framework or a code generator; it is files, templates and a checker.
- Not a replacement for Prax Analytics or Prax App; a system may contain both.
- No heavyweight process: one person and a model should be able to follow it in a night.
