"""
Send / reply / forward / draft endpoints.
"""
import json as _json
import time
from flask import Blueprint, request
from web.shared import db, ok, err
from core.database import get_connection
from core.smtp_send import send_message

bp = Blueprint("compose", __name__)


def _get_or_create_drafts_folder(conn, account_id: int) -> int:
    row = conn.execute(
        "SELECT id FROM folders WHERE account_id=? AND role='drafts' LIMIT 1",
        (account_id,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO folders (account_id, name, display_name, role) VALUES (?,?,?,?)",
        (account_id, "Drafts", "Drafts", "drafts")
    )
    return cur.lastrowid


@bp.route("/api/send", methods=["POST"])
def api_send():
    # Accept multipart/form-data (carries file attachments) or JSON
    if request.content_type and "application/json" in request.content_type:
        data = request.get_json() or {}
        files = []
    else:
        data = request.form
        files = request.files.getlist("attachments")

    account_id = data.get("account_id")
    to         = data.get("to", "")
    subject    = data.get("subject", "")
    body       = data.get("body", "")

    if not account_id or not to or not subject:
        return err("account_id, to, and subject are required")

    conn = get_connection(db())
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (int(account_id),)).fetchone()
    conn.close()
    if not row:
        return err("Account not found", 404)

    attachments = [
        (f.filename, f.content_type or "application/octet-stream", f.read())
        for f in files if f and f.filename
    ]

    ok_sent, msg = send_message(
        account=dict(row),
        to=to,
        subject=subject,
        body=body,
        cc=data.get("cc") or None,
        bcc=data.get("bcc") or None,
        reply_to_msg_id=data.get("reply_to_msg_id") or None,
        references=data.get("references") or None,
        attachments=attachments or None,
        request_receipt=data.get("request_receipt") in ("1", "true", True),
    )
    if ok_sent:
        draft_id = data.get("draft_id")
        if draft_id:
            try:
                dconn = get_connection(db())
                dconn.execute("DELETE FROM messages WHERE id=?", (int(draft_id),))
                dconn.commit()
                dconn.close()
            except Exception:
                pass
        return ok({"message": msg})
    return err(msg)


@bp.route("/api/drafts", methods=["POST"])
def api_save_draft():
    data = request.get_json() or {}
    account_id = int(data.get("account_id") or 0)
    if not account_id:
        return err("account_id required")

    conn = get_connection(db())
    acct = conn.execute("SELECT email, name FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not acct:
        conn.close()
        return err("Account not found", 404)

    folder_id = _get_or_create_drafts_folder(conn, account_id)

    to      = data.get("to", "")
    cc      = data.get("cc", "")
    bcc     = data.get("bcc", "")
    subj    = data.get("subject", "")
    body    = data.get("body", "")
    meta    = _json.dumps({
        "bcc": bcc,
        "reply_msg_id": data.get("reply_msg_id", ""),
        "references":   data.get("references", ""),
    })
    snippet = body[:120].replace("\n", " ")
    flags   = _json.dumps(["\\Draft"])
    uid     = int(time.time() * 1000) % 0x7FFFFFFF + 0x40000000

    cur = conn.execute("""
        INSERT INTO messages
            (account_id, folder_id, uid, flags, from_addr, from_name, to_addrs, cc_addrs,
             subject, date, snippet, body_fetched, draft_meta)
        VALUES (?,?,?,?,?,?,?,?,?,datetime('now','localtime'),?,1,?)
    """, (account_id, folder_id, uid, flags, acct["email"], acct["name"],
          to, cc, subj, snippet, meta))
    draft_id = cur.lastrowid
    conn.execute("UPDATE messages SET uid=? WHERE id=?", (draft_id, draft_id))
    conn.execute("INSERT INTO message_bodies (message_id, body_text) VALUES (?,?)", (draft_id, body))
    conn.commit()
    conn.close()
    return ok({"id": draft_id})


@bp.route("/api/drafts/<int:did>", methods=["PUT"])
def api_update_draft(did: int):
    data = request.get_json() or {}
    to   = data.get("to", "")
    cc   = data.get("cc", "")
    body = data.get("body", "")
    subj = data.get("subject", "")
    meta = _json.dumps({
        "bcc": data.get("bcc", ""),
        "reply_msg_id": data.get("reply_msg_id", ""),
        "references":   data.get("references", ""),
    })
    snippet = body[:120].replace("\n", " ")

    conn = get_connection(db())
    conn.execute("""
        UPDATE messages SET to_addrs=?, cc_addrs=?, subject=?, snippet=?, draft_meta=?
        WHERE id=?
    """, (to, cc, subj, snippet, meta, did))
    conn.execute(
        "INSERT OR REPLACE INTO message_bodies (message_id, body_text) VALUES (?,?)",
        (did, body)
    )
    conn.commit()
    conn.close()
    return ok()


@bp.route("/api/drafts/<int:did>", methods=["DELETE"])
def api_delete_draft(did: int):
    conn = get_connection(db())
    conn.execute("DELETE FROM messages WHERE id=?", (did,))
    conn.commit()
    conn.close()
    return ok()
