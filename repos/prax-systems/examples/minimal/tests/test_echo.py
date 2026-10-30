import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from echo import echo  # noqa: E402


class EchoTest(unittest.TestCase):
    def test_R001_returns_input(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(echo("hi", f"{d}/l.jsonl"), "hi")

    def test_R002_appends_one_line(self):
        with tempfile.TemporaryDirectory() as d:
            p = f"{d}/l.jsonl"
            echo("a", p); echo("b", p)
            rows = [json.loads(l) for l in open(p)]
            self.assertEqual([r["msg"] for r in rows], ["a", "b"])
            self.assertIn("ts", rows[0])


if __name__ == "__main__":
    unittest.main()
