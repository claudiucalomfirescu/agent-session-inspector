"""How an agent reaches the enterprise applications: over HTTP, and nothing else.

    tc = ToolClient("tom-becker")          # or ToolClient("ext:hannah.clarke@mail.example")
    tc.specs                               # the OpenAI tool definitions this actor may use
    tc.call("crm_list_leads", '{"assigned_to": "me"}')   # -> JSON string for the role="tool" message

The tool list is fetched from the services (GET /tools?actor=...), so the applications decide who
may use what. A call is a POST /call to the service that hosts the tool. The agent process holds no
database and no business logic: an LLM decides which tool to call, this client carries the call.

Configuration: VXC_INTERNAL_URL (default http://127.0.0.1:8100), VXC_PORTAL_URL (default :8200).
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request

INTERNAL_URL = os.environ.get("VXC_INTERNAL_URL", "http://127.0.0.1:8100")
PORTAL_URL = os.environ.get("VXC_PORTAL_URL", "http://127.0.0.1:8200")


def _get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())


def services():
    return {"internal": os.environ.get("VXC_INTERNAL_URL", INTERNAL_URL),
            "bmw_portal": os.environ.get("VXC_PORTAL_URL", PORTAL_URL)}


def wait_ready(timeout=60):
    """Block until both services answer /health (they seed their databases on first start)."""
    import time
    deadline = time.time() + timeout
    for url in services().values():
        while True:
            try:
                _get(url.rstrip("/") + "/health")
                break
            except OSError:
                if time.time() > deadline:
                    raise RuntimeError(f"application service {url} is not answering")
                time.sleep(0.3)


class ToolClient:
    def __init__(self, actor):
        self.actor = actor
        self.specs, self.where = [], {}
        for service, url in services().items():
            q = urllib.parse.urlencode({"actor": actor})
            try:
                specs = _get(f"{url.rstrip('/')}/tools?{q}")
            except urllib.error.HTTPError:
                specs = []
            for s in specs:
                self.specs.append(s)
                self.where[s["function"]["name"]] = url
        self.names = set(self.where)

    def call(self, name, args=None):
        """Run one tool call from the model; always returns a JSON string (errors as {"error": ...})."""
        if isinstance(args, str):
            try:
                args = json.loads(args or "{}")
            except json.JSONDecodeError as e:
                return json.dumps({"error": f"arguments are not valid JSON: {e}"})
        if name not in self.where:
            return json.dumps({"error": f"you have no tool called {name}"})
        body = json.dumps({"actor": self.actor, "tool": name, "args": args or {}}).encode()
        req = urllib.request.Request(self.where[name].rstrip("/") + "/call", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                return r.read().decode()
        except urllib.error.HTTPError as e:
            return e.read().decode()
        except OSError as e:
            return json.dumps({"error": f"application unavailable: {e}"})

