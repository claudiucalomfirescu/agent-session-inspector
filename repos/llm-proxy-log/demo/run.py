"""One command for the whole demo: start the proxy, run the team through it, leave the log for the dashboard.

    python3 demo/run.py --offline          # no key needed: a local fake LLM answers (demo/fake_llm.py)
    python3 demo/run.py --live --pace 15   # the real provider (OPENROUTER_API_KEY), one call every 15 s
    python3 demo/run.py --offline --only 4 # just four sessions

Then: python3 dashboard/server.py  -> http://127.0.0.1:8091
The log goes to PROXY_LOG_DB (default logs/proxy.db). If a proxy is already listening on the port, it
is used as is.
"""
import argparse
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
import fake_llm  # noqa: E402
import team  # noqa: E402
from client import proxy_up  # noqa: E402


def start_proxy(env, port):
    base = f"http://127.0.0.1:{port}/v1"
    if proxy_up(base):
        print(f"using the proxy already running at {base}")
        return None, base
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "proxy", "proxy.py")], cwd=ROOT,
                            env={**os.environ, "PROXY_PORT": str(port), **env})
    for _ in range(100):
        if proxy_up(base):
            return proc, base
        if proc.poll() is not None:
            sys.exit("the proxy exited at start (see its message above)")
        time.sleep(0.1)
    proc.terminate()
    sys.exit("the proxy did not start")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true", help="use the local fake LLM, no key needed")
    mode.add_argument("--live", action="store_true", help="use the real provider (needs OPENROUTER_API_KEY)")
    p.add_argument("--only", type=int, help="run only the first N scenarios")
    p.add_argument("--pace", type=float, help="minimum seconds between LLM calls (default: 0 offline, 15 live)")
    p.add_argument("--model", help="model the agents ask for (default: LLM_MODEL or the free model)")
    p.add_argument("--port", type=int, default=int(os.environ.get("PROXY_PORT", "8080")))
    p.add_argument("--scenarios", default=os.path.join(HERE, "scenarios.json"))
    a = p.parse_args(argv)

    env = {"PROXY_LOGGING": "on"}
    fake = None
    if a.offline:
        fake = fake_llm.start(int(os.environ.get("FAKE_LLM_PORT", "8099")))
        env.update(UPSTREAM_BASE_URL=f"http://127.0.0.1:{fake.server_address[1]}/v1", OPENROUTER_API_KEY="offline-demo",
                   GATEWAY_CACHE="off", GATEWAY_FREE_RPM="10000", GATEWAY_DB=os.path.join("logs", "gateway-offline.db"))
    elif not os.environ.get("OPENROUTER_API_KEY"):
        sys.exit("--live needs OPENROUTER_API_KEY (or use --offline)")
    proc, base = start_proxy(env, a.port)
    try:
        args = ["--base-url", base, "--pace", str(a.pace if a.pace is not None else (0 if a.offline else 15)),
                "--scenarios", a.scenarios]
        if a.model:
            args += ["--model", a.model]
        if a.only:
            args += ["--only", str(a.only)]
        team.main(args)
    finally:
        if proc:
            proc.terminate()
            proc.wait()
        if fake:
            fake.shutdown()
    print(f"log: {os.environ.get('PROXY_LOG_DB', 'logs/proxy.db')}   view: python3 dashboard/server.py  or  python3 proxy/view_log.py")


if __name__ == "__main__":
    main()
