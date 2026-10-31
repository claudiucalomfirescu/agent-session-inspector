"""The demo team: four AI agents at Brightleaf Software, each working for one person, each with tools.

Every tool reads demo/company.json, a small made-up company: no network, no real systems. The point of
the demo is the traffic the proxy sees, so the tools are deliberately simple and their answers short.

    agent            works for   dept         tools
    dev-assistant    maya        engineering  read_file, run_tests
    support-bot      omar        support      get_ticket, get_order, get_policy
    sales-assistant  lena        sales        get_lead, get_prices
    ops-helper       raj         ops          get_metrics, get_incident
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "company.json"), encoding="utf-8") as f:
    COMPANY = json.load(f)


def _lookup(table, key):
    row = COMPANY[table].get(str(key).strip())
    return row if row is not None else {"error": f"no {table[:-1]} {key!r}", "known": sorted(COMPANY[table])}


# name -> (description, {param: description}, function)
TOOLS = {
    "read_file": ("Read a source file from the Leafdesk repository.", {"path": "file path, e.g. export/csv.py"},
                  lambda path: {"path": path, "content": COMPANY["repo"].get(path, f"no such file; files: {sorted(COMPANY['repo'])}")}),
    "run_tests": ("Run one test suite and get the result.", {"suite": "export, billing or import"},
                  lambda suite: _lookup("tests", suite)),
    "get_ticket": ("Fetch a support ticket.", {"ticket_id": "e.g. T-311"}, lambda ticket_id: _lookup("tickets", ticket_id)),
    "get_order": ("Fetch a customer's subscription order.", {"order_id": "e.g. 1042"}, lambda order_id: _lookup("orders", order_id)),
    "get_policy": ("Read a company policy.", {"topic": "refunds, seats or failed_payment"},
                   lambda topic: {"topic": topic, "policy": COMPANY["policies"].get(topic, f"topics: {sorted(COMPANY['policies'])}")}),
    "get_lead": ("Fetch a sales lead from the CRM.", {"lead_id": "e.g. L-77"}, lambda lead_id: _lookup("leads", lead_id)),
    "get_prices": ("Get the current price list.", {}, lambda: COMPANY["prices"]),
    "get_metrics": ("Get live metrics for a service.", {"service": "api, web or email-import"},
                    lambda service: {"service": service, **COMPANY["metrics"].get(service, {"error": "unknown service"})}),
    "get_incident": ("Fetch an incident record.", {"incident_id": "e.g. INC-19"}, lambda incident_id: _lookup("incidents", incident_id)),
}

AGENTS = {
    "dev-assistant": {"user": "maya", "tools": ["read_file", "run_tests"],
                      "role": "You help Maya, a backend developer, read code and test results and suggest fixes."},
    "support-bot": {"user": "omar", "tools": ["get_ticket", "get_order", "get_policy"],
                    "role": "You help Omar, the support lead, answer customer tickets correctly and kindly."},
    "sales-assistant": {"user": "lena", "tools": ["get_lead", "get_prices"],
                        "role": "You help Lena, an account executive, prepare for calls and write proposals."},
    "ops-helper": {"user": "raj", "tools": ["get_metrics", "get_incident"],
                   "role": "You help Raj, a site reliability engineer, watch services and handle incidents."},
}


def tool_specs(names):
    return [{"type": "function", "function": {
        "name": n, "description": TOOLS[n][0],
        "parameters": {"type": "object", "properties": {p: {"type": "string", "description": d} for p, d in TOOLS[n][1].items()},
                       "required": list(TOOLS[n][1])}}} for n in names]


def run_tool(name, arguments):
    """Run a tool call from the LLM; always returns a JSON string, errors included."""
    if name not in TOOLS:
        return json.dumps({"error": f"unknown tool {name}"})
    try:
        args = json.loads(arguments or "{}")
        return json.dumps(TOOLS[name][2](**{k: v for k, v in args.items() if k in TOOLS[name][1]}), ensure_ascii=False)
    except Exception as e:  # noqa: BLE001  a bad call is the LLM's problem to read, not a crash
        return json.dumps({"error": f"{type(e).__name__}: {e}"})


def system_prompt(agent_id):
    a, person = AGENTS[agent_id], COMPANY["people"][AGENTS[agent_id]["user"]]
    return (f"You are {agent_id}, an AI assistant at {COMPANY['company']}. {COMPANY['about']} {a['role']} "
            f"You work for {person['name']} ({person['title']}, {person['dept']}). Use your tools to look things up "
            "instead of guessing. Keep answers short and practical.")
