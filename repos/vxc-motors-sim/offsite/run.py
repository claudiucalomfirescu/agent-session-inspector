"""Run the VXC Motors all-staff off-site: a group chat of 12 employee agents and a facilitator agent.

Every message in the room is one LLM call made as that person, through the logging proxy, with the
K-agent-headers@1 identity headers (X-Agent-User = staff id, X-Agent-Dept, X-Session-Id, plus labels
X-Agent-Event: offsite-2026 and X-Agent-Segment). Each employee's system prompt is their intrinsic context
(people/load.py: persona, soul, job, resume) plus the meeting setting; the user message is the chat so far
and the instruction for this turn (offsite/agenda.py). Games and votes are scored by this program, not by
an LLM, so results are exact.

    python3 -m offsite.run --out offsite/runs/2026-10-31            # live, needs the proxy on :8080
    python3 -m offsite.run --fake --out /tmp/offsite-fake            # offline, canned answers, no proxy

Outputs in --out: transcript.jsonl (one room event per line), transcript.md, results.json, factsheet.json,
meta.json. The proxy's own log (PROXY_LOG_DB) is the recorded LLM traffic.
"""
import argparse
import datetime as dt
import json
import os
import random
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from offsite import agenda  # noqa: E402
from people.load import list_people, load_identity, name_and_role  # noqa: E402

MODERATOR = "offsite-moderator"
EVENT = "offsite-2026"
START = dt.datetime(2026, 10, 31, 9, 30)
CONTEXT_MESSAGES = 40
PRIMARY_MODEL = os.environ.get("OFFSITE_PRIMARY_MODEL", "nvidia/nemotron-3.5-super-vl:free")
FALLBACK_MODEL = os.environ.get("OFFSITE_FALLBACK_MODEL", "z-ai/glm-5.3-flash")


def _dept(agent_id):
    path = os.path.join(ROOT, "company", "personas", agent_id + ".md")
    if os.path.isfile(path):
        m = re.search(r"^department:\s*(.+)$", open(path, encoding="utf-8").read(), re.M)
        if m:
            return m.group(1).strip()
    m = re.search(r"^department:\s*(.+)$", open(os.path.join(ROOT, "people", agent_id, "job.md")).read(), re.M)
    return m.group(1).strip() if m else None


def clean(text):
    """Model output -> one chat message: drop reasoning blocks, a leading 'Name:' and wrapping quotes."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    text = re.sub(r"^\*{0,2}[A-Z][\w .'-]{1,40}\*{0,2}:\s+(?=\S)", "", text) if not re.match(
        r"^(IDEA|VOTES|GUESS|COMMIT|THANKS|NEXT|LIE)\b", text) else text
    if len(text) > 1 and text[0] == text[-1] == '"':
        text = text[1:-1].strip()
    return text


def split_next(text, valid):
    """Remove a trailing 'NEXT: a, b' line; return (text, [valid ids in order])."""
    picks = []
    m = re.search(r"\**NEXT\**\s*:\s*([\w\-, `*]+?)\s*$", text)
    if m:
        for tok in re.split(r"[,\s]+", m.group(1)):
            tok = tok.strip(" .`*").lower()
            if tok in valid and tok not in picks:
                picks.append(tok)
        text = (text[:m.start()] + text[m.end():]).strip()
    return text, picks


class Room:
    def __init__(self, out, fake=False, seed=31, min_gap=20.0, model=None, facts=None, call_timeout=90):
        self.out, self.fake, self.min_gap, self.model = out, fake, min_gap, model
        self.rng = random.Random(seed)
        self.people = list_people()
        self.names = {p: name_and_role(p)[0] for p in self.people}
        self.roles = {p: name_and_role(p)[1] for p in self.people}
        self.names[MODERATOR], self.roles[MODERATOR] = "Hannah Brooks", "Facilitator"
        self.events, self.clients, self.results = [], {}, {}
        self.clock, self.last_call, self.segment = START, 0.0, None
        self.facts = facts
        self.call_timeout, self.free_failures, self.fallback_left, self.tripped = call_timeout, 0, 0, False
        self.calls = {"ok": 0, "failed": 0, "models": {}, "prompt_tokens": 0, "completion_tokens": 0}
        with open(os.path.join(HERE, "moderator.md"), encoding="utf-8") as f:
            self.moderator_identity = re.sub(r"^---\n.*?\n---\n", "", f.read(), flags=re.S)
        os.makedirs(out, exist_ok=True)
        self._fh = open(os.path.join(out, "transcript.jsonl"), "w", encoding="utf-8")

    # --- the room ------------------------------------------------------------------------------------
    def post(self, speaker, text, kind="message", hidden=None, call=None):
        self.clock += dt.timedelta(seconds=70 + 6 * min(len(text) // 80, 10))
        ev = {"seq": len(self.events) + 1, "time": self.clock.strftime("%H:%M"), "segment": self.segment,
              "kind": kind, "speaker": speaker, "name": self.names.get(speaker, speaker),
              "role": self.roles.get(speaker, ""), "text": text}
        if hidden:
            ev["hidden"] = hidden
        if call:
            ev["call"] = call
        self.events.append(ev)
        self._fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
        self._fh.flush()
        who = "***" if kind == "scene" else ev["name"]
        print(f"[{ev['time']}] {who}: {text[:160]}", flush=True)
        return ev

    def scene(self, text):
        return self.post("scene", text, kind="scene")

    def context(self):
        lines = []
        for ev in self.events[-CONTEXT_MESSAGES:]:
            if ev["kind"] == "scene":
                lines.append(f"*** {ev['text']} ***")
            else:
                lines.append(f"[{ev['time']}] {ev['name']} ({ev['role']}): {ev['text'][:700]}")
        return "\n".join(lines) or "(the chat is empty)"

    # --- one LLM turn --------------------------------------------------------------------------------
    def system_prompt(self, speaker, facts=False):
        ident = self.moderator_identity if speaker == MODERATOR else load_identity(speaker)
        roster = "\n".join(f"- {self.names[p]} ({p}): {self.roles[p]}" for p in self.people)
        parts = [ident, agenda.SETTING, "Attendees (name, staff id, role):\n" + roster]
        if facts and self.facts:
            parts.append("FACT SHEET (VXC Motors data, year to " + self.facts["as_of"] + "; quote only these figures):\n"
                         + json.dumps(self.facts, indent=1))
        return "\n\n".join(parts)

    def speak(self, speaker, instruction, facts=False, max_tokens=1500):
        system = self.system_prompt(speaker, facts)
        user = (f"Current part of the off-site: {self.segment_title}.\n\nThe chat so far (latest last):\n"
                f"{self.context()}\n\nYour turn, {self.names[speaker]}. {instruction}\n"
                "Write only your chat message.")
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if self.fake:
            return fake_answer(self, speaker, instruction), {"model": "fake"}
        wait = self.min_gap - (time.time() - self.last_call)
        if wait > 0:
            time.sleep(wait)
        self.last_call = time.time()
        from llm import chat
        text, meta = "", {}
        for attempt in range(3):
            model = self.pick_model()
            client = self._client(speaker).with_options(timeout=self.call_timeout)
            t0 = time.time()
            try:
                resp = chat(client, messages, model=model, attempts=1, max_tokens=max_tokens, temperature=0.9,
                            extra_headers={"X-Agent-Segment": self.segment},
                            extra_body={"reasoning": {"effort": "low", "exclude": True}})
                text = clean(resp.choices[0].message.content or "")
                usage = getattr(resp, "usage", None)
                meta = {"model": resp.model, "ms": int(1000 * (time.time() - t0)),
                        "prompt_tokens": getattr(usage, "prompt_tokens", None),
                        "completion_tokens": getattr(usage, "completion_tokens", None)}
                self.model_result(model, ok=bool(text))
                if text:
                    break
            except Exception as e:  # a failed turn should not end the meeting
                meta = {"error": f"{type(e).__name__}: {str(e)[:200]}"}
                self.model_result(model, ok=False)
                print(f"   ! {speaker} via {model}: {meta['error']}", flush=True)
            time.sleep(3)
        if text:
            self.calls["ok"] += 1
            self.calls["models"][meta["model"]] = self.calls["models"].get(meta["model"], 0) + 1
            self.calls["prompt_tokens"] += meta.get("prompt_tokens") or 0
            self.calls["completion_tokens"] += meta.get("completion_tokens") or 0
        else:
            self.calls["failed"] += 1
        return text, meta

    def pick_model(self):
        """Free model first. After 2 free failures in a row, use the paid fallback for the next 15 calls; then
        probe the free model with one call, and go back to the fallback at once if that probe fails."""
        if self.model:
            return self.model
        if self.fallback_left > 0:
            self.fallback_left -= 1
            return FALLBACK_MODEL
        return PRIMARY_MODEL

    def model_result(self, model, ok):
        if model != PRIMARY_MODEL or self.model:
            return
        if ok:
            self.free_failures, self.tripped = 0, False
            return
        self.free_failures += 1
        if self.free_failures >= 2 or self.tripped:
            self.free_failures, self.fallback_left, self.tripped = 0, 15, True
            print("   ! free model failing; using the fallback for the next 15 calls", flush=True)

    def _client(self, speaker):
        if speaker not in self.clients:
            from llm import make_client
            dept = "External" if speaker == MODERATOR else _dept(speaker)
            self.clients[speaker] = make_client(speaker, session_id=f"offsite-20261031-{speaker}", dept=dept,
                                                event=EVENT, role=self.roles[speaker])[0]
        return self.clients[speaker]

    # --- agenda --------------------------------------------------------------------------------------
    def run(self):
        for seg in agenda.SEGMENTS:
            self.segment, self.segment_title = seg["id"], seg["title"]
            self.order = self.people[:]
            self.rng.shuffle(self.order)
            self.scene(f"Agenda: {seg['title']}")
            for step in seg["steps"]:
                self.step(step)
        self._fh.close()

    def fmt(self, instruction, **extra):
        names = ", ".join(self.names[p].split()[0] for p in self.order)
        return instruction.replace("{order_names}", names).format(**extra) if extra else \
            instruction.replace("{order_names}", names)

    def step(self, step, **extra):
        kind = step["kind"]
        if kind == "note":
            self.clock += dt.timedelta(minutes=60)
            self.scene(step["text"])
        elif kind == "say":
            speaker = {"@gm": agenda.GM, "moderator": MODERATOR}.get(step["speaker"], step["speaker"])
            if speaker == "$pick":
                speaker = extra["pick"]
            text, meta = self.speak(speaker, self.fmt(step["instruction"], **extra), facts=step.get("facts"))
            text, _ = split_next(text, set(self.people))
            if text:
                self.post(speaker, text, call=meta)
            else:
                self.scene(f"{self.names[speaker]}'s message did not come through.")
        elif kind == "pick":
            text, meta = self.speak(MODERATOR, step["instruction"])
            text, picks = split_next(text, set(self.people) - {agenda.GM})
            for p in self.rng.sample([p for p in self.people if p != agenda.GM], len(self.people) - 1):
                if len(picks) >= step["count"]:
                    break
                if p not in picks:
                    picks.append(p)
            self.post(MODERATOR, text or "Let's take some questions for Victor.", call=meta,
                      hidden={"picks": picks[:step["count"]]})
            for p in picks[:step["count"]]:
                for sub in step["then"]:
                    self.step(sub, pick=p, asker=self.names[p].split()[0])
        elif kind == "round":
            getattr(self, "round_" + step["game"], self.round_plain)(step)
        elif kind == "tally":
            getattr(self, "tally_" + step["game"])()

    def round_plain(self, step):
        for p in self.order:
            text, meta = self.speak(p, step["instruction"])
            if text:
                self.post(p, text, call=meta)
            self.results.setdefault(step["game"], []).append({"who": p, "text": text})

    # two truths and a lie: each person guesses the previous person's lie, then posts their own three.
    def round_two_truths(self, step):
        game = self.results["two_truths"] = {"turns": [], "guesses": []}
        prev = None
        for p in self.order:
            if prev:
                guess_part = f"First guess which of {self.names[prev].split()[0]}'s three statements is the lie. "
                guess_format = f"GUESS: <1, 2 or 3> <a few words to {self.names[prev].split()[0]}>\n"
            else:
                guess_part, guess_format = "You go first, so there is nothing to guess yet. ", ""
            ins = step["instruction"].replace("{guess_part}", guess_part).replace("{guess_format}", guess_format)
            text, meta = self.speak(p, ins)
            parsed = parse_two_truths(text)
            if prev and parsed["guess"]:
                game["guesses"].append({"by": p, "of": prev, "guess": parsed["guess"]})
            game["turns"].append({"who": p, "statements": parsed["statements"], "lie": parsed["lie"]})
            if text:
                self.post(p, parsed["public"], call=meta, hidden={"lie": parsed["lie"]})
            prev = p
        first, last = self.order[0], self.order[-1]
        text, meta = self.speak(first, f"The round is over. Guess which of {self.names[last].split()[0]}'s three "
                                       "statements is the lie. Answer as: GUESS: <1, 2 or 3> <a few playful words>")
        parsed = parse_two_truths(text)
        if parsed["guess"]:
            game["guesses"].append({"by": first, "of": last, "guess": parsed["guess"]})
        if text:
            self.post(first, parsed["public"], call=meta)

    def tally_two_truths(self):
        game = self.results["two_truths"]
        lies = {t["who"]: t for t in game["turns"]}
        right, lines = [], []
        for g in game["guesses"]:
            truth = lies.get(g["of"], {}).get("lie")
            g["correct"] = truth is not None and g["guess"] == truth
            if g["correct"]:
                right.append(g["by"])
        fooled = [t["who"] for t in game["turns"] if t["lie"] and not any(
            g["of"] == t["who"] and g["correct"] for g in game["guesses"])]
        for t in game["turns"]:
            if t["lie"] and t["lie"] <= len(t["statements"]):
                lines.append(f"{self.names[t['who']].split()[0]}'s lie was #{t['lie']}: \"{t['statements'][t['lie'] - 1]}\"")
        game["detectives"], game["fooled_everyone"] = right, fooled
        self.scene("Icebreaker results. The lies: " + "; ".join(lines) + ". Correct guesses: "
                   + (", ".join(self.names[p].split()[0] for p in right) or "nobody")
                   + ". Got away with it: " + (", ".join(self.names[p].split()[0] for p in fooled) or "nobody") + ".")

    def tally_ideas(self):
        ideas = []
        for r in self.results.get("ideas", []):
            m = re.search(r"IDEA\s*:\s*\**(.+?)\**\s*$", r["text"] or "", re.M | re.I)
            title = (m.group(1) if m else (r["text"] or "").split("\n")[0])[:80].strip(" *")
            if title:
                ideas.append({"n": len(ideas) + 1, "who": r["who"], "title": title})
        self.results["idea_list"] = ideas
        self.scene("Idea board: " + " | ".join(f"{i['n']}. {i['title']} ({self.names[i['who']].split()[0]})" for i in ideas))

    def tally_votes(self):
        ideas = self.results.get("idea_list", [])
        owner = {i["n"]: i["who"] for i in ideas}
        score = {i["n"]: 0 for i in ideas}
        ballots = []
        for r in self.results.get("votes", []):
            m = re.search(r"VOTES?\s*:\s*([\d ,#and]+)", r["text"] or "", re.I)
            nums = [int(x) for x in re.findall(r"\d+", m.group(1))] if m else []
            valid = [n for n in dict.fromkeys(nums) if n in score and owner[n] != r["who"]][:2]
            for n in valid:
                score[n] += 1
            ballots.append({"who": r["who"], "votes": valid})
        ranked = sorted(ideas, key=lambda i: (-score[i["n"]], i["n"]))
        for i in ranked:
            i["votes"] = score[i["n"]]
        self.results["vote"] = {"ballots": ballots, "ranking": ranked}
        self.scene("Vote result: " + " | ".join(
            f"{i['title']} ({self.names[i['who']].split()[0]}): {i['votes']}" for i in ranked[:5]))


def parse_two_truths(text):
    text = text or ""
    guess = re.search(r"GUESS\s*:\s*#?(\d)", text, re.I)
    lie = re.search(r"LIE\s*:\s*#?(\d)", text, re.I)
    statements = [m.strip(" *") for _, m in re.findall(r"^\s*\**([1-3])[.)]\**\s*(.+)$", text, re.M)]
    public = re.sub(r"^\s*\**LIE\**\s*:.*$", "", text, flags=re.M | re.I).strip()
    return {"guess": int(guess.group(1)) if guess else None, "lie": int(lie.group(1)) if lie else None,
            "statements": statements[:3], "public": public}


def fake_answer(room, speaker, instruction):
    """Deterministic stand-in for the LLM, so the runner, the games and the replay can be tested offline."""
    first = room.names[speaker].split()[0]
    n = len(room.events)
    if speaker == MODERATOR:
        if "NEXT:" in instruction and "four" in instruction:
            picks = [p for p in room.people if p != agenda.GM][:4]
            return f"Questions for Victor, please! {room.names[picks[0]].split()[0]}, you're first.\nNEXT: " + ", ".join(picks)
        return f"(Hannah) Moving on, everyone. Step {n}."
    if "two truths" in instruction:
        g = "GUESS: 2 I think that one's made up!\n" if "GUESS:" in instruction else ""
        return f"{g}1. I am {first}.\n2. I work at VXC Motors.\n3. I have been to the moon.\nLIE: 3"
    if "GUESS:" in instruction:
        return "GUESS: 3 has to be the lie"
    if "IDEA:" in instruction:
        return f"IDEA: {first}'s better handover\nMake every handover feel special."
    if "VOTES:" in instruction:
        mine = next((i["n"] for i in room.results.get("idea_list", []) if i["who"] == speaker), 0)
        picks = [i["n"] for i in room.results.get("idea_list", []) if i["n"] != mine][:2]
        return "VOTES: " + ", ".join(map(str, picks)) + "\nThey help customers most."
    if "COMMIT:" in instruction:
        return f"COMMIT: {first} will call every customer back the same day.\nTHANKS: Maria for keeping us organised"
    if "ONE sentence" in instruction:
        return f"Then {first} made sure Sam's day got even better."
    return f"{first} here: message {n}."


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--fake", action="store_true", help="canned answers, no proxy, no key")
    ap.add_argument("--seed", type=int, default=31)
    ap.add_argument("--min-gap", type=float, default=float(os.environ.get("OFFSITE_MIN_GAP_S", 20)),
                    help="seconds between LLM call starts (20 = at most 3 per minute)")
    ap.add_argument("--model", default=None, help="always ask for this model (default: free model, paid fallback)")
    ap.add_argument("--timeout", type=float, default=90, help="seconds before a call is abandoned")
    ap.add_argument("--facts", default=None, help="fact sheet JSON to use instead of computing it from data/")
    a = ap.parse_args(argv)
    if a.facts:
        facts = json.load(open(a.facts))
    else:
        from offsite import factsheet
        facts = factsheet.build()
    room = Room(a.out, fake=a.fake, seed=a.seed, min_gap=a.min_gap, model=a.model, facts=facts, call_timeout=a.timeout)
    started = dt.datetime.now(dt.timezone.utc)
    room.run()
    json.dump(facts, open(os.path.join(a.out, "factsheet.json"), "w"), indent=2, default=str)
    json.dump(room.results, open(os.path.join(a.out, "results.json"), "w"), indent=2, ensure_ascii=False)
    meta = {"event": EVENT, "fake": a.fake, "seed": a.seed, "started_utc": started.isoformat(timespec="seconds"),
            "finished_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "attendees": room.people, "moderator": MODERATOR, "messages": len(room.events), "calls": room.calls}
    json.dump(meta, open(os.path.join(a.out, "meta.json"), "w"), indent=2)
    write_markdown(room.events, os.path.join(a.out, "transcript.md"))
    print(json.dumps(meta["calls"]))


def write_markdown(events, path):
    lines = ["# VXC Motors off-site · 31 October 2026 · transcript", "",
             "All-staff off-site at The Old Mill, held in a group chat. Every message below is one LLM call made "
             "as that person through the logging proxy. Scene lines (in italics) are written by the meeting software.", ""]
    seg = None
    for ev in events:
        if ev["segment"] != seg:
            seg = ev["segment"]
            title = next(s["title"] for s in agenda.SEGMENTS if s["id"] == seg)
            lines += ["", f"## {title}", ""]
        if ev["kind"] == "scene":
            if not ev["text"].startswith("Agenda:"):
                lines += [f"*{ev['time']} · {ev['text']}*", ""]
        else:
            body = ev["text"].replace("\n", "  \n")
            lines += [f"**{ev['time']} · {ev['name']}** ({ev['role']})  \n{body}", ""]
    open(path, "w", encoding="utf-8").write("\n".join(lines))


def reclean(run_dir):
    """Re-apply the message cleaning (R-OFF-011) to a recorded run and rewrite transcript.md.
    Used once on the 2026-10-31 run, whose first build missed a NEXT: written at the end of a line."""
    path = os.path.join(run_dir, "transcript.jsonl")
    events = [json.loads(l) for l in open(path, encoding="utf-8")]
    staff = set(list_people())
    for ev in events:
        if ev["kind"] == "message":
            ev["text"] = split_next(clean(ev["text"]), staff)[0]
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(json.dumps(ev, ensure_ascii=False) + "\n" for ev in events)
    write_markdown(events, os.path.join(run_dir, "transcript.md"))


if __name__ == "__main__":
    if sys.argv[1:2] == ["--reclean"]:
        reclean(sys.argv[2])
    else:
        main()
