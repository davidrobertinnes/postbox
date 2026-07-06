"""
Send / reply / forward endpoints.
"""
import json
from flask import Blueprint, request
from web.shared import db, ok, err, dict_rows
from core.database import get_connection
from core.smtp_send import send_message

bp = Blueprint("compose", __name__)


@bp.route("/api/send", methods=["POST"])
def api_send():
    data = request.get_json() or {}
    account_id = data.get("account_id")
    to = data.get("to", "")
    subject = data.get("subject", "")
    body = data.get("body", "")

    if not account_id or not to or not subject:
        return err("account_id, to, and subject are required")

    conn = get_connection(db())
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    conn.close()
    if not row:
        return err("Account not found", 404)

    ok_sent, msg = send_message(
        account=dict(row),
        to=to,
        subject=subject,
        body=body,
        cc=data.get("cc"),
        reply_to_msg_id=data.get("reply_to_msg_id"),
        references=data.get("references"),
    )
    if ok_sent:
        return ok({"message": msg})
    return err(msg)
