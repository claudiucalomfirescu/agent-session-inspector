"""Local web server: static UI from web/ and a read-only JSON API over one or more proxy logs.

    python3 -m console                         # the bundled demo logs (demo/data/*.db.xz, unpacked on first run)
    python3 -m console --db ~/proxy/logs/proxy.db --db other.db --port 8095

Every API call takes ?db=<name> (default: the first log) and the shared filters
?from=YYYY-MM-DD&to=YYYY-MM-DD&user=&dept=&system=0|1. See SPEC.md §5 for the endpoint list.
The server binds 127.0.0.1 only: proxy logs hold whole conversations.
"""
import argparse
import json
import lzma
import os
import shutil
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .store import Filters, Store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
SAMPLES = os.path.join(ROOT, "demo", "data")
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".svg": "image/svg+xml", ".json": "application/json", ".png": "image/png", ".ico": "image/x-icon"}


def unpack_samples(folder=SAMPLES):
    """demo/data/x.db.xz -> demo/data/.cache/x.db (once; re-unpacked when the .xz is newer)."""
    out = []
    cache = os.path.join(folder, ".cache")
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not name.endswith(".db.xz"):
            continue
        src, dst = os.path.join(folder, name), os.path.join(cache, name[:-3])
        if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
            os.makedirs(cache, exist_ok=True)
            with lzma.open(src) as fi, open(dst + ".tmp", "wb") as fo:
                shutil.copyfileobj(fi, fo)
            os.replace(dst + ".tmp", dst)
        out.append(dst)
    return out


class Logs:
    """The open logs, by name; each is refreshed when its file changes (the proxy is still writing)."""

    def __init__(self, paths):
        self.stores, self.mtimes = {}, {}
        for p in paths:
            s = Store(p)
            name = s.name
            while name in self.stores:
                name += "+"
            s.name = name
            self.stores[name] = s
            self.mtimes[name] = self._mtime(p)

    @staticmethod
    def _mtime(path):
        return max((os.path.getmtime(p) for p in (path, path + "-wal") if os.path.exists(p)), default=0)

    def get(self, name=None):
        s = self.stores.get(name) if name else next(iter(self.stores.values()))
        if s is None:
            return None
        m = self._mtime(s.path)
        if m != self.mtimes[s.name]:
            self.mtimes[s.name] = m
            s.refresh()
        return s

    def list(self):
        return [s.meta() for s in self.stores.values()]


def make_handler(logs):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet: one line per error only
            if args and str(args[1])[0] in "45":
                sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(url.query)
            try:
                if url.path.startswith("/api/"):
                    return self.api(url.path[5:].strip("/"), q)
                return self.static(url.path)
            except Exception as e:  # noqa: BLE001
                return self.send_json({"error": f"{type(e).__name__}: {e}"}, 500)

        def api(self, path, q):
            if path == "dbs":
                return self.send_json({"dbs": logs.list()})
            s = logs.get((q.get("db") or [None])[0])
            if s is None:
                return self.send_json({"error": "unknown db"}, 404)
            f = Filters(q)
            one = lambda k, d=None: (q.get(k) or [d])[0]  # noqa: E731
            parts = path.split("/", 1)
            arg = urllib.parse.unquote(parts[1]) if len(parts) > 1 else None
            bucket = one("bucket", "day")
            if parts[0] == "meta":
                data = s.meta()
            elif parts[0] == "overview":
                data = s.overview(f, bucket)
            elif parts[0] == "users":
                data = s.users(f)
            elif parts[0] == "user" and arg:
                data = s.user(arg, f, bucket)
            elif parts[0] == "sessions":
                data = s.sessions(f, level=one("level"))
            elif parts[0] == "session" and arg:
                data = s.session(arg)
            elif parts[0] == "call" and arg and arg.isdigit():
                data = s.call(int(arg))
            elif parts[0] == "firewall":
                data = s.firewall(f, level=one("level"), topic=one("topic"))
            elif parts[0] == "galaxy":
                data = s.galaxy(f)
            elif parts[0] == "search":
                data = s.search(one("q", ""), f) if len(one("q", "")) >= 2 else []
            else:
                return self.send_json({"error": "unknown endpoint"}, 404)
            if data is None:
                return self.send_json({"error": "not found"}, 404)
            return self.send_json(data)

        def static(self, path):
            if path in ("", "/"):
                path = "/index.html"
            full = os.path.normpath(os.path.join(WEB, path.lstrip("/")))
            if not full.startswith(WEB) or not os.path.isfile(full):
                self.send_response(404)
                self.end_headers()
                return
            with open(full, "rb") as fh:
                body = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", TYPES.get(os.path.splitext(full)[1], "application/octet-stream"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, data, status=200):
            body = json.dumps(data, default=str).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def main(argv=None):
    ap = argparse.ArgumentParser(description="LLM session console: drill into a proxy log")
    ap.add_argument("--db", action="append", help="proxy log (SQLite); repeat for several. Default: bundled demo logs")
    ap.add_argument("--port", type=int, default=int(os.environ.get("CONSOLE_PORT", 8095)))
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args(argv)
    t = time.time()
    paths = a.db or unpack_samples()
    if not paths:
        sys.exit("no --db given and no demo logs found in demo/data/")
    logs = Logs(paths)
    for m in logs.list():
        print(f"  {m['name']:<28} {m['calls']:>6} calls  {m['users']:>3} users  {m['first']} .. {m['last']}"
              f"  firewall={'yes' if m['has_firewall'] else 'no'}  users from {m['identity']}")
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(logs))
    print(f"loaded in {time.time() - t:.1f}s · console on http://{a.host}:{a.port}/")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
