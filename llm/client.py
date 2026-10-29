import json
import os
import subprocess
import sys
import time
import urllib.request
import uuid

from openai import APIStatusError, OpenAI

BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8080/v1")
API_KEY = os.environ.get("LLM_API_KEY", "dummy")
MODEL = os.environ.get("LLM_MODEL", "nvidia/nemotron-3.5-super-vl:free")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def make_client(agent_id, session_id=None, **labels):
    """An OpenAI client that goes through the proxy and names its traffic.

    Every request carries X-Agent-Id and X-Session-Id; extra keyword labels become X-Agent-<Label>
    headers (e.g. role="sales" -> X-Agent-Role: sales). The proxy reads them and strips them before
    forwarding. Returns (client, session_id)."""
    session_id = session_id or uuid.uuid4().hex[:12]
    headers = {"X-Agent-Id": agent_id, "X-Session-Id": session_id}
    for k, v in labels.items():
        if v is not None:
            headers["X-Agent-" + k.replace("_", "-").title()] = str(v)
    # The proxy already waits and retries; the SDK's own retries would only multiply requests.
    return OpenAI(base_url=BASE_URL, api_key=API_KEY, default_headers=headers, max_retries=0, timeout=600), session_id


def chat(client, messages, tools=None, model=None, attempts=3, log=None, **kwargs):
    """One chat completion. Retries a 429/5xx that got past the gateway a couple of times, then raises.
    log: an llm.AgentLog; the request, the answer (with the proxy's X-Firewall verdict) and errors go there."""
    args = {"model": model or MODEL, "messages": messages, **kwargs}
    if tools:
        args["tools"] = tools
    if log:
        log.request(messages)
    for i in range(attempts):
        try:
            if not log:
                return client.chat.completions.create(**args)
            raw = client.chat.completions.with_raw_response.create(**args)
            resp = raw.parse()
            log.response(resp, {k.lower(): v for k, v in raw.headers.items()})
            return resp
        except APIStatusError as e:
            if log:
                log.error(e)
            body = e.body if isinstance(e.body, dict) else {}
            body = body.get("error", body) if isinstance(body.get("error"), dict) else body
            gateway_kind = (body.get("metadata") or {}).get("gateway")
            if gateway_kind in ("spend_cap", "daily_cap", "cache_miss") or e.status_code not in (429, 500, 502, 503, 504):
                raise  # a budget decision or a real error: retrying will not help
            if i == attempts - 1:
                raise
            time.sleep(10 * (i + 1))


def gateway_status():
    """The proxy's budget view: free requests left today, fallback spend, limiter load, cache size."""
    with urllib.request.urlopen(BASE_URL.rstrip("/") + "/gateway/status", timeout=20) as r:
        return json.loads(r.read())


def proxy_up():
    try:
        gateway_status()
        return True
    except OSError:
        return False


def start_proxy(logging=True, **env):
    """Start proxy/proxy.py as a child process (if it is not already running) and wait until it answers.
    Extra keyword arguments become environment variables, e.g. GATEWAY_CACHE="replay".
    Returns the Popen, or None if a proxy was already up."""
    if proxy_up():
        return None
    child_env = {**os.environ, "PROXY_LOGGING": "on" if logging else "off", **{k: str(v) for k, v in env.items()}}
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "proxy", "proxy.py")], cwd=ROOT, env=child_env)
    for _ in range(50):
        if proxy_up():
            return proc
        if proc.poll() is not None:
            raise RuntimeError("proxy exited at start; is OPENROUTER_API_KEY set?")
        time.sleep(0.2)
    proc.terminate()
    raise RuntimeError("proxy did not start")
