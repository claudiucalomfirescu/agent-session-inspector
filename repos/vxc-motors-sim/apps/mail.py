"""Email & chat: messages between staff, and to/from customers (external addresses)."""
from apps.common import Param, ToolError, tool


def _addr(ctx):
    return ctx.persona["email"]


def _resolve(ctx, to):
    """Accept a staff id ('daniel-reed'), a staff email or any external address."""
    to = to.strip()
    if "@" not in to:
        email = ctx.scalar("SELECT email FROM staff WHERE staff_id = ?", [to])
        if not email:
            raise ToolError(f"unknown recipient {to}; use a staff id or an email address")
        return email
    return to


@tool("mail", "Send an email. 'to' is a staff id (e.g. daniel-reed), a staff email or a customer's email.",
      writes=True, to=Param("string", "Recipient"), subject=Param("string", "Subject"),
      body=Param("string", "Message text"), cc=Param("string", "Optional CC, same formats", default=None),
      reply_to=Param("string", "msg_id you are replying to (keeps the thread)", default=None))
def mail_send(ctx, to, subject, body, cc=None, reply_to=None):
    to_addr = _resolve(ctx, to)
    cc_addr = _resolve(ctx, cc) if cc else None
    mid = ctx.next_id("messages", "msg_id", "MSG-", 6)
    thread = mid
    if reply_to:
        thread = ctx.scalar("SELECT thread_id FROM messages WHERE msg_id=?", [reply_to]) or mid
    ctx.db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?,?)",
                   [mid, thread, _addr(ctx), to_addr, cc_addr, subject, body, ctx.now, None])
    external = not to_addr.endswith("@vxcmotors.example")
    return {"msg_id": mid, "thread_id": thread, "to": to_addr, "external": external}


@tool("mail", "Your inbox, newest first.",
      unread_only=Param("boolean", "Only unread", default=True), limit=Param("integer", "Max", default=15))
def mail_inbox(ctx, unread_only=True, limit=15):
    me = _addr(ctx)
    sql = ("SELECT msg_id, thread_id, from_addr, subject, sent_at, read_at IS NOT NULL AS read, "
           "left(body, 160) AS preview FROM messages WHERE (to_addr = ? OR cc = ?)")
    if unread_only:
        sql += " AND read_at IS NULL"
    return ctx.rows(sql + " ORDER BY sent_at DESC LIMIT ?", [me, me, min(int(limit), 50)])


@tool("mail", "Read one message (marks it read) and the earlier messages in its thread.", writes=True,
      msg_id=Param("string", "Message id"))
def mail_read(ctx, msg_id):
    me = _addr(ctx)
    m = ctx.row("SELECT * FROM messages WHERE msg_id=?", [msg_id])
    if not m or me not in (m["to_addr"], m["cc"], m["from_addr"]):
        raise ToolError(f"no message {msg_id} in your mailbox")
    if m["to_addr"] == me or m["cc"] == me:
        ctx.db.execute("UPDATE messages SET read_at=? WHERE msg_id=? AND read_at IS NULL", [ctx.now, msg_id])
    m["thread"] = ctx.rows("SELECT msg_id, from_addr, to_addr, sent_at, body FROM messages "
                           "WHERE thread_id=? AND msg_id<>? AND sent_at <= ? ORDER BY sent_at",
                           [m["thread_id"], msg_id, m["sent_at"]])
    return m


@tool("mail", "Company directory: who does what and their email.")
def mail_directory(ctx):
    return ctx.rows("SELECT staff_id, name, role, department, email, phone_ext FROM staff ORDER BY department, name")
