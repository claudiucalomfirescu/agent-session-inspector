"""echo-log: return a message and append it to a JSONL log (K-echo-log@1)."""
import json
import sys
from datetime import datetime, timezone


def echo(msg, log_path="log.jsonl"):
    with open(log_path, "a") as f:
        f.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), "msg": msg}) + "\n")
    return msg


def replay(log_path):
    with open(log_path) as f:
        for line in f:
            print(json.loads(line)["msg"])


if __name__ == "__main__":
    if sys.argv[1:2] == ["--replay"]:
        replay(sys.argv[2])
    else:
        print(echo(" ".join(sys.argv[1:])))
