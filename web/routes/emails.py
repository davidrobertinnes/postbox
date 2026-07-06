"""
Email list and thread endpoints.
"""
import json
from flask import Blueprint, request
from web.shared import db, ok, err, dict_rows
from core.database import get_connection
from core.imap_sync import fetch_body

bp = Blueprint("emails", __name__)


@bp.route("/api/emails")
def api_emails():
    """
    List messages. Query params:
      folder=inbox|sent|drafts|trash|spam|all  (default: inbox)
      account=<id>    (default: all accounts)
      q=<search>
      unread=1        (only unread)
      limit=<n>       (default 100)
      offset=<n>      (default 0)
    """
    conn = get_connection(db())
    folder_role = request.args.get("folder", "inbox")
    folder_id = request.args.get("folder_id", type=int)
    account_id = request.args.get("account", type=int)
    q = request.args.get("q", "").strip()
    unread_only = request.args.get("unread") == "1"
    priority = request.args.get("priority", type=int)
    limit = min(int(request.args.get("limit", 100)), 9999)
    offset = int(request.args.get("offset", 0))

    params = []
    where = []

    if folder_id:
        where.append("m.folder_id=?")
        params.append(folder_id)
    elif folder_role != "all":
        where.append("f.role=?")
        params.append(folder_role)

    if account_id:
        where.append("m.account_id=?")
        params.append(account_id)

    if unread_only:
        where.append("m.flags NOT LIKE '%Seen%'")

    if priority:
        where.append("m.ai_priority=?")
        params.append(priority)

    if q:
        where.append("(m.subject LIKE ? OR m.from_addr LIKE ? OR m.from_name LIKE ? OR m.snippet LIKE ?)")
        params.extend([f"%{q}%"] * 4)

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""
    params.extend([limit, offset])

    rows = dict_rows(conn.execute(f"""
        SELECT m.id, m.account_id, m.folder_id, m.uid, m.message_id, m.thread_id,
               m.from_addr, m.from_name, m.to_addrs, m.subject, m.date,
               m.snippet, m.flags, m.has_attachments, m.body_fetched,
               m.ai_priority, m.ai_category,
               a.name as account_name, a.email as account_email,
               f.role as folder_role, f.name as folder_name
        FROM messages m
        JOIN accounts a ON a.id = m.account_id
        JOIN folders f ON f.id = m.folder_id
        {where_clause}
        ORDER BY m.date DESC
        LIMIT ? OFFSET ?
    """, params).fetchall())

    # Count for pagination
    count_params = params[:-2]
    total = conn.execute(f"""
        SELECT COUNT(*) FROM messages m
        JOIN accounts a ON a.id = m.account_id
        JOIN folders f ON f.id = m.folder_id
        {where_clause}
    """, count_params).fetchone()[0]

    conn.close()
    return ok({"messages": rows, "total": total})


@bp.route("/api/emails/unread_count")
def api_unread_count():
    conn = get_connection(db())
    row = conn.execute(
        "SELECT SUM(unread_count) as n FROM folders WHERE role='inbox'"
    ).fetchone()
    conn.close()
    return ok({"unread": row["n"] or 0})


@bp.route("/api/emails/<int:mid>")
def api_email(mid: int):
    conn = get_connection(db())
    row = conn.execute("""
        SELECT m.*, a.name as account_name, a.email as account_email,
               f.role as folder_role, f.name as folder_name,
               b.body_text, b.body_html
        FROM messages m
        JOIN accounts a ON a.id = m.account_id
        JOIN folders f ON f.id = m.folder_id
        LEFT JOIN message_bodies b ON b.message_id = m.id
        WHERE m.id=?
    """, (mid,)).fetchone()

    if not row:
        conn.close()
        return err("Not found", 404)

    msg = dict(row)
    account_id = msg["account_id"]
    uid = msg["uid"]
    folder_name = msg["folder_name"]

    # Lazy-fetch body if not yet stored
    if not msg["body_fetched"]:
        conn.close()
        fetch_body(mid, account_id, uid, folder_name, db())
        # Re-read
        conn = get_connection(db())
        row = conn.execute("""
            SELECT m.*, a.name as account_name, a.email as account_email,
                   f.role as folder_role, f.name as folder_name,
                   b.body_text, b.body_html
            FROM messages m
            JOIN accounts a ON a.id = m.account_id
            JOIN folders f ON f.id = m.folder_id
            LEFT JOIN message_bodies b ON b.message_id = m.id
            WHERE m.id=?
        """, (mid,)).fetchone()
        msg = dict(row)

    attachments = dict_rows(conn.execute(
        "SELECT * FROM attachments WHERE message_id=?", (mid,)
    ).fetchall())
    msg["attachments"] = attachments

    # Update local read flag (IMAP server write-back triggered separately by client)
    if "Seen" not in (msg.get("flags") or ""):
        import json as _json
        flags = _json.loads(msg.get("flags") or "[]")
        if "\\Seen" not in flags:
            flags.append("\\Seen")
            conn.execute("UPDATE messages SET flags=? WHERE id=?", (_json.dumps(flags), mid))
            conn.execute(
                "UPDATE folders SET unread_count=MAX(0,unread_count-1) WHERE id=?",
                (msg["folder_id"],)
            )
            conn.commit()

    conn.close()
    return ok(msg)


@bp.route("/api/emails/<int:mid>/mark_read", methods=["POST"])
def api_mark_read(mid: int):
    from core.imap_actions import mark_read
    mark_read(mid, db())
    return ok()


@bp.route("/api/emails/<int:mid>/mark_unread", methods=["POST"])
def api_mark_unread(mid: int):
    from core.imap_actions import mark_unread
    mark_unread(mid, db())
    return ok()


@bp.route("/api/emails/<int:mid>/trash", methods=["POST"])
def api_trash(mid: int):
    from core.imap_actions import trash_message
    if trash_message(mid, db()):
        return ok()
    return err("Could not trash message")


@bp.route("/api/emails/<int:mid>/move", methods=["POST"])
def api_move(mid: int):
    from core.imap_actions import move_message
    data = request.get_json() or {}
    folder_id = data.get("folder_id")
    if not folder_id:
        return err("folder_id required")
    if move_message(mid, int(folder_id), db()):
        return ok()
    return err("Could not move message")


@bp.route("/api/threads/<thread_id>")
def api_thread(thread_id: str):
    """Return all messages in a thread, oldest first."""
    conn = get_connection(db())
    rows = dict_rows(conn.execute("""
        SELECT m.id, m.from_addr, m.from_name, m.to_addrs, m.subject, m.date,
               m.snippet, m.flags, m.account_id, m.thread_id,
               b.body_text, b.body_html
        FROM messages m
        LEFT JOIN message_bodies b ON b.message_id = m.id
        WHERE m.thread_id=?
        ORDER BY m.date ASC
    """, (thread_id,)).fetchall())
    conn.close()
    return ok(rows)


@bp.route("/api/folders")
def api_folders():
    account_id = request.args.get("account", type=int)
    conn = get_connection(db())
    params = []
    where = ""
    if account_id:
        where = "WHERE f.account_id=?"
        params.append(account_id)
    rows = dict_rows(conn.execute(f"""
        SELECT f.*, a.name as account_name, a.email as account_email
        FROM folders f
        JOIN accounts a ON a.id = f.account_id
        {where}
        ORDER BY f.account_id, f.role NULLS LAST, f.name
    """, params).fetchall())
    conn.close()
    return ok(rows)


# ── External hook API (no auth, localhost trust) ───────────────────────────────

@bp.route("/api/ext/emails")
def api_ext_emails():
    """dbox hook: GET /api/ext/emails?contact=email@example.com"""
    contact = request.args.get("contact", "").lower().strip()
    if not contact:
        return err("contact param required")
    conn = get_connection(db())
    rows = dict_rows(conn.execute("""
        SELECT m.id, m.subject, m.date, m.from_addr, m.from_name, m.snippet,
               a.name as account_name
        FROM messages m
        JOIN accounts a ON a.id = m.account_id
        WHERE LOWER(m.from_addr)=? OR LOWER(m.to_addrs) LIKE ?
        ORDER BY m.date DESC LIMIT 20
    """, (contact, f"%{contact}%")).fetchall())
    conn.close()
    return ok(rows)


@bp.route("/api/ext/unread_count")
def api_ext_unread():
    conn = get_connection(db())
    row = conn.execute(
        "SELECT SUM(unread_count) as n FROM folders WHERE role='inbox'"
    ).fetchone()
    conn.close()
    return ok({"unread": row["n"] or 0})
