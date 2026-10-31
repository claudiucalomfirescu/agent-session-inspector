"""Show the recorded workday in demo/data/ — no API key, no network.

    python3 demo/run_demo.py            # rebuild viz/workday.html from demo/data, print the day, serve on :8765
    python3 demo/run_demo.py --no-serve # just rebuild the page and print the summary

Open the printed URL: a timeline of every task, the emails and chats between agents (with their
text, read from the mail and chat applications), firewall signals and blocks, and the IT admin's
actions. demo/data/proxy.db is the full proxy log; point llm-session-console at it for drill-down.
"""
import argparse
import http.server
import json
import os
import sys
from functools import partial

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-serve", action="store_true")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    from sim.export import bake, timeline
    dest = os.path.join(ROOT, "demo", "data")
    if not os.path.exists(os.path.join(dest, "runner.jsonl")):
        sys.exit("demo/data has no recorded day; run `python -m sim.run` then `python -m sim.export --demo`")
    data = timeline(dest)
    bake(data, os.path.join(ROOT, "viz", "workday_template.html"), os.path.join(ROOT, "viz", "workday.html"))
    st = data["stats"]
    print(f"Recorded day {data['date']}: {st['tasks']} tasks, {st['calls']} LLM calls in {st['sessions']} sessions, "
          f"{st['emails']} emails, {st['chats']} chats, signals {st['signals']}, {st['blocked_sessions']} sessions blocked")
    print(json.dumps(st.get("external_agents", {}), indent=1))
    if a.no_serve:
        print("page: viz/workday.html")
        return
    handler = partial(http.server.SimpleHTTPRequestHandler, directory=ROOT)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), handler)
    print(f"open http://127.0.0.1:{a.port}/viz/workday.html   (explainer: /explainers/index.html)   Ctrl-C to stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
