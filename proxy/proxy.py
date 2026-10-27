"""Step 2: pass-through proxy. Sits between the agent and OpenRouter, no logging.

The agent only changes its base URL (and may send a dummy key); this process alone holds the real key.

Configuration (environment variables):
  OPENROUTER_API_KEY  real provider key       (required)
  UPSTREAM_BASE_URL   provider API root       (default: https://openrouter.ai/api/v1)
  PROXY_HOST/PORT     where to listen         (default: 127.0.0.1:8080)
Point the agent at http://127.0.0.1:8080/v1
"""
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = os.environ.get("UPSTREAM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
REAL_KEY = os.environ.get("OPENROUTER_API_KEY")
HOST = os.environ.get("PROXY_HOST", "127.0.0.1")
PORT = int(os.environ.get("PROXY_PORT", "8080"))

# Headers that describe one hop only, or that the agent's own key/transport must not leak upstream.
SKIP_REQUEST = {"host", "authorization", "content-length", "connection", "accept-encoding", "transfer-encoding"}
SKIP_RESPONSE = {"content-length", "content-encoding", "transfer-encoding", "connection"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _forward(self):
        path = self.path[3:] if self.path.startswith("/v1") else self.path
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        headers = {k: v for k, v in self.headers.items() if k.lower() not in SKIP_REQUEST}
        headers["Authorization"] = f"Bearer {REAL_KEY}"
        req = urllib.request.Request(UPSTREAM + path, data=body or None, headers=headers, method=self.command)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                status, resp_headers, data = r.status, r.getheaders(), r.read()
        except urllib.error.HTTPError as e:  # provider errors are passed back as they are
            status, resp_headers, data = e.code, e.headers.items(), e.read()
        except OSError as e:
            data = ('{"error": {"code": 502, "message": "proxy could not reach provider: %s"}}'
                    % type(e).__name__).encode()
            status, resp_headers = 502, [("Content-Type", "application/json")]
        self.send_response(status)
        for k, v in resp_headers:
            if k.lower() not in SKIP_RESPONSE:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = _forward

    def log_message(self, *args):  # pass-through mode logs nothing
        pass


if __name__ == "__main__":
    if not REAL_KEY:
        sys.exit("Set OPENROUTER_API_KEY for the proxy.")
    print(f"proxy listening on http://{HOST}:{PORT}/v1 -> {UPSTREAM}", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
