"""Team chat: short instant messages between colleagues (the dealership's Slack/Teams).

A chat message is stored here when an agent's LLM asks for `chat_send`. The recipient is not handed
the text: the simulation only tells them "you have a new chat message", and they read it with
`chat_unread`, so the text reaches the recipient's LLM as a tool result, through the proxy.
"""
from apps.common import Param, ToolError, personas, tool


def _staff_id(to):
    to = (to or "").strip().lower()
    for pid, p in personas().items():
        if to in (pid, p["email"].lower(), p["name"].lower(), p["name"].lower().replace(" ", "-")):
            return pid
    raise ToolError(f"unknown colleague {to!r}; use a staff id such as daniel-reed")


@tool("chat", "Send a team chat message to a colleague (staff id, e.g. daniel-reed). They see it within minutes. "
              "Use it for quick questions, approval nudges and handoffs.", writes=True,
      to=Param("string", "Colleague's staff id"), message=Param("string", "What you want to say"))
def chat_send(ctx, to, message):
    to_id = _staff_id(to)
    if to_id == ctx.actor:
        raise ToolError("you cannot message yourself")
    if not (message or "").strip():
        raise ToolError("message is empty")
    cid = ctx.next_id("chat_messages", "chat_id", "CH-", 5)
    ctx.db.execute("INSERT INTO chat_messages VALUES (?,?,?,?,?,?)", [cid, ctx.actor, to_id, message, ctx.now, None])
    return {"chat_id": cid, "to": to_id, "delivered": True}


@tool("chat", "Your unread team chat messages, oldest first. Reading them marks them read.", writes=True)
def chat_unread(ctx):
    rows = ctx.rows("SELECT chat_id, from_staff, body, sent_at FROM chat_messages "
                    "WHERE to_staff = ? AND read_at IS NULL ORDER BY sent_at, chat_id", [ctx.actor])
    if rows:
        ctx.db.execute("UPDATE chat_messages SET read_at = ? WHERE to_staff = ? AND read_at IS NULL",
                       [ctx.now, ctx.actor])
    return rows


@tool("chat", "Recent chat history with one colleague, oldest first.",
      colleague=Param("string", "Colleague's staff id"), limit=Param("integer", "Max messages", default=10))
def chat_history(ctx, colleague, limit=10):
    other = _staff_id(colleague)
    rows = ctx.rows("SELECT chat_id, from_staff, to_staff, body, sent_at FROM chat_messages "
                    "WHERE (from_staff = ? AND to_staff = ?) OR (from_staff = ? AND to_staff = ?) "
                    "ORDER BY sent_at DESC, chat_id DESC LIMIT ?",
                    [ctx.actor, other, other, ctx.actor, min(int(limit), 30)])
    return rows[::-1]
