"""
Import messages from .eml and .mbox files into the local DB.
Messages are inserted with a synthetic UID (db row id) and body_fetched=1
so they appear immediately without an IMAP fetch.
"""
import time
import json
import mailbox
import io
import email as _email
import email.utils

from flask import Blueprint, request
from web.shared import db, ok, err
from core.database import get_connection
from core.email_parser import parse_raw, snippet_from_text

bp = Blueprint("import_mail", __name__)


@bp.route("/api/import", methods=["POST"])
def api_import():
    account_id = request.form.get("account_id")
    folder_id  = request.form.get("folder_id")
    files      = request.files.getlist("files")

    if not account_id:
        return err("account_id required")

    conn = get_connection(db())
    acct = conn.execute("SELECT id FROM accounts WHERE id=?", (int(account_id),)).fetchone()
    if not acct:
        conn.close()
        return err("Account not found", 404)

    # Resolve folder — default to inbox
    if folder_id:
        folder = conn.execute("SELECT * FROM folders WHERE id=? AND account_id=?",
                              (int(folder_id), int(account_id))).fetchone()
    else:
        folder = conn.execute("SELECT * FROM folders WHERE account_id=? AND role='inbox' LIMIT 1",
                              (int(account_id),)).fetchone()

    if not folder:
        conn.close()
        return err("Folder not found")
    folder = dict(folder)
    conn.close()

    messages = []
    for f in files:
        raw = f.read()
        fname = (f.filename or "").lower()
        if fname.endswith(".mbox") or raw[:5] == b"From ":
            # mbox: iterate messages
            mbox = mailbox.mbox(None)  # in-memory trick
            mbox._file = io.BytesIO(raw)
            try:
                for msg in mbox:
                    messages.append(msg.as_bytes())
            except Exception:
                # fallback: split on "From " lines
                for part in raw.decode("utf-8", errors="replace").split("\nFrom "):
                    if part.strip():
                        messages.append(("From " + part).encode())
        else:
            messages.append(raw)

    imported = 0
    conn = get_connection(db())
    try:
        for raw_bytes in messages:
            _import_one(conn, int(account_id), folder, raw_bytes)
            imported += 1
        conn.commit()
    except Exception as e:
        conn.close()
        return err(f"Import failed: {e}")
    conn.close()
    return ok({"imported": imported})


def _import_one(conn, account_id: int, folder: dict, raw_bytes: bytes) -> None:
    parsed = parse_raw(raw_bytes)
    folder_id  = folder["id"]

    # Thread ID
    in_reply_to = parsed.get("in_reply_to") or ""
    message_id  = parsed.get("message_id") or ""
    if in_reply_to:
        parent = conn.execute(
            "SELECT thread_id FROM messages WHERE message_id=? AND account_id=?",
            (in_reply_to, account_id)
        ).fetchone()
        thread_id = parent["thread_id"] if parent else in_reply_to
    else:
        thread_id = message_id or f"import-{time.time_ns()}"

    # Synthetic UID: use time-based value in high range unlikely to collide with IMAP UIDs
    synthetic_uid = (int(time.time() * 1000) % 0x7FFFFFFF) + 0x40000000

    flags = json.dumps(["\\Seen"])  # imported messages default to read

    cur = conn.execute("""
        INSERT OR IGNORE INTO messages
            (account_id, folder_id, uid, message_id, thread_id,
             from_addr, from_name, to_addrs, cc_addrs,
             subject, date, snippet, flags, has_attachments, body_fetched)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1)
    """, (
        account_id, folder_id, synthetic_uid,
        message_id, thread_id,
        parsed["from_addr"], parsed["from_name"],
        parsed["to_addrs"], parsed["cc_addrs"],
        parsed["subject"], parsed["date"],
        parsed["snippet"], flags,
        parsed["has_attachments"],
    ))
    if cur.rowcount == 0:
        return  # already exists (same message_id + account + folder)

    msg_db_id = cur.lastrowid
    # Update uid to match row id to ensure uniqueness
    conn.execute("UPDATE messages SET uid=? WHERE id=?", (msg_db_id, msg_db_id))

    conn.execute("""
        INSERT OR REPLACE INTO message_bodies (message_id, body_text, body_html)
        VALUES (?,?,?)
    """, (msg_db_id, parsed["body_text"], parsed["body_html"]))

    for att in (parsed.get("attachments") or []):
        conn.execute("""
            INSERT INTO attachments (message_id, filename, content_type, size)
            VALUES (?,?,?,?)
        """, (msg_db_id, att["filename"], att["content_type"], att["size"]))
