"""Offline tests for the people identity files and the off-site runner (fake LLM, no proxy, no key).

Proves: R-OFF-001, R-OFF-002, R-OFF-003, R-OFF-004, R-OFF-005, R-OFF-006, R-OFF-007 (offsite/SPEC.md)
"""
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from offsite import agenda, run  # noqa: E402
from people.load import PARTS, list_people, load_identity  # noqa: E402

STAFF = ["aisha-rahman", "daniel-reed", "elena-popescu", "james-okafor", "lucas-meyer", "maria-santos",
         "mark-doyle", "nina-kovac", "priya-nair", "sofia-marin", "tom-becker", "victor-hale"]

FACTS = {"as_of": "2026-10-26", "cars_sold_total": 3}


class PeopleTest(unittest.TestCase):
    def test_R_OFF_001_every_employee_has_four_identity_files(self):
        self.assertEqual(list_people(), STAFF)
        for p in STAFF:
            for part in PARTS:
                text = open(os.path.join(ROOT, "people", p, part + ".md"), encoding="utf-8").read()
                self.assertIn(f"id: {p}", text)
                self.assertIn(f"kind: {part}", text)
                self.assertGreater(len(text), 400, f"{p}/{part}.md is too thin")

    def test_R_OFF_002_identity_block_contains_all_parts_in_order(self):
        block = load_identity("tom-becker")
        self.assertIn("Tom Becker", block)
        positions = [block.index(f"=== YOUR {p.upper()} ===") for p in PARTS]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("\n---\n", block, "frontmatter must be stripped")


class OffsiteFakeRunTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        facts = os.path.join(cls.out, "facts.json")
        json.dump(FACTS, open(facts, "w"))
        run.main(["--fake", "--out", cls.out, "--facts", facts])
        cls.events = [json.loads(l) for l in open(os.path.join(cls.out, "transcript.jsonl"))]
        cls.results = json.load(open(os.path.join(cls.out, "results.json")))

    def test_R_OFF_003_every_segment_runs_in_agenda_order(self):
        seen = []
        for e in self.events:
            if e["segment"] not in seen:
                seen.append(e["segment"])
        self.assertEqual(seen, [s["id"] for s in agenda.SEGMENTS])

    def test_R_OFF_004_everyone_speaks_and_moderator_runs_the_room(self):
        speakers = {e["speaker"] for e in self.events if e["kind"] == "message"}
        self.assertEqual(speakers, set(STAFF) | {run.MODERATOR})
        self.assertEqual(self.events[1]["speaker"], run.MODERATOR)

    def test_R_OFF_005_lies_hidden_from_room_and_scored_by_software(self):
        for e in self.events:
            if e["kind"] == "message":
                self.assertNotRegex(e["text"], r"(?m)^\s*LIE\s*:")
        g = self.results["two_truths"]
        self.assertEqual(len(g["turns"]), 12)
        self.assertEqual(len(g["guesses"]), 12)  # 11 in turn + the first person guesses the last
        self.assertTrue(all("correct" in x for x in g["guesses"]))

    def test_R_OFF_006_votes_exclude_own_idea_and_are_tallied(self):
        ideas = {i["n"]: i["who"] for i in self.results["idea_list"]}
        self.assertEqual(len(ideas), 12)
        for b in self.results["vote"]["ballots"]:
            self.assertTrue(all(ideas[n] != b["who"] for n in b["votes"]))
        total = sum(r["votes"] for r in self.results["vote"]["ranking"])
        self.assertEqual(total, sum(len(b["votes"]) for b in self.results["vote"]["ballots"]))

    def test_R_OFF_007_outputs_and_replay(self):
        for f in ("transcript.jsonl", "transcript.md", "results.json", "meta.json", "factsheet.json"):
            self.assertTrue(os.path.isfile(os.path.join(self.out, f)), f)
        from offsite import replay
        html = open(replay.build(self.out), encoding="utf-8").read()
        self.assertIn("VXC Motors all-staff off-site", html)
        self.assertNotIn("http://", html.replace("http://www.w3.org", ""), "replay must work offline")


class ParsingTest(unittest.TestCase):
    def test_split_next_and_clean(self):
        text, picks = run.split_next("Over to you!\nNEXT: priya-nair, nobody, tom-becker", {"priya-nair", "tom-becker"})
        self.assertEqual((text, picks), ("Over to you!", ["priya-nair", "tom-becker"]))
        self.assertEqual(run.clean("<think>hmm</think>Victor Hale: Morning all."), "Morning all.")
        p = run.parse_two_truths("GUESS: 2 nice try\n1. a\n2. b\n3. c\nLIE: 3")
        self.assertEqual((p["guess"], p["lie"], p["statements"]), (2, 3, ["a", "b", "c"]))
        self.assertNotIn("LIE", p["public"])


if __name__ == "__main__":
    unittest.main()
