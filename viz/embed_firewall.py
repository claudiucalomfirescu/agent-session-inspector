"""Snapshot the firewall demo (proxy log + agent logs) into viz/firewall.html, so the page works offline.

    python3 agent/firewall_demo.py      # writes logs/firewall_demo.db and logs/agents/*.jsonl
    python3 viz/embed_firewall.py       # -> viz/data/firewall-demo.json, embedded in viz/firewall.html
    python3 viz/embed_firewall.py viz/data/firewall-demo.json   # re-embed a saved snapshot

Per session and turn: what the agent sent, what came back and from whom (LLM or proxy), the
signals the firewall recorded, and the agent's own log entry for that answer.
"""
import json
import os
import re
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "proxy"))
sys.path.insert(0, ROOT)


def text_of(content):
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


def snapshot(db_path, agent_dir):
    import yaml
    from llm.agentlog import read_log
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    with open(os.path.join(ROOT, "proxy", "firewall_topics.yaml")) as f:
        cfg = yaml.safe_load(f)
    out = {"topics": {k: {"title": v["title"], "policy": v["policy"], "rules": len(v["rules"])}
                      for k, v in cfg["topics"].items()},
           "sessions": [], "actions": [dict(r) for r in db.execute("SELECT * FROM admin_actions ORDER BY id")],
           "classifier_calls": [dict(r) for r in db.execute(
               "SELECT id, ts, duration_ms, status FROM calls WHERE agent='firewall' ORDER BY id")]}
    sessions = db.execute("SELECT session, agent, labels, MIN(id) first FROM calls WHERE agent != 'firewall' "
                          "GROUP BY session ORDER BY first").fetchall()
    for s in sessions:
        events = read_log(s["agent"], s["session"], agent_dir)
        answers = {e["turn"]: e for e in events if e["event"] == "response"}
        calls = db.execute("SELECT * FROM calls WHERE session=? ORDER BY id", (s["session"],)).fetchall()
        turns = []
        for c in calls:
            req, resp = json.loads(c["request"]), json.loads(c["response"])
            turn = 1 + sum(1 for m in req["messages"] if m["role"] == "assistant")
            msg = resp["choices"][0]["message"]
            usage = resp.get("usage") or {}
            turns.append({
                "turn": turn, "ts": c["ts"], "duration_ms": c["duration_ms"], "route": c["route"],
                "level": c["firewall_level"], "sent": text_of(req["messages"][-1].get("content")),
                "answer": msg.get("content") or "", "model": resp.get("model"),
                "tokens": usage.get("total_tokens", 0),
                "signals": [{k: r[k] for k in ("direction", "level", "topic", "detector", "rule", "matched",
                                                "rationale", "confidence", "ref")}
                            for r in db.execute("SELECT * FROM signals WHERE call_id=? ORDER BY id", (c["id"],))],
                "agent_view": {k: answers.get(turn, {}).get(k) for k in ("ts", "content", "firewall")}})
        out["sessions"].append({"session": s["session"], "agent": s["agent"],
                                "labels": json.loads(s["labels"] or "{}"),
                                "system": text_of(json.loads(calls[0]["request"])["messages"][0]["content"]),
                                "turns": turns})
    return out


def embed(page, data):
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        text = text.replace(key, "[REDACTED]")
    text = text.replace("</", "<\\/")
    with open(page) as f:
        html = f.read()
    html, n = re.subn(r'(<script id="fw-data" type="application/json">).*?(</script>)',
                      lambda m: m.group(1) + text + m.group(2), html, count=1, flags=re.S)
    if not n:
        raise SystemExit(f"{page} has no fw-data block")
    with open(page, "w") as f:
        f.write(html)
    print(f"{len(data['sessions'])} sessions embedded in {page}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].endswith(".json"):
        with open(sys.argv[1]) as f:
            data = json.load(f)
    else:
        data = snapshot(os.path.join(ROOT, "logs", "firewall_demo.db"), os.path.join(ROOT, "logs", "agents"))
        os.makedirs(os.path.join(HERE, "data"), exist_ok=True)
        with open(os.path.join(HERE, "data", "firewall-demo.json"), "w") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
    embed(os.path.join(HERE, "firewall.html"), data)
