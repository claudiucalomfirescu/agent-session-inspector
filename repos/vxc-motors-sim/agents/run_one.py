"""One VXC Motors employee as an agent, on its own: persona -> system prompt, applications -> tools,
every LLM call through the proxy with X-Agent-User / X-Agent-Dept.

    python -m apps.server &                    # the applications (tools) on :8100 and :8200
    python -m agents.run_one tom-becker "Check your inbox and deal with what is waiting."

The multi-agent workday (sim/run.py) runs many of these. Set VXC_NOW to pin the simulation clock.
"""
import json
import sys

from agents.staff import StaffAgent
from agents.toolclient import wait_ready


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    wait_ready(10)

    def show(kind, **data):
        if kind == "tool":
            print(f"[{sys.argv[1]}] {data.get('tool')}({data.get('args')}) -> {str(data.get('result'))[:200]}")

    out = StaffAgent(sys.argv[1], on_event=show).run(" ".join(sys.argv[2:]))
    print(f"[{sys.argv[1]}] {out['status']}: {out['answers'][-1] if out['answers'] else ''}")
    print(json.dumps({k: out[k] for k in ("session", "calls", "status")}))


if __name__ == "__main__":
    main()
