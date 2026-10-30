"""Run the demo team's sessions through the proxy: the traffic generator.

    python3 demo/team.py                      # every scenario once, through http://127.0.0.1:8080/v1
    python3 demo/team.py --only 3 --pace 15   # 3 scenarios, at most one LLM call every 15 s

Each scenario in demo/scenarios.json is one session: the person's task goes to their agent, the agent
calls tools until it can answer (at most --max-turns LLM calls), then any follow-up messages are asked in
the same session. Every LLM call carries X-Agent-User / X-Agent-Dept / X-Agent-Id / X-Session-Id, so the
proxy can say who asked. Needs the `openai` package and a running proxy (or use demo/run.py).
"""
import argparse
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from agents import AGENTS, COMPANY, run_tool, system_prompt, tool_specs  # noqa: E402
from client import chat, make_client  # noqa: E402


class Pacer:
    """At most one LLM call every `seconds`, so a free-tier rate limit shared with others is respected."""

    def __init__(self, seconds):
        self.seconds, self.last = seconds, 0.0

    def wait(self):
        delay = self.last + self.seconds - time.time()
        if delay > 0:
            time.sleep(delay)
        self.last = time.time()


def run_session(scenario, pacer, max_turns=4, model=None, base_url=None, out=print):
    agent_id = scenario["agent"]
    user = AGENTS[agent_id]["user"]
    person = COMPANY["people"][user]
    client, session = make_client(agent_id, user=user, dept=person["dept"], base_url=base_url,
                                  org="brightleaf", task=scenario.get("id"))
    tools = tool_specs(AGENTS[agent_id]["tools"])
    messages = [{"role": "system", "content": system_prompt(agent_id)}]
    out(f"\n== {user} -> {agent_id}  session {session}")
    for text in [scenario["task"]] + scenario.get("followups", []):
        out(f"  {user}: {text}")
        messages.append({"role": "user", "content": text})
        for _ in range(max_turns):
            pacer.wait()
            resp = chat(client, messages, tools=tools, model=model)
            msg = resp.choices[0].message
            calls = msg.tool_calls or []
            messages.append({"role": "assistant", "content": msg.content or "",
                             **({"tool_calls": [c.model_dump() for c in calls]} if calls else {})})
            if not calls:
                out(f"  {agent_id}: {' '.join((msg.content or '').split())[:200]}")
                break
            for c in calls:
                result = run_tool(c.function.name, c.function.arguments)
                out(f"    tool {c.function.name}({c.function.arguments}) -> {result[:100]}")
                messages.append({"role": "tool", "tool_call_id": c.id, "content": result})
    return session


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenarios", default=os.path.join(HERE, "scenarios.json"))
    p.add_argument("--only", type=int, help="run only the first N scenarios")
    p.add_argument("--pace", type=float, default=0.0, help="minimum seconds between LLM calls (default 0)")
    p.add_argument("--max-turns", type=int, default=4)
    p.add_argument("--model", help="model to ask for (default: LLM_MODEL or the free model)")
    p.add_argument("--base-url", help="proxy URL (default: LLM_BASE_URL or http://127.0.0.1:8080/v1)")
    a = p.parse_args(argv)
    with open(a.scenarios, encoding="utf-8") as f:
        scenarios = json.load(f)
    for i, s in enumerate(scenarios, 1):
        s.setdefault("id", f"s{i:02d}")
    pacer = Pacer(a.pace)
    sessions = []
    for s in scenarios[:a.only]:
        try:
            sessions.append(run_session(s, pacer, a.max_turns, a.model, a.base_url))
        except Exception as e:  # noqa: BLE001  one failed session should not stop the team
            print(f"  session failed: {type(e).__name__}: {e}")
    print(f"\n{len(sessions)} sessions done.")
    return sessions


if __name__ == "__main__":
    main()
