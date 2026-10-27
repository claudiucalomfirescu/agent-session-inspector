"""Step 1: the smallest agent. Talks to an OpenAI-compatible endpoint (OpenRouter by default).

Configuration (environment variables):
  LLM_BASE_URL   where requests go          (default: https://openrouter.ai/api/v1)
  LLM_API_KEY    key sent to that endpoint  (falls back to OPENROUTER_API_KEY)
  LLM_MODEL      model id                   (default: nvidia/nemotron-3.5-super-vl:free)
  AGENT_GOAL     the task                   (default: a small demo task)
  AGENT_MAX_TURNS turn limit                (default: 8)
  AGENT_ID       name sent as X-Agent-Id    (default: agent-1); a fresh X-Session-Id is made per run
  AGENT_LOG      on|off  the agent's own log in logs/agents/<AGENT_ID>.jsonl (default: on; see llm/agentlog.py)
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone

from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from llm.agentlog import AgentLog  # noqa: E402

BASE_URL = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
API_KEY = os.environ.get("LLM_API_KEY") or os.environ.get("OPENROUTER_API_KEY")
MODEL = os.environ.get("LLM_MODEL", "nvidia/nemotron-3.5-super-vl:free")
MAX_TURNS = int(os.environ.get("AGENT_MAX_TURNS", "8"))
GOAL = os.environ.get(
    "AGENT_GOAL",
    "What is the current UTC time, and what is 1234 * 5678? Use the tools, then answer in one sentence.",
)
SYSTEM_PROMPT = (
    "You are a small autonomous agent. Use the provided tools when they help. "
    "When the goal is fully achieved, reply with the final answer and no tool call."
)


def current_time() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def calculator(expression: str) -> str:
    if not set(expression) <= set("0123456789+-*/(). "):
        return "error: only digits and + - * / ( ) . are allowed"
    try:
        return str(eval(expression, {"__builtins__": {}}, {}))
    except Exception as e:
        return f"error: {e}"


# A tiny fake shop, so a goal can need several dependent lookups (order -> customer -> shipping).
ORDERS = {"A-1001": {"customer_id": "C-77", "items": [{"sku": "LAMP-01", "qty": 2, "unit_price": 39.90},
                                                     {"sku": "BULB-06", "qty": 6, "unit_price": 4.50}]}}
CUSTOMERS = {"C-77": {"name": "Marta Ionescu", "country": "RO", "tier": "gold"}}
SHIPPING = {"RO": {"rate": 12.00, "free_over": 150.00}, "DE": {"rate": 9.00, "free_over": 100.00}}
TIER_DISCOUNT = {"gold": 0.10, "silver": 0.05}


def get_order(order_id: str) -> str:
    return json.dumps(ORDERS.get(order_id) or {"error": f"no order {order_id}"})


def get_customer(customer_id: str) -> str:
    c = CUSTOMERS.get(customer_id)
    return json.dumps({**c, "discount": TIER_DISCOUNT.get(c["tier"], 0)} if c else {"error": f"no customer {customer_id}"})


def get_shipping(country: str) -> str:
    return json.dumps(SHIPPING.get(country) or {"error": f"no shipping to {country}"})


TOOLS = {"current_time": current_time, "calculator": calculator,
         "get_order": get_order, "get_customer": get_customer, "get_shipping": get_shipping}
TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "current_time", "description": "Get the current UTC time.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "calculator", "description": "Evaluate an arithmetic expression.",
        "parameters": {"type": "object",
                       "properties": {"expression": {"type": "string"}},
                       "required": ["expression"]}}},
    {"type": "function", "function": {
        "name": "get_order", "description": "Look up an order: customer id and line items.",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}},
                       "required": ["order_id"]}}},
    {"type": "function", "function": {
        "name": "get_customer", "description": "Look up a customer: name, country, loyalty tier and discount rate.",
        "parameters": {"type": "object", "properties": {"customer_id": {"type": "string"}},
                       "required": ["customer_id"]}}},
    {"type": "function", "function": {
        "name": "get_shipping", "description": "Shipping rate for a country and the order value above which shipping is free.",
        "parameters": {"type": "object", "properties": {"country": {"type": "string"}},
                       "required": ["country"]}}},
]


def run() -> int:
    if not API_KEY:
        sys.exit("Set LLM_API_KEY (or OPENROUTER_API_KEY).")
    session_id = uuid.uuid4().hex[:12]
    agent_id = os.environ.get("AGENT_ID", "agent-1")
    client = OpenAI(base_url=BASE_URL, api_key=API_KEY, default_headers={
        "X-Agent-Id": agent_id, "X-Session-Id": session_id})
    log = AgentLog(agent_id, session_id)  # the agent's own view of the session
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": GOAL}]
    print(f"model={MODEL} base_url={BASE_URL} session={session_id}\ngoal: {GOAL}\n")
    log.start(GOAL, MODEL)

    for turn in range(1, MAX_TURNS + 1):
        log.request(messages)
        raw = client.chat.completions.with_raw_response.create(model=MODEL, messages=messages, tools=TOOL_SPECS,
            extra_body={"reasoning": {"enabled": True}})
        resp = raw.parse()
        log.response(resp, {k.lower(): v for k, v in raw.headers.items()})
        msg = resp.choices[0].message
        print(f"--- turn {turn} (finish_reason={resp.choices[0].finish_reason}) ---")
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            print(f"final answer: {msg.content}")
            if log.blocked:  # the proxy answered in the LLM's place; this session is closed
                print(f"(proxy firewall: {log.blocked})")
            log.end(msg.content)
            return 0

        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            fn = TOOLS.get(call.function.name)
            result = fn(**args) if fn else f"error: unknown tool {call.function.name}"
            print(f"tool call: {call.function.name}({args}) -> {result}")
            log.tool(call.function.name, args, result)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    print(f"stopped: turn limit ({MAX_TURNS}) reached")
    log.end(None, status="turn_limit")
    return 1


if __name__ == "__main__":
    sys.exit(run())
