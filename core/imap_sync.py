"""
IMAP sync engine.
- test_connection: validate account credentials
- sync_account: fetch folder list + new message headers
- Background sync thread management
"""
import threading
import time
import json
import logging
import email.header as _email_header

from core.database import get_connection
from core.credentials import get_password
from core.email_parser import parse_raw

log = logging.getLogger(__name__)

# {account_id: threading.Thread}
_sync_threads: dict[int, threading.Thread] = {}
_stop_events: dict[int, threading.Event] = {}


# ── Connection helpers ─────────────────────────────────────────────────────────

def _make_client(account: dict, password: str):
    """Create and return a logged-in IMAPClient."""
    from imapclient import IMAPClient
    ssl = bool(account.get("imap_ssl", 1))
    client = IMAPClient(
        host=account["imap_host"],
        port=account["imap_port"],
        ssl=ssl,
        timeout=15,
    )
    client.login(account["username"], password)
    return client


def test_connection(account: dict, password: str) -> tuple[bool, str]:
    """
    Try to log in via IMAP. Returns (ok, message).
    account dict needs: imap_host, imap_port, imap_ssl, username
    """
    try:
        client = _make_client(account, password)
        client.logout()
        return True, "Connected successfully"
    except Exception as e:
        return False, str(e)


# ── Folder sync ────────────────────────────────────────────────────────────────

_FOLDER_ROLE_MAP = {
    "inbox":   "inbox",
    "sent":    "sent",
    "drafts":  "drafts",
    "draft":   "drafts",
    "trash":   "trash",
    "deleted": "trash",
    "junk":    "spam",
    "spam":    "spam",
}


def _guess_role(name: str) -> str | None:
    low = name.lower().split("/")[-1]  # last path component
    return _FOLDER_ROLE_MAP.get(low)


def sync_folders(account_id: int, db_path: str) -> None:
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not row:
        conn.close()
        return
    account = dict(row)
    password = get_password(account_id)
    if not password:
        conn.close()
        return

    try:
        client = _make_client(account, password)
        folders = client.list_folders()
        for flags, delimiter, name in folders:
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="replace")
            if isinstance(delimiter, bytes):
                delimiter = delimiter.decode("utf-8", errors="replace")
            role = _guess_role(name)
            display = name.split(delimiter or "/")[-1] if delimiter else name
            conn.execute("""
                INSERT INTO folders (account_id, name, display_name, role)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(account_id, name) DO UPDATE SET
                    display_name=excluded.display_name,
                    role=excluded.role
            """, (account_id, name, display, role))
        conn.commit()
        client.logout()
    except Exception as e:
        log.error("sync_folders account=%d: %s", account_id, e)
    finally:
        conn.close()


# ── Message header sync ────────────────────────────────────────────────────────

def sync_inbox(account_id: int, db_path: str, max_msgs: int = 200) -> int:
    """
    Fetch message headers for the INBOX folder. Returns number of new messages stored.
    """
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not row:
        conn.close()
        return 0
    account = dict(row)
    password = get_password(account_id)
    if not password:
        conn.close()
        return 0

    folder_row = conn.execute(
        "SELECT * FROM folders WHERE account_id=? AND (role='inbox' OR LOWER(name)='inbox') LIMIT 1",
        (account_id,)
    ).fetchone()
    if not folder_row:
        conn.close()
        return 0

    folder_id = folder_row["id"]
    new_count = 0

    try:
        client = _make_client(account, password)
        client.select_folder("INBOX", readonly=True)

        # Fetch most recent UIDs
        uids = client.search("ALL")
        if not uids:
            client.logout()
            conn.close()
            return 0

        # Only fetch UIDs we haven't seen
        existing = set(r[0] for r in conn.execute(
            "SELECT uid FROM messages WHERE account_id=? AND folder_id=?",
            (account_id, folder_id)
        ).fetchall())
        new_uids = [u for u in uids if u not in existing]
        new_uids = new_uids[-max_msgs:]  # limit to most recent

        if new_uids:
            fetch_data = client.fetch(new_uids, ["ENVELOPE", "FLAGS", "RFC822.SIZE", "BODYSTRUCTURE"])
            for uid, data in fetch_data.items():
                _store_envelope(conn, account_id, folder_id, uid, data)
                new_count += 1

        # Update unread count
        unseen = client.search("UNSEEN")
        conn.execute(
            "UPDATE folders SET unread_count=?, message_count=? WHERE id=?",
            (len(unseen), len(uids), folder_id)
        )
        conn.execute(
            "UPDATE accounts SET last_sync=datetime('now','localtime') WHERE id=?",
            (account_id,)
        )
        conn.commit()
        client.logout()

    except Exception as e:
        log.error("sync_inbox account=%d: %s", account_id, e)
    finally:
        conn.close()

    return new_count


def _store_envelope(conn, account_id: int, folder_id: int, uid: int, data: dict) -> None:
    """Parse IMAP ENVELOPE data and insert/ignore into messages table."""
    env = data.get(b"ENVELOPE")
    if not env:
        return

    flags = data.get(b"FLAGS", ())
    flags_json = json.dumps([
        f.decode("utf-8", errors="replace") if isinstance(f, bytes) else str(f)
        for f in flags
    ])

    subject = _decode_mime(_decode_imap_str(env.subject)) or "(no subject)"
    from_addr, from_name = _parse_imap_addr(env.from_)
    to_addrs = json.dumps([{"addr": a, "name": n} for a, n in _parse_imap_addr_list(env.to)])
    cc_addrs = json.dumps([{"addr": a, "name": n} for a, n in _parse_imap_addr_list(env.cc)])
    message_id = (_decode_imap_str(env.message_id) or "").strip()
    in_reply_to = (_decode_imap_str(env.in_reply_to) or "").strip()
    date_str = env.date.strftime("%Y-%m-%dT%H:%M:%S") if env.date else None

    # Thread ID: use In-Reply-To root or own Message-ID
    thread_id = in_reply_to if in_reply_to else message_id

    # Detect attachments via BODYSTRUCTURE (rough heuristic)
    body_struct = data.get(b"BODYSTRUCTURE")
    has_attachments = _has_attachments(body_struct)

    conn.execute("""
        INSERT OR IGNORE INTO messages
            (account_id, folder_id, uid, message_id, thread_id,
             from_addr, from_name, to_addrs, cc_addrs,
             subject, date, flags, has_attachments)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        account_id, folder_id, uid, message_id, thread_id,
        from_addr, from_name, to_addrs, cc_addrs,
        subject, date_str, flags_json, has_attachments
    ))


def _decode_mime(val: str | None) -> str | None:
    """Decode RFC 2047 encoded words in a header string."""
    if not val:
        return val
    try:
        parts = _email_header.decode_header(val)
        decoded = []
        for part, charset in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(charset or "utf-8", errors="replace"))
            else:
                decoded.append(part)
        return "".join(decoded)
    except Exception:
        return val


def _decode_imap_str(val) -> str | None:
    if val is None:
        return None
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return str(val)


def _parse_imap_addr(addr_list) -> tuple[str, str]:
    """Return (address, name) from the first entry of an IMAP address list."""
    if not addr_list:
        return ("", "")
    a = addr_list[0]
    mailbox = _decode_imap_str(a.mailbox) or ""
    host = _decode_imap_str(a.host) or ""
    name = _decode_mime(_decode_imap_str(a.name)) or ""
    addr = f"{mailbox}@{host}".lower() if host else mailbox
    return (addr, name)


def _parse_imap_addr_list(addr_list) -> list[tuple[str, str]]:
    if not addr_list:
        return []
    result = []
    for a in addr_list:
        mailbox = _decode_imap_str(a.mailbox) or ""
        host = _decode_imap_str(a.host) or ""
        name = _decode_mime(_decode_imap_str(a.name)) or ""
        addr = f"{mailbox}@{host}".lower() if host else mailbox
        if addr:
            result.append((addr, name))
    return result


def _has_attachments(body_struct) -> int:
    """Rough check: if BODYSTRUCTURE contains more than one part, likely has attachments."""
    if body_struct is None:
        return 0
    if isinstance(body_struct, (list, tuple)):
        if len(body_struct) > 1 and isinstance(body_struct[0], (list, tuple)):
            return 1
    return 0


# ── Full body fetch ────────────────────────────────────────────────────────────

def fetch_body(message_db_id: int, account_id: int, uid: int,
               folder_name: str, db_path: str) -> bool:
    """Fetch full RFC822 body for a message and store in message_bodies."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not row:
        conn.close()
        return False
    account = dict(row)
    password = get_password(account_id)

    try:
        client = _make_client(account, password)
        client.select_folder(folder_name, readonly=True)
        data = client.fetch([uid], ["RFC822"])
        raw = data[uid][b"RFC822"]
        parsed = parse_raw(raw)
        conn.execute("""
            INSERT OR REPLACE INTO message_bodies (message_id, body_text, body_html)
            VALUES (?, ?, ?)
        """, (message_db_id, parsed["body_text"], parsed["body_html"]))
        conn.execute(
            "UPDATE messages SET body_fetched=1, snippet=? WHERE id=?",
            (parsed["snippet"], message_db_id)
        )
        # Store attachments
        for att in parsed.get("attachments", []):
            conn.execute("""
                INSERT INTO attachments (message_id, filename, content_type, size)
                VALUES (?, ?, ?, ?)
            """, (message_db_id, att["filename"], att["content_type"], att["size"]))
        conn.commit()
        client.logout()
        return True
    except Exception as e:
        log.error("fetch_body uid=%d: %s", uid, e)
        return False
    finally:
        conn.close()


# ── Background sync loop ───────────────────────────────────────────────────────

def start_sync(account_id: int, db_path: str, interval: int = 60) -> None:
    """Start a background thread that syncs this account every `interval` seconds."""
    if account_id in _sync_threads and _sync_threads[account_id].is_alive():
        return
    stop = threading.Event()
    _stop_events[account_id] = stop

    def _loop():
        sync_folders(account_id, db_path)
        while not stop.is_set():
            try:
                sync_inbox(account_id, db_path)
            except Exception as e:
                log.error("sync loop account=%d: %s", account_id, e)
            stop.wait(interval)

    t = threading.Thread(target=_loop, daemon=True, name=f"sync-{account_id}")
    _sync_threads[account_id] = t
    t.start()


def stop_sync(account_id: int) -> None:
    if account_id in _stop_events:
        _stop_events[account_id].set()


def start_all(db_path: str) -> None:
    """Start sync threads for all active accounts."""
    from core.database import get_connection as _gc
    conn = _gc(db_path)
    rows = conn.execute("SELECT id FROM accounts WHERE active=1").fetchall()
    conn.close()
    for row in rows:
        start_sync(row["id"], db_path)
