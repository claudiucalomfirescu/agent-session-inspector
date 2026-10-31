"""BMW's side: the technical support engineer behind the portal's tech-case tool.

The portal service (apps/bmw_portal) calls tech_support_answer() when a dealer opens a technical case.
This is a judgment tool: the answer is written by an LLM agent, through the same proxy as everyone
else, as user `bmw-tech-support`, department "BMW UK". Set VXC_BMW_AGENT=off to skip the LLM (tests):
the case is then queued without an answer.
"""
import json
import os

TECH_USER = "bmw-tech-support"


def tech_support_answer(dealer_actor, vin, symptom, question, facts):
    if os.environ.get("VXC_BMW_AGENT", "on").lower() in ("off", "0", "false", "no"):
        return {}
    from openai import APIError

    from agents.prompts import BMW_TECH
    from llm import MODEL, AgentLog, chat, make_client
    labels = {"role": "Technical Support Engineer", "org": "bmw", "caller": dealer_actor,
              "via": "bmw_open_tech_case"}
    client, session = make_client(TECH_USER, dept="BMW UK", **labels)
    log = AgentLog(TECH_USER, session, **labels)
    prompt = (f"Case from dealer GB-40712 (VXC Motors), opened by {dealer_actor}.\nVIN: {vin}\n"
              f"Symptom: {symptom}\nQuestion: {question}\n\nFacts from the BMW systems:\n"
              f"{json.dumps(facts, default=str)[:6000]}")
    log.start(goal=prompt, model=MODEL)
    try:
        resp = chat(client, [{"role": "system", "content": BMW_TECH}, {"role": "user", "content": prompt}], log=log)
    except APIError as e:
        log.end(status="error")
        return {"answer": None, "error": str(e)[:200]}
    text = (resp.choices[0].message.content or "").strip()
    log.end(answer=text, status="blocked" if log.blocked else "done")
    return {"answer": text, "answered_by": f"{TECH_USER} (session {session})"}
