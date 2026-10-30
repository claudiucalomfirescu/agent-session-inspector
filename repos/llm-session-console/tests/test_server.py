"""HTTP-level acceptance tests: start the real server on a free port and call it like the UI does."""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from console import server  # noqa: E402
from tests import fixtures  # noqa: E402


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        paths = [fixtures.build(cls.tmp, "v2"), fixtures.build(cls.tmp, "v1")]
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(server.Logs(paths)))
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def get(self, path):
        try:
            with urllib.request.urlopen(self.base + path) as r:
                body = r.read()
                return r.status, (json.loads(body) if r.headers.get("Content-Type") == "application/json" else body)
        except urllib.error.HTTPError as e:
            return e.code, None

    def test_R020_several_logs_selected_by_db(self):
        """Proves: R-020."""
        st, d = self.get("/api/dbs")
        self.assertEqual([x["name"] for x in d["dbs"]], ["v2", "v1"])
        self.assertTrue(self.get("/api/meta")[1]["has_signals"])           # first log is the default
        self.assertFalse(self.get("/api/meta?db=v1")[1]["has_signals"])
        self.assertEqual(self.get("/api/meta?db=nope")[0], 404)

    def test_R005_R021_every_view_endpoint_answers(self):
        """Proves: R-005, R-021 (the endpoints behind each drill-down level)."""
        for path in ("/api/overview", "/api/overview?bucket=week", "/api/users", "/api/user/omar", "/api/sessions?level=info",
                     "/api/session/s2", "/api/call/3", "/api/firewall", "/api/galaxy", "/api/search?q=refund",
                     "/api/overview?from=2026-10-28&to=2026-10-28&bucket=hour"):
            st, d = self.get(path)
            self.assertEqual(st, 200, path)
        self.assertEqual(self.get("/api/overview?user=omar")[1]["totals"]["calls"], 2)
        self.assertEqual(self.get("/api/session/missing")[0], 404)
        self.assertEqual(self.get("/api/user/nobody")[0], 404)

    def test_R019_static_files_and_no_traversal(self):
        """Proves: R-019. UI is served; paths outside web/ are refused; server binds localhost."""
        st, body = self.get("/")
        self.assertEqual(st, 200)
        self.assertIn(b"Session Console", body)
        self.assertEqual(self.get("/../console/server.py")[0], 404)
        self.assertEqual(self.get("/%2e%2e/console/server.py")[0], 404)
        self.assertIn('default="127.0.0.1"', open(server.__file__).read())

    def test_R016_live_append_visible_without_restart(self):
        """Proves: R-016 over HTTP: the proxy appends, the next request sees it."""
        p = os.path.join(self.tmp, "v1.db")
        before = self.get("/api/meta?db=v1")[1]["calls"]
        time.sleep(0.05)
        fixtures.add_call(p, 50, "2026-10-29T09:00:00Z", "raj", "live")
        os.utime(p, None)
        self.assertEqual(self.get("/api/meta?db=v1")[1]["calls"], before + 1)


class TestDemoData(unittest.TestCase):
    def test_R018_bundled_demo_logs_unpack_and_load(self):
        """Proves: R-018, R-101. demo/data/*.db.xz unpack offline; the 4-week log loads fast and answers fast."""
        paths = server.unpack_samples()
        names = sorted(os.path.basename(p) for p in paths)
        self.assertIn("vxc-4-weeks.db", names)
        self.assertIn("vxc-recorded-day.db", names)
        t = time.time()
        logs = server.Logs(paths)
        self.assertLess(time.time() - t, 5)
        s = logs.get("vxc-4-weeks")
        m = s.meta()
        self.assertGreater(m["calls"], 4000)
        self.assertTrue(m["has_signals"])
        self.assertEqual(m["identity"], "X-Agent-User")
        from console.store import Filters
        for fn in (lambda: s.overview(Filters()), lambda: s.galaxy(Filters()), lambda: s.firewall(Filters()),
                   lambda: s.user("tom-becker", Filters())):
            t = time.time()
            fn()
            self.assertLess(time.time() - t, 1.5)
        self.assertEqual(logs.get("vxc-recorded-day").meta()["identity"], "X-Agent-Id")


if __name__ == "__main__":
    unittest.main()
