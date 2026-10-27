"""Step 1: the smallest agent. Talks to an OpenAI-compatible endpoint (OpenRouter by default).

Configuration (environment variables):
  LLM_BASE_URL   where requests go          (default: https://openrouter.ai/api/v1)
  LLM_API_KEY    key sent to that endpoint  (falls back to OPENROUTER_API_KEY)
  LLM_MODEL      model id                   (default: nvidia/nemotron-3.5-super-vl:free)
  AGENT_GOAL     the task                   (default: a small demo task)
  AGENT_MAX_TURNS turn limit                (default: 8)
"""
import json
import os
import sys
from datetime import datetime, timezone

from openai import OpenAI

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


TOOLS = {"current_time": current_time, "calculator": calculator}
TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "current_time", "description": "Get the current UTC time.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "calculator", "description": "Evaluate an arithmetic expression.",
        "parameters": {"type": "object",
                       "properties": {"expression": {"type": "string"}},
                       "required": ["expression"]}}},
]


def run() -> int:
    if not API_KEY:
        sys.exit("Set LLM_API_KEY (or OPENROUTER_API_KEY).")
    client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": GOAL}]
    print(f"model={MODEL} base_url={BASE_URL}\ngoal: {GOAL}\n")

    for turn in range(1, MAX_TURNS + 1):
        resp = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOL_SPECS,
            extra_body={"reasoning": {"enabled": True}})
        msg = resp.choices[0].message
        print(f"--- turn {turn} (finish_reason={resp.choices[0].finish_reason}) ---")
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            print(f"final answer: {msg.content}")
            return 0

        for call in msg.tool_calls:
            args = json.loads(call.function.arguments or "{}")
            fn = TOOLS.get(call.function.name)
            result = fn(**args) if fn else f"error: unknown tool {call.function.name}"
            print(f"tool call: {call.function.name}({args}) -> {result}")
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

    print(f"stopped: turn limit ({MAX_TURNS}) reached")
    return 1


if __name__ == "__main__":
    sys.exit(run())
