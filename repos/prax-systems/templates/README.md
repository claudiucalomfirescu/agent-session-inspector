# <name>

> <one-liner from prax.yaml>

![explainer](explainers/preview.png) <!-- optional still; the real thing is explainers/index.html -->

**Animated explainer:** [explainers/index.html](explainers/index.html) · [published](<artifact link>)

## What it is
Two or three sentences. What problem goes away when you run this.

## 60-second quickstart (no API key)
```bash
git clone <url> && cd <name>
pip install -r requirements.txt
python3 demo/run_demo.py         # opens on recorded demo data
```

## Run it live
```bash
export <KEY>=...
...
```

## How it works
One Mermaid diagram, five bullets. Details: [ARCHITECTURE.md](ARCHITECTURE.md).

## Rebuild it
This repo is built with [Prax Systems](<link>): the code is one rendering of the spec.
[GOAL](GOAL.md) · [SPEC](SPEC.md) · [PROMPTS](PROMPTS.md) (start with P-REBUILD) ·
[ROADMAP](ROADMAP.md) · [DECISIONS](DECISIONS.md)

## Tests
```bash
python3 -m unittest discover -s tests    # offline, fake upstream
```
