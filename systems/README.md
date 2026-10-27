# VXC Motors systems

The dealership's applications as agent tools, plus BMW's partner portal as an external service.
Lesson: [docs/lessons/05-mock-systems.md](../docs/lessons/05-mock-systems.md) ·
data model: [viz/data-model.html](../viz/data-model.html).

| File | What |
|---|---|
| `common.py` | `@tool` registry, `call(actor, tool, args)` (access check, transaction, audit), `Store` (one DuckDB connection per DB), clock (`VXC_NOW`) |
| `rules.py` | Approval limits and rates from company/README.md |
| `crm.py` `dms.py` `workshop.py` `parts.py` `finance.py` `mail.py` | Internal systems, all in `data/vxc.duckdb` |
| `bmw_portal/` | External portal, own DB `data/bmw_portal.duckdb`, clock-driven order status |
| `schema.py` | DDL for both databases |
| `seed.py`, `scenario_today.py`, `catalog.py` | Reproducible history from 2026-01-01 and the open work on the seed morning |
| `tools.py` | `Toolset(persona_id)`: specs + `call()`, in-process or over HTTP (`VXC_INTERNAL_URL`, `VXC_PORTAL_URL`) |
| `server.py` | `python -m systems.server internal` (:8100) / `bmw_portal` (:8200) |
| `cli.py` | `python -m systems.cli <persona> [<tool> '<json args>']` |
| `persona_agent.py` | One persona as an LLM agent through the proxy (building block for the multi-agent workday) |

Tests: `python3 -m unittest -v tests.test_systems`.
