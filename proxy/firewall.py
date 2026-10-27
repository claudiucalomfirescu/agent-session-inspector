"""Deep session inspection: the proxy reads every conversation and can answer in the LLM's place.

Lesson 8 (sensitive topics) is the detection half, lesson 9 (proxy firewall) the enforcement half.

For each chat completion the proxy calls:
  inspect_request(...)   on what the agent is about to send (the new user/tool messages of this turn)
  inspect_response(...)  on what the LLM answered (assistant text and tool-call arguments)
Each returns a Decision with a level (None / info / warning / block) and the findings ("hits").

Detection runs in three layers, cheapest first:
  1. keyword          single regexes from firewall_topics.yaml (`any:` rules)
  2. intent_heuristic co-occurrence rules (`all:` rules): several ideas in the same text
  3. intent_llm       an LLM classifier, asked only when layer 1 or 2 found something and the level
                      is below block. It goes through the gateway (same budget, same cache) and is
                      skipped, falling back to layers 1-2, when the free budget is tight.
The final level is the highest one any layer gives; the LLM can raise a level but never lower it.
A session that reaches `warnings_to_block` warnings on one topic is blocked (detector "escalation").

On block the proxy does not forward the request. It answers itself with a normal chat completion
whose text says the conversation was blocked (block_completion), marks the session blocked, and
answers every later request of that session the same way until an administrator unblocks it.

Configuration (environment variables):
  FIREWALL               on|off       (default: on)
  FIREWALL_TOPICS        topics file  (default: proxy/firewall_topics.yaml)
  FIREWALL_INTENT        auto|llm|heuristic|off  (default: auto = LLM when the budget allows)
  FIREWALL_INTENT_MIN_FREE   free requests that must be left today to use the LLM check (default: 200)
  FIREWALL_DISCLOSE      on|off  add an X-Firewall header to replies (default: on; the body never says
                         it came from the proxy)
"""
import hashlib
import json
import os
import re
import threading
import time
import uuid
from collections import Counter, OrderedDict
from dataclasses import dataclass, field

import yaml

from logstore import now

LEVELS = ["info", "warning", "block"]
RANK = {None: 0, "none": 0, "info": 1, "warning": 2, "block": 3}
HERE = os.path.dirname(os.path.abspath(__file__))


def top(levels):
    return max(levels, key=lambda lv: RANK.get(lv, 0), default=None) or None


def load_topics(path=None):
    with open(path or os.environ.get("FIREWALL_TOPICS") or os.path.join(HERE, "firewall_topics.yaml")) as f:
        cfg = yaml.safe_load(f)
    for tid, t in cfg["topics"].items():
        t["id"] = tid
        for r in t["rules"]:
            assert r["level"] in LEVELS, f"{tid}/{r['id']}: bad level {r['level']}"
            r["detector"] = "intent_heuristic" if "all" in r else "keyword"
            r["regex"] = [re.compile(p, re.I | re.S) for p in (r.get("all") or r.get("any"))]
    return cfg


def _content_text(content):
    if isinstance(content, list):  # [{"type": "text", "text": ...}, ...]
        return "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content or ""


def request_text(req):
    """The part of a request that is new this turn: user/tool messages after the last assistant
    message. The system prompt is skipped (a persona prompt may describe its own risks), and older
    turns were already inspected when they were new."""
    msgs = req.get("messages") or []
    last = max((i for i, m in enumerate(msgs) if m.get("role") == "assistant"), default=-1)
    return "\n".join(_content_text(m.get("content")) for m in msgs[last + 1:] if m.get("role") in ("user", "tool"))


def response_text(resp):
    msg = ((resp.get("choices") or [{}])[0] or {}).get("message") or {}
    parts = [_content_text(msg.get("content"))]
    for c in msg.get("tool_calls") or []:
        fn = c.get("function") or {}
        parts.append(f"{fn.get('name')}({fn.get('arguments')})")
    return "\n".join(p for p in parts if p)


def turn_of(req):
    return 1 + sum(1 for m in req.get("messages") or [] if m.get("role") == "assistant")


@dataclass
class Decision:
    direction: str
    session: str
    agent: str
    turn: int
    hits: list = field(default_factory=list)
    level: str = None
    topic: str = None
    ref: str = None
    actions: list = field(default_factory=list)  # admin_actions rows to write

    @property
    def blocked(self):
        return self.level == "block"


class Firewall:
    def __init__(self, store, llm=None, budget_ok=None, topics=None, intent_mode=None, min_free=None):
        """store: LogStore.  llm(messages) -> answer text or None: the classifier's way to the model.
        budget_ok() -> bool: whether the LLM check may spend a request now."""
        self.store, self.llm, self.budget_ok = store, llm, budget_ok or (lambda: True)
        self.cfg = topics or load_topics()
        self.topics = self.cfg["topics"]
        self.intent_mode = (intent_mode or os.environ.get("FIREWALL_INTENT", "auto")).lower()
        self.min_free = int(min_free if min_free is not None else os.environ.get("FIREWALL_INTENT_MIN_FREE", 200))
        self.lock = threading.Lock()
        self.blocked = {}        # session -> {"topic", "ref", "ts", "agent"}
        self.warnings = Counter()  # (session, topic) -> warnings so far
        self.intent_cache = OrderedDict()
        self.stats = Counter()
        self._restore()

    # ---- state ----------------------------------------------------------------------------------
    def _restore(self):
        """Rebuild blocked sessions from admin_actions, so a proxy restart does not reopen them."""
        try:
            rows = self.store.query("SELECT session, agent, action, topic, ref, ts FROM admin_actions "
                                    "WHERE action IN ('block_session', 'unblock_session') ORDER BY id")
        except Exception:  # noqa: BLE001
            rows = []
        for r in rows:
            if r["action"] == "block_session":
                self.blocked[r["session"]] = {"topic": r["topic"], "ref": r["ref"], "ts": r["ts"], "agent": r["agent"]}
            else:
                self.blocked.pop(r["session"], None)

    def is_blocked(self, session):
        return self.blocked.get(session)

    # ---- detection ------------------------------------------------------------------------------
    def scan(self, text):
        """Layers 1 and 2: every rule that fires, with what it matched."""
        hits = []
        if not text.strip():
            return hits
        for t in self.topics.values():
            for r in t["rules"]:
                found = [rx.search(text) for rx in r["regex"]]
                ok = all(found) if r["detector"] == "intent_heuristic" else any(found)
                if ok:
                    m = [f.group(0) for f in found if f]
                    first = min((f for f in found if f), key=lambda f: f.start())
                    hits.append({"topic": t["id"], "rule": r["id"], "level": r["level"], "detector": r["detector"],
                                 "matched": " + ".join(dict.fromkeys(x.strip()[:60] for x in m)),
                                 "excerpt": _excerpt(text, first.start(), first.end())})
        return hits

    def _use_llm(self):
        if self.llm is None or self.intent_mode in ("off", "heuristic"):
            return False
        return self.intent_mode == "llm" or self.budget_ok()

    def classify(self, text, candidates):
        """Layer 3: ask the LLM which topic (if any) the text's intent matches. Cached by text."""
        key = hashlib.sha256(text.encode()).hexdigest()
        if key in self.intent_cache:
            self.stats["intent_cache_hits"] += 1
            return self.intent_cache[key]
        topics = "\n".join(f"- {t['id']}: {' '.join(t['intent'].split())}" for t in self.topics.values())
        system = ("You are the compliance classifier of VXC Motors, a BMW dealership. Read the TEXT, which is "
                  "part of a conversation between a staff member's AI assistant and the LLM, and decide whether "
                  "its intent matches one of these sensitive topics:\n" + topics +
                  "\n\nLevels: block = the text clearly carries out or requests the forbidden action; "
                  "warning = it is heading there, asks how to, or discusses doing it; info = it only mentions "
                  "the subject in a legitimate way; none = unrelated.\n"
                  'Reply with JSON only: {"topic": "<topic id or none>", "level": "none|info|warning|block", '
                  '"confidence": <0..1>, "rationale": "<one short sentence>"}')
        user = f"Keyword rules flagged: {', '.join(sorted(candidates))}\n\nTEXT:\n{text[:4000]}"
        self.stats["intent_llm_calls"] += 1
        answer = None
        try:
            answer = self.llm([{"role": "system", "content": system}, {"role": "user", "content": user}])
        except Exception:  # noqa: BLE001
            pass
        result = _parse_verdict(answer, self.topics)
        if result is None:
            self.stats["intent_llm_failed"] += 1
            return None
        self.intent_cache[key] = result
        while len(self.intent_cache) > 2000:
            self.intent_cache.popitem(last=False)
        return result

    def _decide(self, direction, agent, session, turn, text):
        d = Decision(direction, session, agent, turn)
        d.hits = self.scan(text)
        if d.hits and top(h["level"] for h in d.hits) != "block":
            if self._use_llm():
                v = self.classify(text, {h["topic"] for h in d.hits})
                if v and RANK[v["level"]] > 0:
                    d.hits.append({"topic": v["topic"], "rule": "llm-classifier", "level": v["level"],
                                   "detector": "intent_llm", "matched": None, "rationale": v["rationale"],
                                   "confidence": v["confidence"], "excerpt": _excerpt(text, 0, 0)})
            else:
                self.stats["intent_llm_skipped"] += 1
        with self.lock:
            for tid in {h["topic"] for h in d.hits if h["level"] == "warning"}:
                self.warnings[(session, tid)] += 1
                n = self.warnings[(session, tid)]
                if n >= self.cfg.get("warnings_to_block", 3):
                    d.hits.append({"topic": tid, "rule": "warnings-to-block", "level": "block",
                                   "detector": "escalation", "matched": None,
                                   "rationale": f"{n} warnings on {tid} in this session", "excerpt": None})
        self._settle(d)
        return d

    def _settle(self, d):
        d.level = top(h["level"] for h in d.hits)
        if d.hits:
            best = max(d.hits, key=lambda h: (RANK[h["level"]], h["detector"] != "intent_llm"))
            d.topic = best["topic"]
        if d.blocked:
            d.ref = "FW-" + uuid.uuid4().hex[:8].upper()
            with self.lock:
                self.blocked[d.session] = {"topic": d.topic, "ref": d.ref, "ts": now(), "agent": d.agent}
            why = "; ".join(f"{h['detector']}:{h['rule']}" for h in d.hits if h["level"] == "block")
            d.actions.append({"actor": "firewall", "action": "block_session", "topic": d.topic, "reason": why})
            if d.direction == "response":
                d.actions.append({"actor": "firewall", "action": "replace_response", "topic": d.topic,
                                  "reason": "LLM answer withheld; agent received the block message"})
        for h in d.hits:
            self.stats[h["level"]] += 1

    def inspect_request(self, agent, session, req):
        """Called before forwarding. A session that is already blocked stays blocked."""
        turn = turn_of(req)
        held = self.is_blocked(session)
        if held:
            d = Decision("request", session, agent, turn, level="block", topic=held["topic"], ref=held["ref"])
            d.hits.append({"topic": held["topic"], "rule": "session-blocked", "level": "block", "detector": "session",
                           "matched": None, "rationale": f"session blocked earlier ({held['ref']})",
                           "excerpt": _excerpt(request_text(req), 0, 0)})
            self.stats["block"] += 1
            return d
        return self._decide("request", agent, session, turn, request_text(req))

    def inspect_response(self, agent, session, req, resp):
        if not isinstance(resp, dict) or "choices" not in resp:
            return Decision("response", session, agent, turn_of(req))
        return self._decide("response", agent, session, turn_of(req), response_text(resp))

    def commit(self, d, call_id=None):
        """Write the decision's signals and actions, now that the call row (if any) has an id."""
        for h in d.hits:
            self.store.insert("signals", {"ts": now(), "session": d.session, "agent": d.agent, "call_id": call_id,
                                          "turn": d.turn, "direction": d.direction, "level": h["level"],
                                          "topic": h["topic"], "detector": h["detector"], "rule": h["rule"],
                                          "matched": h.get("matched"), "rationale": h.get("rationale"),
                                          "confidence": h.get("confidence"), "excerpt": h.get("excerpt"),
                                          "ref": d.ref if h["level"] == "block" else None})
        for a in d.actions:
            self.store.insert("admin_actions", {"ts": now(), "session": d.session, "agent": d.agent,
                                                "ref": d.ref, "call_id": call_id, **a})

    # ---- enforcement ----------------------------------------------------------------------------
    def block_message(self, topic, ref):
        t = self.topics.get(topic) or {"title": topic, "policy": ""}
        return " ".join(self.cfg["block_message"].format(title=t["title"], policy=t["policy"], ref=ref).split())

    def block_completion(self, req, d):
        """(status, headers, body) of an ordinary chat completion carrying the block message, so the
        agent's SDK parses it like any LLM answer. Streams it as SSE if the agent asked for a stream."""
        text = self.block_message(d.topic, d.ref)
        cid, created, model = "gen-" + uuid.uuid4().hex[:24], int(time.time()), req.get("model")
        headers = [("Content-Type", "application/json")]
        if os.environ.get("FIREWALL_DISCLOSE", "on").lower() in ("on", "1", "true", "yes"):
            headers.append(("X-Firewall", f"block; topic={d.topic}; ref={d.ref}"))
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        if req.get("stream"):
            def chunk(delta, finish=None):
                return "data: " + json.dumps({"id": cid, "object": "chat.completion.chunk", "created": created,
                                              "model": model, "choices": [{"index": 0, "delta": delta,
                                                                           "finish_reason": finish}]}) + "\n\n"
            body = chunk({"role": "assistant", "content": text}) + chunk({}, "stop") + "data: [DONE]\n\n"
            headers[0] = ("Content-Type", "text/event-stream")
            return 200, headers, body.encode()
        body = {"id": cid, "object": "chat.completion", "created": created, "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text},
                             "finish_reason": "stop", "native_finish_reason": "stop"}], "usage": usage}
        return 200, headers, json.dumps(body).encode()

    # ---- administrator ----------------------------------------------------------------------------
    def admin(self, action, session, actor, reason=None):
        """An administrator blocks or unblocks a session by hand (or leaves a note)."""
        if action not in ("block_session", "unblock_session", "note"):
            raise ValueError(f"unknown action {action}")
        ref, topic, agent = None, None, None
        with self.lock:
            held = self.blocked.get(session)
            if held:
                topic, agent, ref = held["topic"], held["agent"], held["ref"]
            if action == "block_session":
                ref = "FW-" + uuid.uuid4().hex[:8].upper()
                self.blocked[session] = {"topic": "manual", "ref": ref, "ts": now(), "agent": agent}
                topic = "manual"
            elif action == "unblock_session":
                self.blocked.pop(session, None)
                for k in [k for k in self.warnings if k[0] == session]:
                    del self.warnings[k]
        row = {"ts": now(), "actor": actor or "admin", "action": action, "session": session, "agent": agent,
               "topic": topic, "reason": reason, "ref": ref}
        row["id"] = self.store.insert("admin_actions", row)
        return row

    def status(self):
        return {"intent_mode": self.intent_mode, "llm_available": self.llm is not None,
                "llm_budget_ok": bool(self.llm) and self.budget_ok(),
                "topics": {t["id"]: {"title": t["title"], "rules": len(t["rules"])} for t in self.topics.values()},
                "blocked_sessions": self.blocked, "counters": dict(self.stats)}


def _excerpt(text, start, end, width=160):
    if not text:
        return None
    a = max(0, start - width // 2)
    s = " ".join(text[a:max(end, start) + width // 2].split())
    return ("…" if a else "") + s[:width + 40]


def _parse_verdict(answer, topics):
    if not answer:
        return None
    m = re.search(r"\{.*\}", answer, re.S)
    try:
        v = json.loads(m.group(0)) if m else None
    except ValueError:
        v = None
    if not isinstance(v, dict):
        return None
    level = str(v.get("level", "none")).lower()
    topic = str(v.get("topic", "none"))
    if level not in RANK or (level != "none" and topic not in topics):
        return None
    try:
        conf = float(v.get("confidence", 0))
    except (TypeError, ValueError):
        conf = 0.0
    return {"topic": topic, "level": level, "confidence": conf, "rationale": str(v.get("rationale", ""))[:300]}
