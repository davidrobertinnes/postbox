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

_OAUTH_AUTH_TYPES = {"oauth_microsoft", "oauth_google"}


# ── Re-auth helpers ────────────────────────────────────────────────────────────

def _is_auth_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(kw in msg for kw in (
        'invalid_grant', 'token has been expired', 'token has been revoked',
        'no oauth tokens', 're-authenticate', 'token expired',
        'authenticationfailed', 'authentication failed', 'invalid credentials',
    )) or type(e).__name__ == 'RefreshError'


def _set_needs_reauth(account_id: int, db_path: str) -> None:
    try:
        conn = get_connection(db_path)
        conn.execute("UPDATE accounts SET needs_reauth=1 WHERE id=?", (account_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _clear_needs_reauth(account_id: int, db_path: str) -> None:
    try:
        conn = get_connection(db_path)
        conn.execute("UPDATE accounts SET needs_reauth=0 WHERE id=?", (account_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── Connection helpers ─────────────────────────────────────────────────────────

def _make_client(account: dict, password: str | None = None):
    """Create and return a logged-in IMAPClient. Handles password and OAuth."""
    from imapclient import IMAPClient
    ssl = bool(account.get("imap_ssl", 1))
    client = IMAPClient(
        host=account["imap_host"],
        port=account["imap_port"],
        ssl=ssl,
        timeout=15,
    )
    auth_type = account.get("auth_type", "password")
    if auth_type == "oauth_microsoft":
        from core.oauth_microsoft import get_valid_access_token
        token = get_valid_access_token(account["id"], account.get("email", ""))
        client.oauth2_login(account.get("username") or account.get("email", ""), token)
    elif auth_type == "oauth_google":
        from core.oauth_google import get_valid_access_token
        token = get_valid_access_token(account["id"], account.get("email", ""))
        client.oauth2_login(account.get("username") or account.get("email", ""), token)
    else:
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
    "inbox":            "inbox",
    "sent":             "sent",
    "sent items":       "sent",
    "sent mail":        "sent",
    "sent messages":    "sent",
    "drafts":           "drafts",
    "draft":            "drafts",
    "trash":            "trash",
    "deleted":          "trash",
    "deleted items":    "trash",
    "deleted messages": "trash",
    "bin":              "trash",
    "junk":             "spam",
    "spam":             "spam",
    "junk e-mail":      "spam",
    "bulk mail":        "spam",
    "junk mail":        "spam",
}

# Gmail virtual folders that duplicate messages already covered by other folders.
# Syncing these causes every email to appear 2-3 times in the DB.
_GMAIL_SKIP_FOLDERS = {
    "[gmail]/all mail",
    "[gmail]/important",
    "[gmail]/starred",
    "[gmail]",          # container pseudo-folder
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
    password = None
    if account.get("auth_type") not in _OAUTH_AUTH_TYPES:
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
    # Phase 1: read what we need, then release the DB connection
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not row:
        conn.close()
        return 0
    account = dict(row)

    folder_row = conn.execute(
        "SELECT * FROM folders WHERE account_id=? AND (role='inbox' OR LOWER(name)='inbox') LIMIT 1",
        (account_id,)
    ).fetchone()
    if not folder_row:
        conn.close()
        return 0

    folder_id = folder_row["id"]
    existing = set(r[0] for r in conn.execute(
        "SELECT uid FROM messages WHERE account_id=? AND folder_id=?",
        (account_id, folder_id)
    ).fetchall())
    conn.close()

    password = None
    if account.get("auth_type") not in _OAUTH_AUTH_TYPES:
        password = get_password(account_id)
        if not password:
            return 0

    # Phase 2: IMAP fetch — no DB connection open
    results = []
    total_uids = 0
    unseen_count = 0
    try:
        client = _make_client(account, password)
        client.select_folder("INBOX", readonly=True)
        uids = client.search("ALL")
        if not uids:
            client.logout()
            return 0
        total_uids = len(uids)
        new_uids = [u for u in uids if u not in existing][-max_msgs:]
        if new_uids:
            fetch_data = client.fetch(new_uids, ["ENVELOPE", "FLAGS", "RFC822.SIZE", "BODYSTRUCTURE"])
            results = list(fetch_data.items())
        unseen_count = len(client.search("UNSEEN"))
        client.logout()
    except Exception as e:
        log.error("sync_inbox account=%d: %s", account_id, e)
        return 0

    # Phase 3: write results in a short-lived connection
    new_count = 0
    conn = get_connection(db_path)
    try:
        for uid, data in results:
            _store_envelope(conn, account_id, folder_id, uid, data)
            new_count += 1
        conn.execute(
            "UPDATE folders SET unread_count=?, message_count=? WHERE id=?",
            (unseen_count, total_uids, folder_id)
        )
        conn.execute(
            "UPDATE accounts SET last_sync=datetime('now','localtime') WHERE id=?",
            (account_id,)
        )
        conn.commit()
    except Exception as e:
        log.error("sync_inbox write account=%d: %s", account_id, e)
    finally:
        conn.close()

    return new_count


def sync_all_folders_messages(account_id: int, db_path: str, max_msgs: int = 100) -> int:
    """Sync message headers for all folders in one IMAP connection."""
    # Phase 1: read account + folders + existing UIDs, then release the DB connection
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    if not row:
        conn.close()
        return 0
    account = dict(row)
    folders = [dict(r) for r in conn.execute(
        "SELECT * FROM folders WHERE account_id=?", (account_id,)
    ).fetchall()]
    existing_by_folder = {
        f["id"]: set(
            r[0] for r in conn.execute(
                "SELECT uid FROM messages WHERE account_id=? AND folder_id=?",
                (account_id, f["id"])
            ).fetchall()
        )
        for f in folders
    }
    conn.close()

    password = None
    if account.get("auth_type") not in _OAUTH_AUTH_TYPES:
        password = get_password(account_id)
        if not password:
            return 0

    # Phase 2: IMAP fetch — no DB connection open
    # results: list of (folder_id, uid, imap_data)
    # folder_counts: folder_id -> (message_count, unread_count or None)
    results = []
    folder_counts = {}
    total_new = 0
    try:
        client = _make_client(account, password)
        for folder_row in folders:
            folder_id   = folder_row["id"]
            folder_name = folder_row["name"]
            if folder_name.lower() in _GMAIL_SKIP_FOLDERS:
                continue
            try:
                client.select_folder(folder_name, readonly=True)
                uids = client.search("ALL")
                if not uids:
                    folder_counts[folder_id] = (0, 0)
                    continue

                existing = existing_by_folder.get(folder_id, set())
                new_uids = [u for u in uids if u not in existing][-max_msgs:]

                if new_uids:
                    fetch_data = client.fetch(new_uids, ["ENVELOPE", "FLAGS", "RFC822.SIZE", "BODYSTRUCTURE"])
                    for uid, data in fetch_data.items():
                        results.append((folder_id, uid, data))
                        total_new += 1

                try:
                    unseen = client.search("UNSEEN")
                    folder_counts[folder_id] = (len(uids), len(unseen))
                except Exception:
                    folder_counts[folder_id] = (len(uids), None)

            except Exception as e:
                log.debug("sync folder '%s' account=%d: %s", folder_name, account_id, e)
                continue

        try:
            client.logout()
        except Exception:
            pass

    except Exception as e:
        log.error("sync_all_folders_messages account=%d: %s", account_id, e)
        return total_new

    # Phase 3: write results in a short-lived connection
    conn = get_connection(db_path)
    try:
        for folder_id, uid, data in results:
            _store_envelope(conn, account_id, folder_id, uid, data)
        for folder_id, (msg_count, unread_count) in folder_counts.items():
            if unread_count is not None:
                conn.execute(
                    "UPDATE folders SET unread_count=?, message_count=? WHERE id=?",
                    (unread_count, msg_count, folder_id)
                )
            else:
                conn.execute(
                    "UPDATE folders SET message_count=? WHERE id=?",
                    (msg_count, folder_id)
                )
        conn.execute(
            "UPDATE accounts SET last_sync=datetime('now','localtime') WHERE id=?",
            (account_id,)
        )
        conn.commit()
    except Exception as e:
        log.error("sync_all_folders_messages write account=%d: %s", account_id, e)
    finally:
        conn.close()

    return total_new


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

    # Thread ID: resolve to the root thread by looking up the parent's thread_id.
    # This chains A→B→C correctly even for long threads.
    if in_reply_to:
        parent = conn.execute(
            "SELECT thread_id FROM messages WHERE message_id=? AND account_id=?",
            (in_reply_to, account_id)
        ).fetchone()
        thread_id = parent["thread_id"] if parent else in_reply_to
    else:
        thread_id = message_id

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
    if body_struct is None or not isinstance(body_struct, (list, tuple)):
        return 0
    # The multipart subtype is the last string element (b'MIXED', b'ALTERNATIVE', etc.)
    subtype = ''
    for item in reversed(body_struct):
        if isinstance(item, (str, bytes)):
            subtype = (item.decode('ascii', errors='replace') if isinstance(item, bytes) else item).upper()
            break
    # ALTERNATIVE = plain+html variants of the same content; RELATED = HTML + inline images.
    # Neither carries downloadable attachments.
    if subtype in ('ALTERNATIVE', 'RELATED'):
        return 0
    return 1


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
    password = None
    if account.get("auth_type") not in _OAUTH_AUTH_TYPES:
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
        atts = parsed.get("attachments", [])
        conn.execute(
            "UPDATE messages SET body_fetched=1, snippet=?, has_attachments=? WHERE id=?",
            (parsed["snippet"], 1 if atts else 0, message_db_id)
        )
        for att in atts:
            conn.execute("""
                INSERT INTO attachments (message_id, filename, content_type, size)
                VALUES (?, ?, ?, ?)
            """, (message_db_id, att["filename"], att["content_type"], att["size"]))
        conn.commit()
        client.logout()
        return True
    except Exception as e:
        if _is_auth_error(e):
            log.warning("Auth failure fetching body for account=%d: %s", account_id, e)
            _set_needs_reauth(account_id, db_path)
        else:
            log.error("fetch_body uid=%s: %s", uid, e)
        return False
    finally:
        conn.close()


def fetch_raw(account_id: int, uid: int, folder_name: str, db_path: str) -> bytes | None:
    """Fetch raw RFC822 bytes for a single message without storing anything."""
    conn = get_connection(db_path)
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    conn.close()
    if not row:
        return None
    account = dict(row)
    password = None
    if account.get("auth_type") not in _OAUTH_AUTH_TYPES:
        password = get_password(account_id)
    try:
        client = _make_client(account, password)
        client.select_folder(folder_name, readonly=True)
        data = client.fetch([uid], ["RFC822"])
        client.logout()
        return data[uid][b"RFC822"]
    except Exception as e:
        if _is_auth_error(e):
            log.warning("Auth failure in fetch_raw for account=%d: %s", account_id, e)
            _set_needs_reauth(account_id, db_path)
        else:
            log.error("fetch_raw uid=%s: %s", uid, e)
        return None


# ── Background sync loop — IDLE with polling fallback ─────────────────────────

_IDLE_MAX_SECS     = 29 * 60   # re-IDLE before server's 30-min limit
_FULL_SYNC_INTERVAL = 10 * 60  # full all-folder sync every 10 min


def _idle_watch(client, stop: threading.Event, max_secs: int = _IDLE_MAX_SECS) -> bool:
    """
    Enter IMAP IDLE and block until EXISTS/RECENT push, stop event, or timeout.
    Returns True if new mail was signalled.
    """
    client.idle()
    deadline = time.monotonic() + max_secs
    new_mail = False
    try:
        while not stop.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            responses = client.idle_check(timeout=min(1.0, remaining))
            for resp in (responses or []):
                if len(resp) >= 2 and resp[1] in (b"EXISTS", b"RECENT"):
                    new_mail = True
            if new_mail:
                break
    except Exception as e:
        log.debug("idle_watch: %s", e)
    finally:
        try:
            client.idle_done()
        except Exception:
            pass
    return new_mail


def _sync_loop_idle(account_id: int, db_path: str, stop: threading.Event) -> None:
    """
    Main sync loop for one account. Uses IMAP IDLE on the inbox for real-time
    new-mail detection; falls back to 60s polling if server lacks IDLE.
    Full all-folder sync runs every _FULL_SYNC_INTERVAL seconds regardless.
    """
    last_full = 0.0

    while not stop.is_set():
        # Full all-folder sync on schedule
        if time.monotonic() - last_full >= _FULL_SYNC_INTERVAL:
            try:
                sync_all_folders_messages(account_id, db_path)
                last_full = time.monotonic()
            except Exception as e:
                log.error("full sync account=%d: %s", account_id, e)

        # Connect for IDLE (or polling fallback)
        try:
            conn = get_connection(db_path)
            acct_row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
            conn.close()
            if not acct_row:
                break

            auth_type = acct_row["auth_type"] or "password"
            password = None
            if auth_type not in _OAUTH_AUTH_TYPES:
                password = get_password(account_id)
                if not password:
                    stop.wait(60)
                    continue

            client = _make_client(dict(acct_row), password)
            _clear_needs_reauth(account_id, db_path)
            caps = client.capabilities()
            has_idle = b"IDLE" in caps or "IDLE" in caps

            if not has_idle:
                # Polling fallback — sync now, wait 60s
                client.logout()
                stop.wait(60)
                try:
                    sync_all_folders_messages(account_id, db_path)
                    last_full = time.monotonic()
                except Exception as e:
                    log.error("poll sync account=%d: %s", account_id, e)
                continue

            # Find inbox folder name
            conn = get_connection(db_path)
            inbox_row = conn.execute(
                "SELECT name FROM folders WHERE account_id=? AND role='inbox' LIMIT 1",
                (account_id,)
            ).fetchone()
            conn.close()
            inbox_name = inbox_row["name"] if inbox_row else "INBOX"

            client.select_folder(inbox_name)
            got_new = _idle_watch(client, stop)

            try:
                client.logout()
            except Exception:
                pass

            if got_new and not stop.is_set():
                try:
                    sync_inbox(account_id, db_path)
                except Exception as e:
                    log.error("inbox sync after IDLE account=%d: %s", account_id, e)

        except Exception as e:
            if _is_auth_error(e):
                log.warning("Auth failure account=%d — re-auth required: %s", account_id, e)
                _set_needs_reauth(account_id, db_path)
                stop.wait(3600)  # Don't hammer retries on auth failure
            else:
                log.error("idle loop account=%d: %s", account_id, e)
                stop.wait(30)


def start_sync(account_id: int, db_path: str, interval: int = 60) -> None:
    """Start a background IDLE/sync thread for this account."""
    if account_id in _sync_threads and _sync_threads[account_id].is_alive():
        return
    stop = threading.Event()
    _stop_events[account_id] = stop

    def _loop():
        sync_folders(account_id, db_path)
        _sync_loop_idle(account_id, db_path, stop)

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
