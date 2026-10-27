"""Shared LLM layer for every VXC Motors agent: one way to get a client that talks through the proxy.

    from llm import make_client, chat
    client, session = make_client("sales-anna", role="sales", department="sales")
    resp = chat(client, messages, tools=TOOL_SPECS)

The budget rules (rate limit, backoff, daily-cap fallback, spend cap, replay cache) live in the proxy
(proxy/gateway.py), because they are account-wide and the proxy is the one place every call passes.
This module only points agents at the proxy, labels their traffic, and retries the rare error that
still reaches them.

Configuration (environment variables):
  LLM_BASE_URL  proxy address      (default: http://127.0.0.1:8080/v1)
  LLM_API_KEY   key sent to proxy  (default: "dummy"; the proxy holds the real key)
  LLM_MODEL     model agents ask for (default: nvidia/nemotron-3.5-super-vl:free)
"""
from .client import BASE_URL, MODEL, chat, gateway_status, make_client, proxy_up, start_proxy

__all__ = ["BASE_URL", "MODEL", "chat", "gateway_status", "make_client", "proxy_up", "start_proxy"]
