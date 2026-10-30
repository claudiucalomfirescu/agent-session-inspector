"""Call any system tool by hand, as a given persona.

    python -m apps.cli                                  # list personas and their tool counts
    python -m apps.cli tom-becker                       # list Tom's tools
    python -m apps.cli tom-becker crm_list_leads '{"assigned_to": "me"}'
"""
import json
import sys

from apps.common import personas
from apps.tools import Toolset


def main(argv):
    if not argv:
        for pid, p in personas().items():
            print(f"{pid:16s} {p['role']:40s} {len(Toolset(pid).specs):3d} tools  {', '.join(p.get('systems', []))}")
        return 0
    ts = Toolset(argv[0])
    if len(argv) == 1:
        for s in ts.specs:
            f = s["function"]
            print(f"{f['name']:36s} {f['description']}")
        return 0
    out = ts.call(argv[1], argv[2] if len(argv) > 2 else "{}")
    print(json.dumps(json.loads(out), indent=2, ensure_ascii=False))
    return 1 if '"error"' in out[:12] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
