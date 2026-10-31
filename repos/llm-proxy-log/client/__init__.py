"""A tiny client helper: an OpenAI SDK client that talks through the proxy and says who is calling.

    from client import make_client, chat
    client, session = make_client("support-bot", user="omar", dept="support")
    resp = chat(client, [{"role": "user", "content": "Where is order 1042?"}])

Any OpenAI-compatible client works with the proxy without this module: point its base URL at the proxy
and add the headers listed in SPEC.md. This helper only does that for you.

Configuration (environment variables):
  LLM_BASE_URL  proxy address        (default: http://127.0.0.1:8080/v1)
  LLM_API_KEY   key sent to proxy    (default: "dummy"; the proxy holds the real key)
  LLM_MODEL     model agents ask for (default: nvidia/nemotron-3.5-super-vl:free)
"""
import json
import os
import time
import urllib.request
import uuid

BASE_URL = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:8080/v1")
API_KEY = os.environ.get("LLM_API_KEY", "dummy")
MODEL = os.environ.get("LLM_MODEL", "nvidia/nemotron-3.5-super-vl:free")


def identity_headers(agent_id=None, user=None, dept=None, session_id=None, **labels):
    """The proxy's identity headers (SPEC.md, "Who is calling"). Extra keyword labels become
    X-Agent-<Label> headers, e.g. role="support" -> X-Agent-Role: support."""
    headers = {"X-Agent-Id": agent_id, "X-Agent-User": user, "X-Agent-Dept": dept, "X-Session-Id": session_id}
    for k, v in labels.items():
        headers["X-Agent-" + k.replace("_", "-").title()] = v
    return {k: str(v) for k, v in headers.items() if v is not None}


def make_client(agent_id, user=None, dept=None, session_id=None, base_url=None, api_key=None, **labels):
    """An OpenAI client that goes through the proxy and names its traffic. Returns (client, session_id)."""
    from openai import OpenAI  # only the demo agents need the SDK; the proxy and dashboard do not

    session_id = session_id or uuid.uuid4().hex[:12]
    headers = identity_headers(agent_id, user, dept, session_id, **labels)
    # The proxy's gateway already waits and retries; the SDK's own retries would only multiply requests.
    client = OpenAI(base_url=base_url or BASE_URL, api_key=api_key or API_KEY, default_headers=headers,
                    max_retries=0, timeout=600)
    return client, session_id


def chat(client, messages, tools=None, model=None, attempts=3, **kwargs):
    """One chat completion. Retries a 429/5xx that got past the gateway a couple of times, then raises."""
    from openai import APIStatusError

    args = {"model": model or MODEL, "messages": messages, **kwargs}
    if tools:
        args["tools"] = tools
    for i in range(attempts):
        try:
            return client.chat.completions.create(**args)
        except APIStatusError as e:
            body = e.body if isinstance(e.body, dict) else {}
            body = body.get("error", body) if isinstance(body.get("error"), dict) else body
            if (body.get("metadata") or {}).get("gateway") in ("spend_cap", "daily_cap", "cache_miss") \
                    or e.status_code not in (429, 500, 502, 503, 504) or i == attempts - 1:
                raise  # a budget decision or a real error: retrying will not help
            time.sleep(10 * (i + 1))


def proxy_up(base_url=None):
    try:
        root = (base_url or BASE_URL).rstrip("/").removesuffix("/v1")
        with urllib.request.urlopen(root + "/healthz", timeout=5) as r:
            return json.loads(r.read()).get("ok") is True
    except OSError:
        return False
