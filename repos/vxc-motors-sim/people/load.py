"""Load an employee's intrinsic context: resume, job description, persona and soul.

    from people.load import load_identity, list_people
    system_prompt = load_identity("tom-becker") + "\n\n" + task_prompt

Stdlib only. The four files live in people/<id>/{resume,job,persona,soul}.md; each starts with a small
YAML-ish frontmatter block (id, kind, ...) that is stripped here. Facts such as name, role and email stay
in company/personas/<id>.md (the source of truth); this module reads name and role from there when it can.
"""
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PERSONAS = os.path.join(os.path.dirname(HERE), "company", "personas")
PARTS = ("persona", "soul", "job", "resume")  # most behaviour-shaping first

PREAMBLE = """You are {name}, {role} at VXC Motors, a single-site BMW dealership with 12 staff.
Everything below is who you are. Your PERSONA is how you behave in front of colleagues: follow it.
Your SOUL is private: it shapes what you care about and how you react, but you do not recite it.
Your JOB says what you are responsible for and decide; your RESUME is your history and can come up naturally.
Stay in character. Never say you are an AI or a language model."""


def _strip_frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    meta = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        text = text[m.end():]
    return meta, text.strip()


def list_people():
    """Employee ids that have all four identity files, sorted."""
    return sorted(d for d in os.listdir(HERE)
                  if all(os.path.isfile(os.path.join(HERE, d, p + ".md")) for p in PARTS))


def read_part(agent_id, part):
    with open(os.path.join(HERE, agent_id, part + ".md"), encoding="utf-8") as f:
        return _strip_frontmatter(f.read())


def name_and_role(agent_id):
    """(name, role) from company/personas/<id>.md, falling back to the resume heading and job title."""
    path = os.path.join(PERSONAS, agent_id + ".md")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            meta, _ = _strip_frontmatter(f.read())
        if meta.get("name") and meta.get("role"):
            return meta["name"], meta["role"]
    _, resume = read_part(agent_id, "resume")
    job_meta, _ = read_part(agent_id, "job")
    name = re.match(r"#\s*(.+?)\s*·", resume)
    return (name.group(1) if name else agent_id), job_meta.get("title", "employee")


def load_identity(agent_id):
    """The agent's intrinsic context as one system-prompt block."""
    name, role = name_and_role(agent_id)
    blocks = [PREAMBLE.format(name=name, role=role)]
    for part in PARTS:
        _, body = read_part(agent_id, part)
        blocks.append(f"=== YOUR {part.upper()} ===\n{body}")
    return "\n\n".join(blocks)


if __name__ == "__main__":
    import sys
    ids = sys.argv[1:] or list_people()
    for i in ids:
        text = load_identity(i)
        print(f"{i}: {len(text)} chars, ~{len(text) // 4} tokens")
