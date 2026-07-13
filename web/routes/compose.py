"""
Send / reply / forward endpoints.
"""
from flask import Blueprint, request
from web.shared import db, ok, err
from core.database import get_connection
from core.smtp_send import send_message

bp = Blueprint("compose", __name__)


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
        return ok({"message": msg})
    return err(msg)
