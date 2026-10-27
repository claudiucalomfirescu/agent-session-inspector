"""Per-persona toolsets: what an agent playing a VXC Motors employee can call.

    from systems.tools import Toolset
    ts = Toolset("tom-becker")
    ts.specs                      # OpenAI tool definitions, only for Tom's systems (crm, dms, mail)
    ts.call("crm_list_leads", {"assigned_to": "me"})   # -> JSON string for the tool message

By default tools run in-process against data/*.duckdb. Set VXC_INTERNAL_URL and/or VXC_PORTAL_URL
(e.g. http://127.0.0.1:8100) to call a running `python -m systems.server` instead, which is how
several agent processes share the databases.
"""
import json
import os
import urllib.error
import urllib.request

from systems import bmw_portal, crm, dms, finance, mail, parts, workshop  # noqa: F401  (registers the tools)
from systems.common import REGISTRY, SYSTEM_DB, call_json, personas


def specs_for(persona_id: str) -> list[dict]:
    systems = set(personas()[persona_id].get("systems", []))
    return [t.spec() for t in REGISTRY.values() if t.system in systems]


def _remote_url(tool_name):
    db = SYSTEM_DB[REGISTRY[tool_name].system]
    return os.environ.get("VXC_PORTAL_URL" if db == "bmw_portal" else "VXC_INTERNAL_URL")


def call_remote(base_url: str, actor: str, name: str, args: dict) -> str:
    body = json.dumps({"actor": actor, "tool": name, "args": args}).encode()
    req = urllib.request.Request(base_url.rstrip("/") + "/call", data=body,
                                 headers={"Content-Type": "application/json", "X-Agent-Id": actor})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        return e.read().decode()
    except OSError as e:
        return json.dumps({"error": f"system unavailable: {e}"})


class Toolset:
    def __init__(self, persona_id: str):
        if persona_id not in personas():
            raise KeyError(f"unknown persona {persona_id}")
        self.actor = persona_id
        self.specs = specs_for(persona_id)
        self.names = {s["function"]["name"] for s in self.specs}

    def call(self, name: str, args: dict | str | None = None) -> str:
        """Run a tool call from the model; always returns a JSON string (errors as {"error": ...})."""
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except json.JSONDecodeError as e:
                return json.dumps({"error": f"arguments are not valid JSON: {e}"})
        if name not in REGISTRY:
            return json.dumps({"error": f"unknown tool {name}"})
        url = _remote_url(name)
        if url:
            return call_remote(url, self.actor, name, args or {})
        return call_json(self.actor, name, args or {})
