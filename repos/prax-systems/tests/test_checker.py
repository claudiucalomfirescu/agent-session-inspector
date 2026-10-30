"""Acceptance tests for tools/prax_check.py. Each test cites the R-id it proves."""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import prax_check  # noqa: E402

MINIMAL = ROOT / "examples" / "minimal"
BRONZE = ["prax.yaml", "README.md", "GOAL.md", "SPEC.md", "ARCHITECTURE.md",
          "PROMPTS.md", "ROADMAP.md", "DECISIONS.md"]


class CheckerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "repo"
        shutil.copytree(MINIMAL, self.repo)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def problems(self, level="silver"):
        return prax_check.check(self.repo, level)[0]

    def test_minimal_example_passes_silver(self):
        self.assertEqual(self.problems(), [])

    def test_R001_missing_bronze_file_fails(self):
        for f in BRONZE:
            with self.subTest(f=f):
                shutil.rmtree(self.repo); shutil.copytree(MINIMAL, self.repo)
                (self.repo / f).unlink()
                self.assertIn(f"missing {f}", self.problems("bronze"))

    def test_R002_spec_without_requirements_fails(self):
        (self.repo / "SPEC.md").write_text("# Spec\n\n" + "No numbered requirements here. " * 10)
        self.assertIn("SPEC.md defines no requirements (R-001…)", self.problems("bronze"))

    def test_R003_prompts_need_rebuild_verify_and_steps(self):
        (self.repo / "PROMPTS.md").write_text("# Prompts\n\n" + "Just prose about prompts. " * 10)
        p = self.problems("bronze")
        self.assertIn("PROMPTS.md has no P-REBUILD", p)
        self.assertIn("PROMPTS.md has no P-VERIFY", p)
        self.assertIn("PROMPTS.md has no step-by-step prompts (P-01…)", p)

    def test_R004_manifest_keys_required(self):
        (self.repo / "prax.yaml").write_text('prax: "0.1"\nname: x\n')
        self.assertIn("prax.yaml has no 'one_liner'", self.problems("bronze"))

    def test_R005_uncovered_requirement_fails_silver(self):
        spec = self.repo / "SPEC.md"
        spec.write_text(spec.read_text() + "| R-042 | something new | test_R042 |\n")
        self.assertTrue(any("R-042" in p for p in self.problems()))
        self.assertFalse(any("R-042" in p for p in self.problems("bronze")))

    def test_R006_empty_demo_data_fails_silver(self):
        for f in (self.repo / "demo" / "data").iterdir():
            f.unlink()
        self.assertIn("silver: demo/data/ has no recorded demo data", self.problems())

    def test_R009_checker_imports_only_stdlib(self):
        src = (ROOT / "tools" / "prax_check.py").read_text()
        imports = {l.split()[1].split(".")[0] for l in src.splitlines()
                   if l.startswith(("import ", "from "))}
        self.assertLessEqual(imports, {"argparse", "json", "re", "sys", "pathlib"})

    def test_R010_templates_exist(self):
        names = {p.name for p in (ROOT / "templates").iterdir()}
        self.assertLessEqual(set(BRONZE) | {"DEMO.md", "EXPLAINER_GUIDE.md"}, names)

    def test_R011_placeholders_reported(self):
        (self.repo / "GOAL.md").write_text((ROOT / "templates" / "GOAL.md").read_text())
        self.assertIn("GOAL.md still contains template placeholders", self.problems("bronze"))


if __name__ == "__main__":
    unittest.main()
