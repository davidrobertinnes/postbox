"""
IMAP write-back operations — mark read/unread, trash, move.
Each function makes its own IMAP connection (thread-safe, no shared state).
Local DB is updated first (optimistic); IMAP write is best-effort in background.
"""
import json
import logging
import threading

from core.database import get_connection
from core.credentials import get_password
from core.imap_sync import _make_client, _OAUTH_AUTH_TYPES

log = logging.getLogger(__name__)


def _load_message(conn, message_db_id: int):
    return conn.execute("""
        SELECT m.*, f.name as folder_name
        FROM messages m
        JOIN folders f ON f.id = m.folder_id
        WHERE m.id=?
    """, (message_db_id,)).fetchone()


def _imap_connect(account_id: int, db_path: str):
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    conn.close()
    if not row:
        return None
    account = dict(row)
    password = None
    if account.get("auth_type") not in _OAUTH_AUTH_TYPES:
        password = get_password(account_id)
        if not password:
            return None
    try:
        return _make_client(account, password)
    except Exception as e:
        log.error("imap connect account=%d: %s", account_id, e)
        return None


def _set_flags_db(conn, message_db_id: int, folder_id: int, add: list, remove: list):
    row = conn.execute("SELECT flags FROM messages WHERE id=?", (message_db_id,)).fetchone()
    if not row:
        return
    flags = json.loads(row["flags"] or "[]")
    flags = [f for f in flags if f not in remove]
    for f in add:
        if f not in flags:
            flags.append(f)
    conn.execute("UPDATE messages SET flags=? WHERE id=?", (json.dumps(flags), message_db_id))

    # Adjust unread count
    was_unread = "\\Seen" in remove
    now_unread = "\\Seen" in add
    if was_unread:
        conn.execute("UPDATE folders SET unread_count=MAX(0,unread_count-1) WHERE id=?", (folder_id,))
    if now_unread:
        conn.execute("UPDATE folders SET unread_count=unread_count+1 WHERE id=?", (folder_id,))


def mark_read(message_db_id: int, db_path: str) -> bool:
    conn = get_connection(db_path)
    row = _load_message(conn, message_db_id)
    if not row:
        conn.close()
        return True
    if "\\Seen" in json.loads(row["flags"] or "[]"):
        conn.close()
        return True  # already read

    _set_flags_db(conn, message_db_id, row["folder_id"], add=["\\Seen"], remove=[])
    conn.commit()
    uid         = row["uid"]
    account_id  = row["account_id"]
    folder_name = row["folder_name"]
    receipt_to  = row["receipt_to"]  if "receipt_to"  in row.keys() else None
    receipt_sent = row["receipt_sent"] if "receipt_sent" in row.keys() else 1
    subject     = row["subject"]
    message_id  = row["message_id"]
    conn.close()

    # Send read receipt (MDN) if requested and not yet sent
    if receipt_to and not receipt_sent:
        try:
            acct_conn = get_connection(db_path)
            acct_row  = acct_conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
            acct_conn.close()
            if acct_row:
                from core.smtp_send import send_mdn
                threading.Thread(
                    target=lambda: _send_mdn_and_mark(
                        dict(acct_row), subject, message_id, receipt_to,
                        message_db_id, db_path
                    ),
                    daemon=True,
                ).start()
        except Exception as e:
            log.error("MDN setup error msg=%d: %s", message_db_id, e)

    def _imap_write():
        try:
            client = _imap_connect(account_id, db_path)
            if client:
                client.select_folder(folder_name, readonly=False)
                client.add_flags([uid], ["\\Seen"])
                client.logout()
        except Exception as e:
            log.error("mark_read uid=%d: %s", uid, e)

    threading.Thread(target=_imap_write, daemon=True).start()
    return True


def _send_mdn_and_mark(account, subject, message_id, receipt_to, msg_db_id, db_path):
    try:
        from core.smtp_send import send_mdn
        send_mdn(account, subject or "(no subject)", message_id or "", receipt_to)
        conn = get_connection(db_path)
        conn.execute("UPDATE messages SET receipt_sent=1 WHERE id=?", (msg_db_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        log.error("send_mdn msg=%d: %s", msg_db_id, e)


def mark_unread(message_db_id: int, db_path: str) -> bool:
    conn = get_connection(db_path)
    row = _load_message(conn, message_db_id)
    if not row:
        conn.close()
        return False

    _set_flags_db(conn, message_db_id, row["folder_id"], add=[], remove=["\\Seen"])
    conn.commit()
    uid, account_id, folder_name = row["uid"], row["account_id"], row["folder_name"]
    conn.close()

    def _imap_write():
        try:
            client = _imap_connect(account_id, db_path)
            if client:
                client.select_folder(folder_name, readonly=False)
                client.remove_flags([uid], ["\\Seen"])
                client.logout()
        except Exception as e:
            log.error("mark_unread uid=%d: %s", uid, e)

    threading.Thread(target=_imap_write, daemon=True).start()
    return True


def trash_message(message_db_id: int, db_path: str) -> bool:
    conn = get_connection(db_path)
    row = _load_message(conn, message_db_id)
    if not row:
        conn.close()
        return False

    account_id  = row["account_id"]
    uid         = row["uid"]
    src_folder  = row["folder_name"]
    folder_id   = row["folder_id"]

    trash_row = conn.execute(
        "SELECT * FROM folders WHERE account_id=? AND role='trash' LIMIT 1",
        (account_id,)
    ).fetchone()

    # Already in trash — delete from DB now, expunge IMAP in background
    if trash_row and folder_id == trash_row["id"]:
        conn.execute("DELETE FROM message_bodies WHERE message_id=?", (message_db_id,))
        conn.execute("DELETE FROM messages WHERE id=?", (message_db_id,))
        conn.commit()
        conn.close()

        def _imap_expunge():
            try:
                client = _imap_connect(account_id, db_path)
                if client:
                    client.select_folder(src_folder, readonly=False)
                    client.add_flags([uid], ["\\Deleted"])
                    client.expunge()
                    client.logout()
            except Exception as e:
                log.error("expunge uid=%d: %s", uid, e)

        threading.Thread(target=_imap_expunge, daemon=True).start()
        return True

    # Move to trash — update DB optimistically, IMAP move in background
    trash_folder_name = trash_row["name"] if trash_row else None
    trash_folder_id   = trash_row["id"]   if trash_row else None

    if trash_folder_id:
        conn.execute(
            "UPDATE messages SET folder_id=?, trashed_at=datetime('now') WHERE id=?",
            (trash_folder_id, message_db_id)
        )
        conn.commit()
    conn.close()

    if trash_folder_name:
        def _imap_move():
            try:
                client = _imap_connect(account_id, db_path)
                if client:
                    client.select_folder(src_folder, readonly=False)
                    try:
                        client.move([uid], trash_folder_name)
                    except Exception:
                        client.copy([uid], trash_folder_name)
                        client.add_flags([uid], ["\\Deleted"])
                        client.expunge()
                    client.logout()
            except Exception as e:
                log.error("trash uid=%d: %s", uid, e)

        threading.Thread(target=_imap_move, daemon=True).start()

    return True


def bulk_move_messages(message_ids: list, dst_folder_id: int, db_path: str) -> int:
    """Move a list of message DB IDs to dst_folder_id. Returns count moved."""
    if not message_ids:
        return 0

    conn = get_connection(db_path)
    dst = conn.execute("SELECT * FROM folders WHERE id=?", (dst_folder_id,)).fetchone()
    if not dst:
        conn.close()
        return 0
    dst = dict(dst)
    dst_folder_name = dst["name"]
    dst_account_id  = dst["account_id"]

    placeholders = ",".join("?" * len(message_ids))
    rows = conn.execute(f"""
        SELECT m.id, m.uid, m.account_id, m.folder_id, f.name as folder_name
        FROM messages m JOIN folders f ON f.id = m.folder_id
        WHERE m.id IN ({placeholders}) AND m.account_id=?
    """, message_ids + [dst_account_id]).fetchall()

    if not rows:
        conn.close()
        return 0

    # Update DB optimistically
    for r in rows:
        conn.execute("UPDATE messages SET folder_id=? WHERE id=?", (dst_folder_id, r["id"]))
    conn.commit()
    conn.close()

    from collections import defaultdict
    by_folder = defaultdict(list)
    for row in rows:
        by_folder[(row["account_id"], row["folder_name"])].append(dict(row))

    def _imap_bulk_move():
        for (account_id, src_folder_name), group in by_folder.items():
            uids = [r["uid"] for r in group]
            try:
                client = _imap_connect(account_id, db_path)
                if not client:
                    continue
                client.select_folder(src_folder_name, readonly=False)
                try:
                    client.move(uids, dst_folder_name)
                except Exception:
                    client.copy(uids, dst_folder_name)
                    client.add_flags(uids, ["\\Deleted"])
                    client.expunge()
                client.logout()
            except Exception as e:
                log.error("bulk_move src=%s account=%d: %s", src_folder_name, account_id, e)

    threading.Thread(target=_imap_bulk_move, daemon=True).start()
    return len(rows)


def empty_trash(account_id: int, db_path: str) -> int:
    """Permanently delete all messages in the Trash folder. Returns count deleted."""
    conn = get_connection(db_path)
    trash = conn.execute(
        "SELECT * FROM folders WHERE account_id=? AND role='trash' LIMIT 1",
        (account_id,)
    ).fetchone()
    if not trash:
        conn.close()
        return 0
    trash = dict(trash)

    rows = conn.execute(
        "SELECT id, uid FROM messages WHERE folder_id=? AND account_id=?",
        (trash["id"], account_id)
    ).fetchall()
    if not rows:
        conn.close()
        return 0

    ids  = [r["id"]  for r in rows]
    uids = [r["uid"] for r in rows]
    ph   = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM message_bodies WHERE message_id IN ({ph})", ids)
    conn.execute(f"DELETE FROM messages WHERE id IN ({ph})", ids)
    conn.execute("UPDATE folders SET message_count=0, unread_count=0 WHERE id=?", (trash["id"],))
    conn.commit()
    conn.close()

    def _imap_expunge():
        try:
            client = _imap_connect(account_id, db_path)
            if client:
                client.select_folder(trash["name"], readonly=False)
                client.add_flags(uids, ["\\Deleted"])
                client.expunge()
                client.logout()
        except Exception as e:
            log.error("empty_trash account=%d: %s", account_id, e)

    threading.Thread(target=_imap_expunge, daemon=True).start()
    return len(ids)


def mark_spam(message_db_id: int, db_path: str) -> bool:
    """Move message to spam/junk folder."""
    conn = get_connection(db_path)
    row = _load_message(conn, message_db_id)
    if not row:
        conn.close()
        return False
    account_id = row["account_id"]
    uid        = row["uid"]
    src_folder = row["folder_name"]
    folder_id  = row["folder_id"]

    spam = conn.execute(
        "SELECT * FROM folders WHERE account_id=? AND role='spam' LIMIT 1",
        (account_id,)
    ).fetchone()
    if spam and folder_id == spam["id"]:
        conn.close()
        return True  # already in spam

    spam_name = spam["name"] if spam else None
    spam_id   = spam["id"]   if spam else None

    if spam_id:
        conn.execute("UPDATE messages SET folder_id=? WHERE id=?", (spam_id, message_db_id))
        conn.commit()
    conn.close()

    if spam_name:
        def _imap_move():
            try:
                client = _imap_connect(account_id, db_path)
                if client:
                    client.select_folder(src_folder, readonly=False)
                    try:
                        client.move([uid], spam_name)
                    except Exception:
                        client.copy([uid], spam_name)
                        client.add_flags([uid], ["\\Deleted"])
                        client.expunge()
                    client.logout()
            except Exception as e:
                log.error("mark_spam uid=%d: %s", uid, e)

        threading.Thread(target=_imap_move, daemon=True).start()
    return True


def mark_not_spam(message_db_id: int, db_path: str) -> bool:
    """Move message from spam/junk back to inbox."""
    conn = get_connection(db_path)
    row = _load_message(conn, message_db_id)
    if not row:
        conn.close()
        return False
    account_id = row["account_id"]
    uid        = row["uid"]
    src_folder = row["folder_name"]

    inbox = conn.execute(
        "SELECT * FROM folders WHERE account_id=? AND role='inbox' LIMIT 1",
        (account_id,)
    ).fetchone()
    if not inbox:
        conn.close()
        return False
    inbox_id   = inbox["id"]
    inbox_name = inbox["name"]

    conn.execute("UPDATE messages SET folder_id=? WHERE id=?", (inbox_id, message_db_id))
    conn.commit()
    conn.close()

    def _imap_move():
        try:
            client = _imap_connect(account_id, db_path)
            if client:
                client.select_folder(src_folder, readonly=False)
                try:
                    client.move([uid], inbox_name)
                except Exception:
                    client.copy([uid], inbox_name)
                    client.add_flags([uid], ["\\Deleted"])
                    client.expunge()
                client.logout()
        except Exception as e:
            log.error("mark_not_spam uid=%d: %s", uid, e)

    threading.Thread(target=_imap_move, daemon=True).start()
    return True


def toggle_starred(message_db_id: int, db_path: str) -> bool:
    """Toggle \\Flagged on a message. Returns True if now starred, False if now unstarred."""
    conn = get_connection(db_path)
    row = _load_message(conn, message_db_id)
    if not row:
        conn.close()
        return False
    flags = json.loads(row["flags"] or "[]")
    was_starred = "\\Flagged" in flags
    if was_starred:
        _set_flags_db(conn, message_db_id, row["folder_id"], add=[], remove=["\\Flagged"])
    else:
        _set_flags_db(conn, message_db_id, row["folder_id"], add=["\\Flagged"], remove=[])
    conn.commit()
    uid, account_id, folder_name = row["uid"], row["account_id"], row["folder_name"]
    now_starred = not was_starred
    conn.close()

    def _imap_write():
        try:
            client = _imap_connect(account_id, db_path)
            if client:
                client.select_folder(folder_name, readonly=False)
                if now_starred:
                    client.add_flags([uid], ["\\Flagged"])
                else:
                    client.remove_flags([uid], ["\\Flagged"])
                client.logout()
        except Exception as e:
            log.error("toggle_starred uid=%d: %s", uid, e)

    threading.Thread(target=_imap_write, daemon=True).start()
    return now_starred


def purge_old_trash(db_path: str, days: int = 30) -> int:
    """Permanently delete trash messages trashed more than `days` days ago."""
    from collections import defaultdict
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT m.id, m.uid, m.account_id, f.name as folder_name
        FROM messages m
        JOIN folders f ON f.id = m.folder_id
        WHERE f.role = 'trash'
          AND m.trashed_at IS NOT NULL
          AND datetime(m.trashed_at) < datetime('now', ?)
    """, (f"-{days} days",)).fetchall()
    if not rows:
        conn.close()
        return 0

    ids = [r["id"] for r in rows]
    ph  = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM message_bodies WHERE message_id IN ({ph})", ids)
    conn.execute(f"DELETE FROM messages WHERE id IN ({ph})", ids)
    conn.commit()
    conn.close()

    by_folder = defaultdict(list)
    for r in rows:
        by_folder[(r["account_id"], r["folder_name"])].append(r["uid"])

    for (account_id, folder_name), uids in by_folder.items():
        try:
            client = _imap_connect(account_id, db_path)
            if client:
                client.select_folder(folder_name, readonly=False)
                client.add_flags(uids, ["\\Deleted"])
                client.expunge()
                client.logout()
        except Exception as e:
            log.error("purge_old_trash account=%d folder=%s: %s", account_id, folder_name, e)

    return len(ids)


def mark_all_read(message_ids: list, db_path: str) -> int:
    """Mark a list of message DB IDs as read. Returns count marked."""
    if not message_ids:
        return 0

    conn = get_connection(db_path)
    placeholders = ",".join("?" * len(message_ids))
    rows = conn.execute(f"""
        SELECT m.id, m.uid, m.account_id, m.folder_id, m.flags, f.name as folder_name
        FROM messages m JOIN folders f ON f.id = m.folder_id
        WHERE m.id IN ({placeholders})
    """, message_ids).fetchall()

    unread = [r for r in rows if "\\Seen" not in json.loads(r["flags"] or "[]")]
    if not unread:
        conn.close()
        return 0

    for r in unread:
        _set_flags_db(conn, r["id"], r["folder_id"], add=["\\Seen"], remove=[])
    conn.commit()
    conn.close()

    from collections import defaultdict
    by_folder = defaultdict(list)
    for r in unread:
        by_folder[(r["account_id"], r["folder_name"])].append(r["uid"])

    def _imap_write():
        for (account_id, folder_name), uids in by_folder.items():
            try:
                client = _imap_connect(account_id, db_path)
                if client:
                    client.select_folder(folder_name, readonly=False)
                    client.add_flags(uids, ["\\Seen"])
                    client.logout()
            except Exception as e:
                log.error("mark_all_read account=%d folder=%s: %s", account_id, folder_name, e)

    threading.Thread(target=_imap_write, daemon=True).start()
    return len(unread)


def move_message(message_db_id: int, dst_folder_id: int, db_path: str) -> bool:
    conn = get_connection(db_path)
    row = _load_message(conn, message_db_id)
    dst = conn.execute("SELECT * FROM folders WHERE id=?", (dst_folder_id,)).fetchone()
    if not row or not dst:
        conn.close()
        return False

    account_id = row["account_id"]
    uid        = row["uid"]
    src_folder = row["folder_name"]
    dst_folder = dst["name"]

    conn.execute("UPDATE messages SET folder_id=? WHERE id=?", (dst_folder_id, message_db_id))
    conn.commit()
    conn.close()

    def _imap_move():
        try:
            client = _imap_connect(account_id, db_path)
            if client:
                client.select_folder(src_folder, readonly=False)
                try:
                    client.move([uid], dst_folder)
                except Exception:
                    client.copy([uid], dst_folder)
                    client.add_flags([uid], ["\\Deleted"])
                    client.expunge()
                client.logout()
        except Exception as e:
            log.error("move uid=%d: %s", uid, e)

    threading.Thread(target=_imap_move, daemon=True).start()
    return True
