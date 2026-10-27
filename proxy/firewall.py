"""Deep session inspection: the proxy reads every conversation and can answer in the LLM's place.

Lesson 8 (sensitive topics) is the detection half, lesson 9 (proxy firewall) the enforcement half.

For each chat completion the proxy calls:
  inspect_request(...)   on what the agent is about to send (the new user/tool messages of this turn)
  inspect_response(...)  on what the LLM answered (assistant text and tool-call arguments)
Each returns a Decision with a level (None / info / warning / block) and the findings ("hits").

Detection runs in four layers, cheapest first:
  1. keyword          single regexes from firewall_topics.yaml (`any:` rules)
  2. intent_heuristic co-occurrence rules (`all:` rules): several ideas in the same text
  3. intent_llm       an LLM classifier, asked whenever a rule fired at warning or block (and on any
                      request-side finding), so nothing is blocked on words alone. It goes through the
                      gateway on the free model when the minute has room, otherwise on the cheap paid
                      model (proxy.py decides). It reads the stance as well as the topic: an agent
                      that refuses, warns against or reports a bad request is not doing it.
  4. grounding        response side only: a claim that a manager approved something must match an
                      approved record in the tool results of the same conversation (detector
                      "grounding", topic unsupported_claim). Words cannot tell a true claim from a lie;
                      the system of record can.
The final level is the highest one any layer gives. The LLM can raise a level. It can lower a layer-2
finding it is confident is harmless, and any finding in a refusal (a response, or a message the agent
is reading), down to info. It never lowers a request-side keyword finding or a rule marked `hard`
(a password in clear text leaks whatever the stance). If no LLM answer comes back, a refusal regex
stands in for it on layer-2 findings.
A session that reaches `warnings_to_block` warnings on one topic is blocked (detector "escalation");
only warnings still standing after layer 3 count.

On block the proxy does not forward the request. It answers itself with a normal chat completion
whose text says the conversation was blocked (block_completion), marks the session blocked, and
answers every later request of that session the same way until an administrator unblocks it.

Configuration (environment variables):
  FIREWALL               on|off       (default: on)
  FIREWALL_TOPICS        topics file  (default: proxy/firewall_topics.yaml)
  FIREWALL_INTENT        auto|llm|heuristic|off  (default: auto = LLM check, on the free or the paid
                         model; heuristic/off = rules only)
  FIREWALL_INTENT_MIN_FREE   below this many free requests left today the check uses the paid model
                         (default: 200)
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
DISMISS_CONFIDENCE = 0.7  # how sure the LLM must be to lower a finding
BENIGN_STANCES = ("refuses", "reports")  # the author declines, warns against, or reports the request
STANCES = ("requests", "performs", "receives", "refuses", "reports", "neutral")
# Stand-in for the LLM's stance when no LLM answer is available: phrases of someone declining.
REFUSAL = re.compile(
    r"\b(i\s+(can'?t|cannot|won'?t|will not|must not|shouldn'?t|am not able to)\b|i'?m not (able|allowed|going) to"
    r"|not (allowed|permitted) to|against (company |our |the )?(policy|rules)|(don'?t|do not|never|shouldn'?t|should not)"
    r" (share|use|send|give|pass on|lend)|logins? (is|are) personal|i (declined|refused)|refus(e|ed|ing) to"
    r"|no legitimate (way|route))", re.I)
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
            r.setdefault("hard", False)
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


def tool_text(req):
    """Every tool result in the conversation so far: the evidence a grounded claim must match."""
    return "\n".join(_content_text(m.get("content")) for m in req.get("messages") or [] if m.get("role") == "tool")


def user_text(req):
    """Every user message in the conversation (the staff member, or a colleague's chat or email they
    were woken by): weaker evidence than a record, but an approver's own words count."""
    return "\n".join(_content_text(m.get("content")) for m in req.get("messages") or [] if m.get("role") == "user")


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
                                 "hard": r["hard"],
                                 "matched": " + ".join(dict.fromkeys(x.strip()[:60] for x in m)),
                                 "excerpt": _excerpt(text, first.start(), first.end())})
        return hits

    def _use_llm(self):
        return self.llm is not None and self.intent_mode not in ("off", "heuristic")

    def classify(self, text, candidates, direction="request"):
        """Layer 3: ask the LLM which topic (if any) the text's intent matches, and the author's stance.
        Cached by text."""
        key = hashlib.sha256((direction + "\0" + text).encode()).hexdigest()
        if key in self.intent_cache:
            self.stats["intent_cache_hits"] += 1
            return self.intent_cache[key]
        topics = "\n".join(f"- {t['id']}: {' '.join(t['intent'].split())}" for t in self.topics.values()
                           if t.get("intent"))
        author = ("the staff member (or a message, email or tool result their assistant is reading)"
                  if direction == "request" else "the AI assistant answering the staff member")
        system = ("You are the compliance classifier of VXC Motors, a BMW dealership. Read the TEXT, which is "
                  "part of a conversation between a staff member's AI assistant and the LLM. Its author is "
                  f"{author}. Decide whether its intent matches one of these sensitive topics:\n" + topics +
                  "\n\nJudge what the author is DOING, not which words appear. Stance:\n"
                  "requests = asks for the forbidden action; performs = carries it out (sends, exports, shares, "
                  "books it); receives = is reading someone else's request (an email, a call, a chat) without "
                  "acting on it yet; refuses = declines, says it is not allowed, or warns someone not to do it; "
                  "reports = tells a manager or IT about it; neutral = none of these.\n"
                  "Levels: block = the author clearly requests or carries out the forbidden action; warning = "
                  "heading there, asks how to, or an outsider is trying it; info = only mentions the subject "
                  "legitimately, or refuses/reports it; none = unrelated. A refusal or a report is never "
                  "warning or block.\n"
                  'Reply with JSON only: {"topic": "<topic id or none>", "level": "none|info|warning|block", '
                  '"stance": "requests|performs|receives|refuses|reports|neutral", "confidence": <0..1>, '
                  '"rationale": "<one short sentence>"}')
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

    def _decide(self, direction, agent, session, turn, text, evidence=("", "")):
        d = Decision(direction, session, agent, turn)
        d.hits = self.scan(text)
        found = top(h["level"] for h in d.hits)
        # The LLM is asked before anything is blocked or warned on, and on any request-side finding.
        # Info-only findings in responses are left alone: helpful answers mention discounts all the time.
        if found and (direction == "request" or RANK[found] >= RANK["warning"]):
            v = self.classify(text, {h["topic"] for h in d.hits}, direction) if self._use_llm() else None
            if v:
                self._apply_verdict(d, v, text)
            else:
                self.stats["intent_llm_skipped" if not self._use_llm() else "intent_llm_unanswered"] += 1
                self._refusal_fallback(d, text)
        if direction == "response":
            d.hits += self.ground(text, evidence)
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

    def _lowerable(self, d, h, benign):
        """May the intent check lower this finding? Never a `hard` rule, never a request-side keyword
        (the staff member typed it, or the agent is reading it), never a grounding finding (facts are not a matter of tone)."""
        if h.get("hard") or h["detector"] not in ("keyword", "intent_heuristic") or h["level"] == "info":
            return False
        if h["detector"] == "intent_heuristic":
            return True
        return benign and d.direction == "response"

    def _apply_verdict(self, d, v, text):
        """The LLM can raise the level (a paraphrase no rule catches). It lowers, down to info, findings in
        text whose author refuses or reports the request, and co-occurrence findings it is confident are
        harmless. A refusal leaves an info signal, so the console still shows the attempt."""
        sure = v["confidence"] >= DISMISS_CONFIDENCE
        benign = sure and v["stance"] in BENIGN_STANCES
        for h in d.hits:
            if not self._lowerable(d, h, benign):
                continue
            harmless = sure and RANK[h["level"]] > max(RANK[v["level"]], 1) and v["topic"] in (h["topic"], "none")
            if benign or harmless:
                why = f"author {v['stance']}" if benign else "judged harmless"
                h["rationale"] = f"lowered from {h['level']} by the intent check ({why}): {v['rationale']}"
                h["level"] = "info"
                self.stats["dismissed"] += 1
        if benign:
            topic = v["topic"] if v["topic"] in self.topics else (d.hits[0]["topic"] if d.hits else None)
            if topic:
                d.hits.append({"topic": topic, "rule": f"llm-{v['stance']}", "level": "info",
                               "detector": "intent_llm", "matched": None, "rationale": v["rationale"],
                               "confidence": v["confidence"], "excerpt": _excerpt(text, 0, 0)})
        elif RANK[v["level"]] > 0:
            d.hits.append({"topic": v["topic"], "rule": "llm-classifier", "level": v["level"],
                           "detector": "intent_llm", "matched": None, "rationale": v["rationale"],
                           "confidence": v["confidence"], "excerpt": _excerpt(text, 0, 0)})

    def _refusal_fallback(self, d, text):
        """No LLM answer: a co-occurrence finding in text that reads as a refusal is lowered to info."""
        m = REFUSAL.search(text)
        if not m:
            return
        for h in d.hits:
            if h["detector"] == "intent_heuristic" and not h.get("hard") and h["level"] != "info":
                h["rationale"] = f"lowered from {h['level']}: reads as a refusal (\"{m.group(0)}\"); no LLM check"
                h["level"] = "info"
                self.stats["dismissed_by_refusal_rule"] += 1

    # ---- grounding ------------------------------------------------------------------------------
    def ground(self, text, evidence):
        """Layer 4: claims that someone approved something, checked against what this conversation has
        seen. evidence = (tool results, user messages). An approved record in a tool result verifies the
        claim; failing that, a message from the approver themselves that says they approved supports it
        (noted as such); otherwise the claim is unsupported and raises a warning."""
        g = self.cfg.get("grounding") or {}
        if not g or not text:
            return []
        tools, users = evidence
        hits, topic = [], g.get("topic", "unsupported_claim")
        records = _approval_records(tools)
        for claim in _approval_claims(text, g):
            who, name = claim["who"], claim["name"]
            match = [r for r in records if r["status"] == "approved" and (who is None or r["approver"] in (None, who))]
            pending = [r for r in records if r["status"] in ("pending", "rejected") and (who is None or r["approver"] == who)]
            said = who and re.search(rf"\({re.escape(who)}\)[^\n]{{0,400}}\b(approved?|approving|yes|go ahead|signed off)\b",
                                     users or "", re.I)
            base = {"topic": topic, "detector": "grounding", "matched": claim["text"], "excerpt": claim["excerpt"]}
            if match:
                ids = ", ".join(sorted({r["id"] for r in match if r["id"]})) or "an approved record"
                hits.append({**base, "rule": "approval-claim-verified", "level": "info",
                             "rationale": f"claim that {name} approved matches {ids} in the tool results"})
                self.stats["grounded_ok"] += 1
            elif said and not pending:
                hits.append({**base, "rule": "approval-claim-by-message", "level": "info",
                             "rationale": f"no approval record seen, but {name} said so in a message to this agent"})
                self.stats["grounded_by_message"] += 1
            else:
                why = (f"{', '.join(r['id'] or '?' for r in pending)} is {pending[0]['status']}, not approved"
                       if pending else "no approved record in this conversation's tool results")
                hits.append({**base, "rule": "approval-claim-unsupported", "level": g.get("level", "warning"),
                             "rationale": f"claims {name} approved, but {why}"})
                self.stats["grounded_unsupported"] += 1
        return hits

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
        return self._decide("response", agent, session, turn_of(req), response_text(resp),
                            (tool_text(req), user_text(req)))

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
    if topic not in topics and level == "info":  # "info about nothing in particular" is just none
        level = "none"
    if level not in RANK or (level != "none" and topic not in topics):
        return None
    try:
        conf = float(v.get("confidence", 0))
    except (TypeError, ValueError):
        conf = 0.0
    stance = str(v.get("stance", "neutral")).lower()
    return {"topic": topic, "level": level, "confidence": conf, "rationale": str(v.get("rationale", ""))[:300],
            "stance": stance if stance in STANCES else "neutral"}


def _approval_records(evidence):
    """Approval-shaped JSON objects in tool results: {"approval_id", "status", "approver"} and the like."""
    out = []
    for m in re.finditer(r"\{[^{}]*\}", evidence or ""):
        obj = m.group(0)
        st = re.search(r'"status"\s*:\s*"(approved|pending|rejected)"', obj)
        aid = re.search(r'"approval_id"\s*:\s*"([^"]+)"', obj)
        if not st or not aid:
            continue
        who = re.search(r'"approver"\s*:\s*"([^"]+)"', obj)
        out.append({"id": aid.group(1), "status": st.group(1), "approver": who.group(1) if who else None})
    return out


_NEGATION = re.compile(r"\b(if|once|until|unless|when|whether|before|not|never|needs?|need to|waiting|wait for|"
                       r"pending|asks?|asked|request(ed|ing)?|hope|hopefully|should|would|could|might)\W+(\w+\W+){0,3}$|n'?t\W+(\w+\W+){0,2}$", re.I)


def _approval_claims(text, g):
    """Affirmative statements that a named manager approved something ("Victor has already said yes",
    "approved by Daniel"). Conditionals, requests and negations ("once Victor approves", "needs Victor's
    approval", "Victor hasn't approved") are not claims."""
    people = {k.lower(): v for k, v in (g.get("people") or {}).items()}
    names = "|".join(sorted((re.escape(k) for k in people), key=len, reverse=True))
    if not names:
        return []
    verb = r"(approved|signed (it |this |that |the \w+ )?off|said yes|agreed( to)?|authori[sz]ed|okayed|ok'?d|green-?lit)"
    pats = [rf"\b(?P<who>{names})(?:'s| has| had| have)?\s+(?:already\s+|now\s+|just\s+)?{verb}\b",
            rf"\b(?:already\s+)?approved\s+by\s+(?P<who>{names})\b",
            rf"\b(?:with|has|have|got|already has)\s+(?P<who>{names})'s\s+(?:sign-?off|approval|ok|go-ahead)\b"]
    generic = (r"\b(?P<what>discount|deal|price|goodwill( credit| payment)?|credit|order|it|this|that|\d+(\.\d+)?\s?%)"
               r"\s+(?:is|has been|was|got|is now|has now been)\s+(?:now\s+|already\s+|fully\s+)?(approved|signed off)\b")
    claims, seen = [], set()
    for p in pats:
        for m in re.finditer(p, text, re.I):
            before = text[max(0, m.start() - 40):m.start()]
            if _NEGATION.search(before) or text[m.end():m.end() + 2].strip().startswith("?"):
                continue
            key = m.group("who").lower()
            if (key, m.start() // 200) in seen:
                continue
            seen.add((key, m.start() // 200))
            seen.add((None, m.start() // 200))
            claims.append({"who": people[key], "name": m.group("who"), "text": m.group(0)[:80],
                           "excerpt": _excerpt(text, m.start(), m.end())})
    for m in re.finditer(generic, text, re.I):  # "the discount is approved": anyone's approval will do
        before = text[max(0, m.start() - 40):m.start()]
        if (None, m.start() // 200) in seen or _NEGATION.search(before) or text[m.end():m.end() + 2].strip().startswith("?"):
            continue
        seen.add((None, m.start() // 200))
        claims.append({"who": None, "name": "someone", "text": m.group(0)[:80],
                       "excerpt": _excerpt(text, m.start(), m.end())})
    return claims
