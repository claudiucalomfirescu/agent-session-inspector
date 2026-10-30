"""Build company/org_chart.html: a self-contained org chart with avatars and personas embedded.

    python company/tools/build_org_chart.py
"""

import json
from pathlib import Path

from load_personas import COMPANY, SYSTEMS, load_all

TEMPLATE = Path(__file__).resolve().parent / "org_chart_template.html"


def main():
    people = load_all()
    avatars = {p["id"]: (COMPANY / p["avatar"]).read_text(encoding="utf-8").strip() for p in people}
    data = {
        "people": people,
        "avatars": avatars,
        "systems": {sid: name for sid, name, _ext, _desc in SYSTEMS},
    }
    # "</" must not appear inside the inline <script>.
    blob = json.dumps(data, default=str, ensure_ascii=False).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*DATA*/null", blob)
    out = COMPANY / "org_chart.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html) // 1024} KB)")


if __name__ == "__main__":
    main()
