#!/usr/bin/env python3
"""Check a repository against the Prax Systems repository contract.

Usage:
    python3 prax_check.py <repo-dir> [--level bronze|silver] [--json]

Stdlib only, so it runs in any fresh clone. Exit code 0 when the repo
meets the requested level, 1 otherwise.
"""
import argparse
import json
import re
import sys
from pathlib import Path

REQUIRED_FILES = [
    "prax.yaml", "README.md", "GOAL.md", "SPEC.md", "ARCHITECTURE.md",
    "PROMPTS.md", "ROADMAP.md", "DECISIONS.md",
]
SILVER_PATHS = ["demo/DEMO.md", "explainers/index.html", "tests"]
MANIFEST_KEYS = ["prax", "name", "kind", "one_liner", "status", "run", "docs", "explainer"]
R_ID = re.compile(r"\bR-(\d{3})\b")
# Tests may cite R-004 or test_R004_...
TEST_ID = re.compile(r"(?<![A-Za-z])R-?(\d{3})(?!\d)")
PLACEHOLDER = re.compile(r"<name>|<one-liner|R-001 \| The <component>")
TEXT_SUFFIXES = {".py", ".js", ".ts", ".go", ".rs", ".java", ".sh", ".md", ".html", ".txt", ".yaml", ".yml", ".json"}


def spec_requirements(spec_text):
    """R-ids defined in SPEC.md: those that start a table row or a heading/bullet."""
    ids = set()
    for line in spec_text.splitlines():
        s = line.strip()
        if s.startswith(("|", "#", "-", "*")):
            m = R_ID.search(s[:20])
            if m:
                ids.add(m.group(1))
    return ids


def manual_requirements(spec_text):
    """R-ids whose spec row says the check is manual."""
    ids = set()
    for line in spec_text.splitlines():
        if "manual" in line.lower():
            m = R_ID.search(line.strip()[:20])
            if m:
                ids.add(m.group(1))
    return ids


def cited_in_tests(tests_dir):
    ids = set()
    if not tests_dir.is_dir():
        return ids
    for p in tests_dir.rglob("*"):
        if p.is_file() and p.suffix in TEXT_SUFFIXES:
            try:
                ids |= set(TEST_ID.findall(p.read_text(errors="ignore")))
            except OSError:
                pass
    return ids


def check(repo, level):
    problems, notes = [], []
    for f in REQUIRED_FILES:
        p = repo / f
        if not p.is_file():
            problems.append(f"missing {f}")
        elif p.stat().st_size < 120 and f != "prax.yaml":
            problems.append(f"{f} is nearly empty")
        elif PLACEHOLDER.search(p.read_text(errors="ignore")):
            problems.append(f"{f} still contains template placeholders")

    manifest = repo / "prax.yaml"
    if manifest.is_file():
        text = manifest.read_text(errors="ignore")
        for key in MANIFEST_KEYS:
            if not re.search(rf"^{key}:", text, re.M):
                problems.append(f"prax.yaml has no '{key}'")

    prompts = repo / "PROMPTS.md"
    if prompts.is_file():
        t = prompts.read_text(errors="ignore")
        for p in ("P-REBUILD", "P-VERIFY"):
            if p not in t:
                problems.append(f"PROMPTS.md has no {p}")
        if not re.search(r"P-0?1\b", t):
            problems.append("PROMPTS.md has no step-by-step prompts (P-01…)")

    spec = repo / "SPEC.md"
    reqs = set()
    if spec.is_file():
        st = spec.read_text(errors="ignore")
        reqs = spec_requirements(st)
        if not reqs:
            problems.append("SPEC.md defines no requirements (R-001…)")
        if not re.search(r"\bK-[\w-]+@\d", st):
            notes.append("SPEC.md names no versioned contract (K-…@n)")
        notes.append(f"{len(reqs)} requirements in SPEC.md")

    readme = repo / "README.md"
    if readme.is_file() and "```" not in readme.read_text(errors="ignore"):
        problems.append("README.md has no quickstart commands")

    if level == "silver":
        for p in SILVER_PATHS:
            if not (repo / p).exists():
                problems.append(f"silver: missing {p}")
        data = repo / "demo" / "data"
        if not data.is_dir() or not any(data.iterdir()):
            problems.append("silver: demo/data/ has no recorded demo data")
        if reqs:
            covered = cited_in_tests(repo / "tests") | manual_requirements(spec.read_text(errors="ignore"))
            missing = sorted(reqs - covered)
            if missing:
                problems.append("silver: requirements with no test or manual check: "
                                + ", ".join(f"R-{m}" for m in missing))
            notes.append(f"{len(reqs & covered)}/{len(reqs)} requirements covered")

    return problems, notes


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("repo", type=Path)
    ap.add_argument("--level", choices=["bronze", "silver"], default="bronze")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    problems, notes = check(a.repo, a.level)
    ok = not problems
    if a.json:
        print(json.dumps({"repo": str(a.repo), "level": a.level, "ok": ok,
                          "problems": problems, "notes": notes}, indent=2))
    else:
        print(f"{a.repo}: {'PASS' if ok else 'FAIL'} ({a.level})")
        for p in problems:
            print(f"  ✗ {p}")
        for n in notes:
            print(f"  · {n}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
