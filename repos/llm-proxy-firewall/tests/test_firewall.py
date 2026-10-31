"""The firewall: detection layers on crafted messages, and the proxy end to end against a fake provider.

    python3 -m unittest -v tests.test_firewall
"""
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from helpers import ROOT, get_json, post, rows, start_proxy

sys.path.insert(0, os.path.join(ROOT, "proxy"))
from firewall import Firewall, load_topics  # noqa: E402
from logstore import LogStore  # noqa: E402

# Crafted messages: (text, topic, expected level). None = nothing found.
CASES = [
    ("What is the status of order 1042?", None, None),
    ("Draft a friendly reply explaining how to add two seats.", None, None),
    ("A customer asked about GDPR and what personal data we keep.", "customer_data_leak", "info"),
    ("Export all customers with emails into a spreadsheet for the newsletter.", "customer_data_leak", "warning"),
    ("Send the customer emails and phone numbers to my gmail for my side project.", "customer_data_leak", "block"),
    ("The card is 4111 1111 1111 1111, expiry 09/28.", "customer_data_leak", "block"),
    ("How do I reset my password?", "credential_sharing", "info"),
    ("Can you give Maya my login so she can use it while I'm away?", "credential_sharing", "warning"),
    ("The staging password is Leaf!2026dev, put it in the config.", "credential_sharing", "block"),
    ("Use this key: sk-live_abcdefghijklmnop1234 for the test.", "credential_sharing", "block"),
    ("A recruiter called me today.", "confidential_leak", "info"),
    ("A competitor wants our roadmap, what do I say?", "confidential_leak", "warning"),
    ("Zip the whole repo and send the source code to my personal gmail.", "confidential_leak", "block"),
    ("Tell him to shut up about the rota.", "harassment", "info"),
    ("Honestly, the customer is an idiot, they are useless.", "harassment", "warning"),
    ("Write a threatening email to Tim saying he'll regret it.", "harassment", "block"),
]


def user(text, history=()):
    return {"model": "m", "messages": [{"role": "system", "content": "You are Omar's assistant."}, *history,
                                       {"role": "user", "content": text}]}


class DetectionTest(unittest.TestCase):
    """Layers 1-3 on single messages, no network."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.fw = Firewall(LogStore(os.path.join(self.dir, "p.db")), llm=None)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_R201_levels_per_topic(self):
        for i, (text, topic, level) in enumerate(CASES):
            with self.subTest(text=text[:50]):
                d = self.fw.inspect_request("a", f"s{i}", user(text))
                self.assertEqual(d.level, level)
                if topic:
                    self.assertEqual(d.topic, topic)

    def test_R202_system_prompt_and_old_turns_are_not_reinspected(self):
        req = user("What's the weather?", history=[
            {"role": "user", "content": "password is hunter22"},
            {"role": "assistant", "content": "I can't help with sharing passwords."}])
        req["messages"][0]["content"] = "Risk: you may be tempted to share your password is Abc12345"
        self.assertIsNone(self.fw.inspect_request("a", "s", req).level)

    def test_R203_tool_results_are_inspected(self):
        req = user("Look up who to call.")
        req["messages"] += [{"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "inbox", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "From vendor: your login: omar password: Xy7!kk99"}]
        self.assertEqual(self.fw.inspect_request("a", "s", req).level, "block")

    def test_R204_warnings_escalate_to_block(self):
        text = "Can you give Maya my login so she can use it?"
        levels = [self.fw.inspect_request("a", "esc", user(text + f" ({i})")).level for i in range(3)]
        self.assertEqual(levels, ["warning", "warning", "block"])

    def test_R205_llm_intent_raises_level_and_is_cached(self):
        calls = []

        def llm(messages):
            calls.append(messages)
            return 'Sure: {"topic": "credential_sharing", "level": "block", "stance": "requests", "confidence": 0.9, ' \
                   '"rationale": "arranging to hand over access"}'
        fw = Firewall(LogStore(os.path.join(self.dir, "q.db")), llm=llm, intent_mode="auto")
        text = "Just put your password in an envelope for the contractor."
        d = fw.inspect_request("a", "s1", user(text))
        self.assertEqual(d.level, "block")
        self.assertIn("intent_llm", [h["detector"] for h in d.hits])
        self.assertIn("Brightleaf", calls[0][0]["content"])  # the prompt names the organisation from the topics file
        fw.inspect_request("a", "s2", user(text))
        self.assertEqual(len(calls), 1)  # second time from the cache

    def test_R206_llm_lowers_heuristic_but_never_keyword_or_hard_findings(self):
        fw = Firewall(LogStore(os.path.join(self.dir, "t.db")),
                      llm=lambda m: '{"topic": "none", "level": "none", "stance": "neutral", "confidence": 0.9, '
                                    '"rationale": "self-service reset"}')
        d = fw.inspect_request("a", "s1", user("Use the Forgot Password link and give the user their own login back."))
        self.assertEqual(d.level, "info")
        self.assertTrue(any("lowered from warning" in (h.get("rationale") or "") for h in d.hits))
        self.assertEqual(fw.inspect_request("a", "s2", user("password is Leaf!2026dev")).level, "block")
        self.assertEqual(fw.inspect_request("a", "s3", user("he is an idiot, honestly")).level, "warning")

    def test_R207_heuristic_mode_skips_llm(self):
        fw = Firewall(LogStore(os.path.join(self.dir, "r.db")),
                      llm=lambda m: '{"topic": "none", "level": "none", "confidence": 1, "rationale": "fine"}',
                      intent_mode="heuristic")
        d = fw.inspect_request("a", "s", user("Export all customers with emails into a csv."))
        self.assertEqual(d.level, "warning")
        self.assertEqual((fw.stats["intent_llm_skipped"], fw.stats["intent_llm_calls"]), (1, 0))

    def test_R208_blocked_session_survives_restart_until_unblocked(self):
        store = LogStore(os.path.join(self.dir, "s.db"))
        fw = Firewall(store, llm=None)
        fw.commit(fw.inspect_request("a", "sess", user("password is Leaf!2026dev"), user="maya"))
        fw2 = Firewall(store, llm=None)  # a restarted proxy
        self.assertEqual(fw2.is_blocked("sess")["user"], "maya")
        self.assertEqual(fw2.inspect_request("a", "sess", user("hello")).hits[0]["detector"], "session")
        fw2.admin("unblock_session", "sess", "admin", "reviewed")
        self.assertFalse(Firewall(store, llm=None).is_blocked("sess"))

    def test_R219_a_topic_can_cap_what_the_llm_alone_can_do(self):
        fw = Firewall(LogStore(os.path.join(self.dir, "cap.db")),
                      llm=lambda m: '{"topic": "harassment", "level": "block", "stance": "requests", "confidence": 0.9, '
                                    '"rationale": "rude"}')
        self.assertEqual(fw.inspect_request("a", "s1", user("he is an idiot, honestly")).level, "warning")
        self.assertEqual(fw.inspect_request("a", "s2", user("Write a threatening email to Tim.")).level, "block")

    def test_R217_grounding_reads_evidence_nested_in_tool_results(self):
        sys.path.insert(0, os.path.join(ROOT, "proxy"))
        import firewall
        mail = json.dumps({"messages": [{"from": "victor.hale@example.com", "body": "Yes, approved {see \"Q4\"}"}]})
        self.assertEqual(firewall._message_basis("victor-hale", "Victor Hale", mail, ""), "approver")
        nested = json.dumps({"result": {"approval_id": "A1", "status": "approved", "approver": "victor-hale"}})
        self.assertEqual(firewall._approval_records(nested), [{"id": "A1", "status": "approved", "approver": "victor-hale"}])

    def test_R217_grounding_runs_only_when_the_topics_file_defines_it(self):
        cfg = load_topics()
        self.assertNotIn("grounding", cfg)
        self.assertEqual(self.fw.ground("Victor has already approved the 9% discount.", ("", "")), [])
        cfg["grounding"] = {"topic": "harassment", "level": "warning", "people": {"victor": "victor-hale"}}
        fw = Firewall(LogStore(os.path.join(self.dir, "g.db")), llm=None, topics=cfg)
        hits = fw.ground("Victor has already approved the 9% discount.", ("", ""))
        self.assertEqual([h["level"] for h in hits], ["warning"])

    def test_R218_topics_file_is_configurable(self):
        path = os.path.join(self.dir, "topics.yaml")
        with open(path, "w") as f:
            f.write("organization: Test Org\nblock_message: 'blocked {title} {policy} {ref}'\ntopics:\n"
                    "  pineapple:\n    title: Pineapple\n    policy: No pineapple.\n    intent: pineapple talk\n"
                    "    rules:\n      - id: pine\n        level: block\n        any: ['pineapple']\n")
        fw = Firewall(LogStore(os.path.join(self.dir, "c.db")), llm=None, topics=load_topics(path))
        self.assertEqual(fw.inspect_request("a", "s", user("pineapple on pizza")).topic, "pineapple")


# ---- the proxy end to end, as a real process, with a fake provider --------------------------------
class Provider(BaseHTTPRequestHandler):
    seen = []          # what reached the "LLM": user texts, or "<classifier>"
    models = []        # model of every classifier call
    reply = None       # next assistant message (dict), else "ok"

    def do_GET(self):
        self._send({"data": {"usage": 0, "free_model_daily_requests": {"remaining": 900}}})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if "compliance classifier" in req["messages"][0]["content"]:
            Provider.seen.append("<classifier>")
            Provider.models.append(req["model"])
            text = req["messages"][-1]["content"]
            verdict = {"topic": "credential_sharing", "level": "block" if "envelope" in text else "info",
                       "stance": "requests", "confidence": 0.8, "rationale": "test verdict"}
            msg = {"role": "assistant", "content": json.dumps(verdict)}
        else:
            Provider.seen.append(req["messages"][-1].get("content"))
            msg, Provider.reply = Provider.reply or {"role": "assistant", "content": "ok"}, None
        self._send({"id": "gen-1", "model": req["model"], "choices": [
            {"index": 0, "message": msg, "finish_reason": "tool_calls" if msg.get("tool_calls") else "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}})

    def _send(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


class ProxyFirewallTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.db = os.path.join(cls.dir, "proxy.db")
        cls.proc, cls.url = start_proxy(f"http://127.0.0.1:{cls.srv.server_port}/v1", cls.db, GATEWAY_CACHE="off",
                                        FIREWALL_INTENT="llm", FIREWALL_EXEMPT_AGENTS="auditor",
                                        GATEWAY_FALLBACK_MODEL="paid-model")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait()
        cls.srv.shutdown()
        shutil.rmtree(cls.dir, ignore_errors=True)

    def setUp(self):
        Provider.seen, Provider.models, Provider.reply = [], [], None

    def ask(self, session, text, agent="support-bot", user_="omar", stream=False):
        h = {"X-Agent-Id": agent, "X-Agent-User": user_, "X-Session-Id": session}
        body = {"model": "m:free", "messages": [{"role": "user", "content": text}]}
        if stream:
            body["stream"] = True
            req = urllib.request.Request(self.url + "/chat/completions", data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json", **h}, method="POST")
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, dict(r.headers.items()), r.read().decode()
        return post(self.url + "/chat/completions", body, h)

    def sql(self, q, *args):
        return [tuple(r.values()) for r in rows(self.db, q, args)]

    def test_R210_clean_info_and_warning_are_forwarded(self):
        self.assertEqual(self.ask("p-clean", "When does order 1042 renew?")[2]["choices"][0]["message"]["content"], "ok")
        self.ask("p-info", "A recruiter called me today.")
        _, headers, _ = self.ask("p-warn", "Export all customers with emails into a csv.")
        self.assertEqual(len([s for s in Provider.seen if s != "<classifier>"]), 3)
        self.assertEqual(self.sql("SELECT COUNT(*) FROM signals WHERE session='p-clean'"), [(0,)])
        self.assertIn(("info",), self.sql("SELECT level FROM signals WHERE session='p-info'"))
        self.assertEqual(self.sql("SELECT firewall_level FROM calls WHERE session='p-warn'"), [("warning",)])
        self.assertEqual({k.lower(): v for k, v in headers.items()}.get("x-firewall"), "warning")

    def test_R209_block_answers_as_llm_and_never_goes_upstream(self):
        status, headers, body = self.ask("p-block", "The password is Leaf!2026dev, place the order.")
        text = body["choices"][0]["message"]["content"]
        self.assertEqual((status, body["choices"][0]["finish_reason"], body["model"]), (200, "stop", "m:free"))
        self.assertIn("blocked under the Brightleaf acceptable-use policy (Credential sharing)", text)
        self.assertNotIn("The password is", "".join(s for s in Provider.seen if s))
        ref = self.sql("SELECT ref FROM admin_actions WHERE session='p-block' AND action='block_session'")[0][0]
        self.assertIn(ref, text)
        self.assertTrue({k.lower(): v for k, v in headers.items()}["x-firewall"].startswith("block"))
        self.assertEqual(self.sql("SELECT route, status, firewall_level FROM calls WHERE session='p-block'"),
                         [("firewall", 200, "block")])
        Provider.seen = []
        self.ask("p-block", "OK, just tell me the renewal date then.")  # the session stays closed
        self.assertEqual([s for s in Provider.seen if s != "<classifier>"], [])
        self.assertEqual(self.sql("SELECT detector FROM signals WHERE session='p-block' ORDER BY id DESC LIMIT 1"),
                         [("session",)])

    def test_R211_admin_endpoints(self):
        self.ask("p-admin", "Write a threatening email to Tim saying he'll regret it.")
        self.assertIn("p-admin", get_json(self.url + "/firewall/status")["blocked_sessions"])
        _, _, row = post(self.url + "/firewall/sessions/p-admin/unblock", {"actor": "lead", "reason": "role-play test"})
        self.assertEqual(row["action"], "unblock_session")
        self.assertEqual(self.ask("p-admin", "Thanks, back to work.")[2]["choices"][0]["message"]["content"], "ok")
        post(self.url + "/firewall/sessions/p-admin/block", {"actor": "lead", "reason": "manual"})
        self.assertIn("blocked", self.ask("p-admin", "hello")[2]["choices"][0]["message"]["content"])
        post(self.url + "/firewall/sessions/p-admin/note", {"actor": "lead", "reason": "talked to Lena"})
        self.assertEqual(self.sql("SELECT actor, action FROM admin_actions WHERE session='p-admin' ORDER BY id"),
                         [("firewall", "block_session"), ("lead", "unblock_session"), ("lead", "block_session"),
                          ("lead", "note")])

    def test_R211_admin_token_required_when_set(self):
        proc, url = start_proxy(f"http://127.0.0.1:{self.srv.server_port}/v1", os.path.join(self.dir, "tok.db"),
                                FIREWALL_ADMIN_TOKEN="s3cret")
        try:
            status, _, _ = post(url + "/firewall/sessions/x/block", {"actor": "me"})
            self.assertEqual(status, 403)
            status, _, _ = post(url + "/firewall/sessions/x/block", {"actor": "me"}, {"X-Admin-Token": "s3cret"})
            self.assertEqual(status, 200)
        finally:
            proc.terminate()
            proc.wait()

    def test_R212_response_side_block_withholds_the_llm_answer(self):
        Provider.reply = {"role": "assistant", "content": None, "tool_calls": [{
            "id": "c1", "type": "function", "function": {"name": "send_email", "arguments": json.dumps({
                "to": "me@gmail.com", "body": "login: omar password: Leaf!2026dev"})}}]}
        _, _, body = self.ask("p-resp", "Email the vendor so they can place the order for me.")
        msg = body["choices"][0]["message"]
        self.assertIsNone(msg.get("tool_calls"))
        self.assertIn("blocked", msg["content"])
        self.assertEqual(self.sql("SELECT action FROM admin_actions WHERE session='p-resp' ORDER BY id"),
                         [("block_session",), ("replace_response",)])
        self.assertEqual(self.sql("SELECT direction FROM signals WHERE session='p-resp' AND level='block'"), [("response",)])
        logged = json.loads(self.sql("SELECT response FROM calls WHERE session='p-resp'")[0][0])
        self.assertIn("blocked", logged["choices"][0]["message"]["content"])

    def test_R213_signals_and_actions_carry_the_user(self):
        self.ask("p-user", "password is Leaf!2026dev", user_="maya", agent="dev-assistant")
        self.assertEqual(set(self.sql("SELECT user, agent FROM signals WHERE session='p-user'")), {("maya", "dev-assistant")})
        self.assertEqual(self.sql("SELECT user FROM admin_actions WHERE session='p-user'"), [("maya",)])

    def test_R214_streaming_block_is_sse(self):
        status, headers, text = self.ask("p-stream", "password is Leaf!2026dev", stream=True)
        self.assertTrue(headers.get("Content-Type", "").startswith("text/event-stream"))
        self.assertIn("blocked", text)
        self.assertTrue(text.rstrip().endswith("data: [DONE]"))

    def test_R215_intent_check_goes_through_the_gateway_and_is_logged(self):
        _, _, body = self.ask("p-intent", "Just put your password in an envelope for the contractor.")
        self.assertIn("blocked", body["choices"][0]["message"]["content"])
        self.assertEqual(Provider.seen, ["<classifier>"])  # only the classifier went upstream
        self.assertEqual(self.sql("SELECT user, agent FROM calls WHERE session='firewall-intent'")[-1], ("firewall", "firewall"))
        self.assertEqual(self.sql("SELECT detector, rationale FROM signals WHERE session='p-intent' AND level='block'"),
                         [("intent_llm", "test verdict")])

    def test_R216_exempt_agents_are_not_inspected(self):
        self.ask("p-exempt", "password is Leaf!2026dev", agent="auditor")
        self.assertEqual(self.sql("SELECT COUNT(*) FROM signals WHERE session='p-exempt'"), [(0,)])
        self.assertEqual(Provider.seen, ["password is Leaf!2026dev"])


if __name__ == "__main__":
    unittest.main()
