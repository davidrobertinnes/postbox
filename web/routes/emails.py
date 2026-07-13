"""
Email list and thread endpoints.
"""
import json
import threading
from flask import Blueprint, request
from web.shared import db, ok, err, dict_rows
from core.database import get_connection
from core.imap_sync import fetch_body

bp = Blueprint("emails", __name__)

_prefetch_state = {}  # {key: {"total": N, "done": M, "running": bool}}


def _parse_search_operators(q: str):
    """Split 'from:alice subject:invoice has:attachment is:unread is:starred freetext'
    into structured filters and remaining freetext."""
    import re
    filters = {}
    freetext = []
    for token in q.split():
        if token.startswith("from:"):
            filters["from"] = token[5:]
        elif token.startswith("subject:"):
            filters["subject"] = token[8:]
        elif token == "has:attachment":
            filters["has_attachment"] = True
        elif token == "is:unread":
            filters["is_unread"] = True
        elif token == "is:starred":
            filters["is_starred"] = True
        else:
            freetext.append(token)
    filters["freetext"] = " ".join(freetext)
    return filters


@bp.route("/api/emails")
def api_emails():
    """
    List messages. Query params:
      folder=inbox|sent|drafts|trash|spam|all  (default: inbox)
      account=<id>    (default: all accounts)
      q=<search>      (supports from:, subject:, has:attachment, is:unread, is:starred)
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

    category = request.args.get("category")
    if category:
        where.append("m.ai_category=?")
        params.append(category)

    if q:
        sf = _parse_search_operators(q)
        if sf.get("from"):
            where.append("(m.from_addr LIKE ? OR m.from_name LIKE ?)")
            params.extend([f"%{sf['from']}%"] * 2)
        if sf.get("subject"):
            where.append("m.subject LIKE ?")
            params.append(f"%{sf['subject']}%")
        if sf.get("has_attachment"):
            where.append("m.has_attachments=1")
        if sf.get("is_unread"):
            where.append("m.flags NOT LIKE '%Seen%'")
        if sf.get("is_starred"):
            where.append("m.flags LIKE '%Flagged%'")
        if sf["freetext"]:
            ft = sf["freetext"]
            where.append("(m.subject LIKE ? OR m.from_addr LIKE ? OR m.from_name LIKE ? OR m.snippet LIKE ?)")
            params.extend([f"%{ft}%"] * 4)

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


@bp.route("/api/emails/bulk_move", methods=["POST"])
def api_bulk_move():
    from core.imap_actions import bulk_move_messages
    data = request.get_json() or {}
    category  = data.get("category")
    folder_id = data.get("folder_id")
    folder_role = data.get("folder_role") or "inbox"
    account_id  = data.get("account_id")

    if not folder_id or not category:
        return err("category and folder_id required")

    conn = get_connection(db())
    where = ["m.ai_category=?"]
    params = [category]
    if folder_role:
        where.append("f.role=?")
        params.append(folder_role)
    if account_id:
        where.append("m.account_id=?")
        params.append(account_id)
    where_clause = "WHERE " + " AND ".join(where)
    rows = conn.execute(f"""
        SELECT m.id FROM messages m
        JOIN folders f ON f.id = m.folder_id
        {where_clause}
        LIMIT 500
    """, params).fetchall()
    conn.close()

    if not rows:
        return ok({"moved": 0})

    ids = [r[0] for r in rows]
    moved = bulk_move_messages(ids, int(folder_id), db())
    return ok({"moved": moved})


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
        fetched_ok = fetch_body(mid, account_id, uid, folder_name, db())
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
        if not fetched_ok and not msg.get("body_text") and not msg.get("body_html"):
            msg["_fetch_error"] = "Could not load message body — check account password in Accounts settings."

    attachments = dict_rows(conn.execute(
        "SELECT * FROM attachments WHERE message_id=?", (mid,)
    ).fetchall())
    msg["attachments"] = attachments

    conn.close()
    return ok(msg)


@bp.route("/api/emails/prefetch", methods=["POST"])
def api_prefetch():
    """Start background body-fetch for all messages in a view that lack body."""
    data       = request.get_json() or {}
    folder_role = data.get("folder_role")
    folder_id_arg = data.get("folder_id")
    account_id_arg = data.get("account_id")

    conn = get_connection(db())
    params, where = [], []
    if folder_id_arg:
        where.append("m.folder_id=?"); params.append(folder_id_arg)
    elif folder_role:
        where.append("f.role=?"); params.append(folder_role)
    if account_id_arg:
        where.append("m.account_id=?"); params.append(account_id_arg)
    where.append("m.body_fetched=0")
    wc = "WHERE " + " AND ".join(where)
    rows = conn.execute(f"""
        SELECT m.id, m.uid, m.account_id, f.name as folder_name
        FROM messages m JOIN folders f ON f.id=m.folder_id {wc}
        LIMIT 500
    """, params).fetchall()
    conn.close()
    if not rows:
        return ok({"queued": 0})

    key = f"{folder_role or folder_id_arg}_{account_id_arg}"
    _prefetch_state[key] = {"total": len(rows), "done": 0, "running": True}

    db_path = db()
    def _run():
        for row in rows:
            fetch_body(row["id"], row["account_id"], row["uid"], row["folder_name"], db_path)
            _prefetch_state[key]["done"] += 1
        _prefetch_state[key]["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return ok({"queued": len(rows), "key": key})


@bp.route("/api/emails/prefetch_status")
def api_prefetch_status():
    key = request.args.get("key", "")
    state = _prefetch_state.get(key)
    if not state:
        return ok({"done": 0, "total": 0, "running": False})
    return ok(state)


@bp.route("/api/emails/empty_trash", methods=["POST"])
def api_empty_trash():
    from core.imap_actions import empty_trash
    data = request.get_json() or {}
    account_id = data.get("account_id")
    if not account_id:
        return err("account_id required")
    deleted = empty_trash(int(account_id), db())
    return ok({"deleted": deleted})


@bp.route("/api/emails/mark_all_read", methods=["POST"])
def api_mark_all_read():
    from core.imap_actions import mark_all_read
    data = request.get_json() or {}
    folder_role = data.get("folder_role")
    folder_id_arg = data.get("folder_id")
    account_id_arg = data.get("account_id")

    conn = get_connection(db())
    if folder_id_arg:
        where = "WHERE m.folder_id=? AND m.flags NOT LIKE '%Seen%'"
        wparams = [folder_id_arg]
    elif folder_role:
        where = "WHERE f.role=? AND m.flags NOT LIKE '%Seen%'"
        wparams = [folder_role]
    else:
        conn.close()
        return err("folder_role or folder_id required")
    if account_id_arg:
        where += " AND m.account_id=?"
        wparams.append(account_id_arg)
    rows = conn.execute(f"""
        SELECT m.id FROM messages m JOIN folders f ON f.id = m.folder_id
        {where} LIMIT 1000
    """, wparams).fetchall()
    conn.close()
    if not rows:
        return ok({"marked": 0})
    ids = [r[0] for r in rows]
    marked = mark_all_read(ids, db())
    return ok({"marked": marked})


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


@bp.route("/api/emails/<int:mid>/spam", methods=["POST"])
def api_spam(mid: int):
    from core.imap_actions import mark_spam
    if mark_spam(mid, db()):
        return ok()
    return err("Could not mark as spam")


@bp.route("/api/emails/<int:mid>/unspam", methods=["POST"])
def api_unspam(mid: int):
    from core.imap_actions import mark_not_spam
    if mark_not_spam(mid, db()):
        return ok()
    return err("Could not unspam message")


@bp.route("/api/emails/<int:mid>/star", methods=["POST"])
def api_star(mid: int):
    from core.imap_actions import toggle_starred
    starred = toggle_starred(mid, db())
    return ok({"starred": starred})


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


@bp.route("/api/emails/<int:mid>/attachment/<int:att_id>")
def api_download_attachment(mid: int, att_id: int):
    import io
    from flask import send_file
    from core.imap_sync import fetch_raw
    from core.email_parser import extract_attachment_bytes

    conn = get_connection(db())
    att = conn.execute(
        "SELECT * FROM attachments WHERE id=? AND message_id=?", (att_id, mid)
    ).fetchone()
    if not att:
        conn.close()
        return err("Attachment not found", 404)
    att = dict(att)

    msg_row = conn.execute("""
        SELECT m.uid, m.account_id, f.name as folder_name
        FROM messages m JOIN folders f ON f.id = m.folder_id
        WHERE m.id=?
    """, (mid,)).fetchone()
    if not msg_row:
        conn.close()
        return err("Message not found", 404)
    msg_row = dict(msg_row)

    all_ids = [r[0] for r in conn.execute(
        "SELECT id FROM attachments WHERE message_id=? ORDER BY id", (mid,)
    ).fetchall()]
    conn.close()

    att_index = all_ids.index(att_id) if att_id in all_ids else 0

    raw = fetch_raw(msg_row["account_id"], msg_row["uid"], msg_row["folder_name"], db())
    if raw is None:
        return err("Could not fetch message from IMAP server")

    data, content_type = extract_attachment_bytes(raw, att_index)
    if data is None:
        return err("Attachment not found in message body")

    import re
    safe_name = re.sub(r'[\r\n\t]', ' ', att["filename"] or "attachment").strip() or "attachment"
    return send_file(
        io.BytesIO(data),
        mimetype=content_type or "application/octet-stream",
        as_attachment=True,
        download_name=safe_name,
    )


@bp.route("/api/threads/<thread_id>")
def api_thread(thread_id: str):
    """Return all messages in a thread, oldest first."""
    conn = get_connection(db())
    rows = dict_rows(conn.execute("""
        SELECT m.id, m.from_addr, m.from_name, m.to_addrs, m.cc_addrs,
               m.subject, m.date, m.snippet, m.flags, m.account_id, m.thread_id,
               m.has_attachments, m.body_fetched,
               b.body_text, b.body_html,
               f.role as folder_role,
               a.email as account_email
        FROM messages m
        LEFT JOIN message_bodies b ON b.message_id = m.id
        JOIN folders f ON f.id = m.folder_id
        JOIN accounts a ON a.id = m.account_id
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
