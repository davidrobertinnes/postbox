"""
IMAP write-back operations — mark read/unread, trash, move.
Each function makes its own IMAP connection (thread-safe, no shared state).
Local DB is updated first; IMAP write is best-effort.
"""
import json
import logging

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
    if not row or "Seen" in (row["flags"] or ""):
        conn.close()
        return True  # already read

    _set_flags_db(conn, message_db_id, row["folder_id"], add=["\\Seen"], remove=[])
    conn.commit()
    uid, account_id, folder_name = row["uid"], row["account_id"], row["folder_name"]
    conn.close()

    try:
        client = _imap_connect(account_id, db_path)
        if client:
            client.select_folder(folder_name, readonly=False)
            client.add_flags([uid], ["\\Seen"])
            client.logout()
            return True
    except Exception as e:
        log.error("mark_read uid=%d: %s", uid, e)
    return False


def mark_unread(message_db_id: int, db_path: str) -> bool:
    conn = get_connection(db_path)
    row = _load_message(conn, message_db_id)
    if not row:
        conn.close()
        return False

    _set_flags_db(conn, message_db_id, row["folder_id"], add=[], remove=["\\Seen", "\\\\Seen", "Seen"])
    conn.commit()
    uid, account_id, folder_name = row["uid"], row["account_id"], row["folder_name"]
    conn.close()

    try:
        client = _imap_connect(account_id, db_path)
        if client:
            client.select_folder(folder_name, readonly=False)
            client.remove_flags([uid], ["\\Seen"])
            client.logout()
            return True
    except Exception as e:
        log.error("mark_unread uid=%d: %s", uid, e)
    return False


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

    # Already in trash — expunge permanently
    if trash_row and folder_id == trash_row["id"]:
        try:
            client = _imap_connect(account_id, db_path)
            if client:
                client.select_folder(src_folder, readonly=False)
                client.add_flags([uid], ["\\Deleted"])
                client.expunge()
                client.logout()
        except Exception as e:
            log.error("expunge uid=%d: %s", uid, e)
        conn.execute("DELETE FROM message_bodies WHERE message_id=?", (message_db_id,))
        conn.execute("DELETE FROM messages WHERE id=?", (message_db_id,))
        conn.commit()
        conn.close()
        return True

    # Move to trash
    trash_folder_name = trash_row["name"] if trash_row else None
    trash_folder_id   = trash_row["id"]   if trash_row else None
    conn.close()

    moved = False
    if trash_folder_name:
        try:
            client = _imap_connect(account_id, db_path)
            if client:
                client.select_folder(src_folder, readonly=False)
                try:
                    client.move([uid], trash_folder_name)
                except Exception:
                    # Fallback: COPY + DELETE for servers without MOVE extension
                    client.copy([uid], trash_folder_name)
                    client.add_flags([uid], ["\\Deleted"])
                    client.expunge()
                client.logout()
                moved = True
        except Exception as e:
            log.error("trash uid=%d: %s", uid, e)

    if moved and trash_folder_id:
        conn = get_connection(db_path)
        conn.execute(
            "UPDATE messages SET folder_id=? WHERE id=?",
            (trash_folder_id, message_db_id)
        )
        conn.commit()
        conn.close()

    return moved


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
    conn.close()

    moved = False
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
            moved = True
    except Exception as e:
        log.error("move uid=%d: %s", uid, e)

    if moved:
        conn = get_connection(db_path)
        conn.execute(
            "UPDATE messages SET folder_id=? WHERE id=?",
            (dst_folder_id, message_db_id)
        )
        conn.commit()
        conn.close()

    return moved
