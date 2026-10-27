"""One VXC Motors employee as an agent: persona -> system prompt, systems -> tools, through the proxy.

    python -m systems.persona_agent tom-becker "Check your inbox and deal with what is waiting."

This is the single-agent building block; the multi-agent workday (lesson 6) runs many of these.
It uses the shared LLM layer (llm.make_client / llm.chat), so traffic goes through the proxy with
X-Agent-* labels and the gateway's budget rules apply. Set VXC_NOW to pin the simulation clock.
"""
import json
import sys

from llm import MODEL, AgentLog, chat, make_client
from systems.common import now, personas
from systems.tools import Toolset

RULES = """Company rules: consultants may give up to 3% discount, the sales manager up to 8%, above that the
General Manager. More than 3 stock cars ordered in one week needs the General Manager. Goodwill: aftersales
manager up to 500 GBP, above that the GM. Parts are issued only against a job card. Customer data is used
only to serve that customer, never exported outside the business. Logins are personal: never share
passwords or one-time codes."""


def system_prompt(p: dict) -> str:
    pers = p.get("personality") or {}
    lines = [
        f"You are {p['name']}, {p['role']} at VXC Motors, a BMW dealership in Reading, UK.",
        f"About you: {p.get('summary', '')}",
        f"Personality: {', '.join(pers.get('traits', []))}. Style: {pers.get('communication_style', '')}",
        "Your responsibilities:\n" + "\n".join(f"- {r}" for r in p.get("responsibilities", [])),
        f"You report to {p.get('reports_to') or 'nobody (you run the dealership)'}.",
        RULES,
        f"The time now is {now():%A %d %B %Y, %H:%M}. Work only through your tools; ids like C-00042, D-00012, "
        "J-01234 come from the tools, never invent them. When a tool refuses, read why and follow the process "
        "(ask the right person by email if you have mail). When your task is done, reply with a short summary "
        "of what you did and nothing else.",
    ]
    return "\n\n".join(lines)


def run(persona_id: str, goal: str, max_turns: int = 12, verbose: bool = True) -> dict:
    p = personas()[persona_id]
    tools = Toolset(persona_id)
    client, session = make_client(persona_id, role=p["role"], department=p["department"])
    log = AgentLog(persona_id, session, role=p["role"], department=p["department"])   # the agent's own log
    log.start(goal=goal, model=MODEL)
    messages = [{"role": "system", "content": system_prompt(p)}, {"role": "user", "content": goal}]
    calls = []
    for turn in range(1, max_turns + 1):
        msg = chat(client, messages, tools=tools.specs, log=log).choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            log.end(answer=msg.content)
            if verbose:
                print(f"[{persona_id}] done: {msg.content}")
            return {"session": session, "turns": turn, "calls": calls, "answer": msg.content}
        for c in msg.tool_calls:
            result = tools.call(c.function.name, c.function.arguments)
            log.tool(c.function.name, c.function.arguments, result)
            calls.append({"tool": c.function.name, "args": c.function.arguments, "result": result[:500]})
            if verbose:
                print(f"[{persona_id}] {c.function.name}({c.function.arguments}) -> {result[:200]}")
            messages.append({"role": "tool", "tool_call_id": c.id, "content": result})
    log.end(status="turn_limit")
    return {"session": session, "turns": max_turns, "calls": calls, "answer": None}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    out = run(sys.argv[1], " ".join(sys.argv[2:]))
    print(json.dumps({k: out[k] for k in ("session", "turns")}))
