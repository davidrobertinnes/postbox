"""
Outbox — queue and retry messages that failed due to network errors.
"""
import logging
import threading
import time

log = logging.getLogger(__name__)

_NETWORK_STRINGS = (
    'connection refused', 'timed out', 'timeout',
    'network unreachable', 'no route to host',
    'name or service not known', 'connection reset',
    'connection aborted', 'temporarily failed',
    'could not connect', '[errno 111]', '[errno 110]',
    '[errno 113]', '[errno 101]', '[errno 104]',
    'eof occurred in violation', 'server disconnected',
    'gaierror', 'getaddrinfo failed',
)


def is_network_error(error_msg: str) -> bool:
    lower = error_msg.lower()
    return any(p in lower for p in _NETWORK_STRINGS)


def queue_message(db_path: str, account_id: int, to: str, subject: str,
                  body: str, cc=None, bcc=None, reply_to_msg_id=None,
                  references_hdr=None, request_receipt=False,
                  draft_id=None, attachments=None) -> int:
    from core.database import get_connection
    conn = get_connection(db_path)
    cur = conn.execute("""
        INSERT INTO outbox
            (account_id, to_addrs, cc_addrs, bcc_addrs, subject, body_text,
             reply_to_msg_id, references_hdr, request_receipt, draft_id)
        VALUES (?,?,?,?,?,?,?,?,?,?)
    """, (account_id, to, cc or '', bcc or '', subject, body,
          reply_to_msg_id, references_hdr, 1 if request_receipt else 0, draft_id))
    outbox_id = cur.lastrowid
    if attachments:
        for filename, content_type, data in attachments:
            conn.execute("""
                INSERT INTO outbox_attachments (outbox_id, filename, content_type, data)
                VALUES (?,?,?,?)
            """, (outbox_id, filename, content_type, data))
    conn.commit()
    conn.close()
    return outbox_id


def retry_outbox(db_path: str) -> int:
    from core.database import get_connection
    from core.smtp_send import send_message

    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM outbox WHERE status='pending' ORDER BY created_at"
    ).fetchall()
    conn.close()

    sent = 0
    for row in rows:
        row        = dict(row)
        outbox_id  = row['id']
        account_id = row['account_id']

        conn     = get_connection(db_path)
        acct     = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        att_rows = conn.execute(
            "SELECT filename, content_type, data FROM outbox_attachments WHERE outbox_id=?",
            (outbox_id,)
        ).fetchall()
        conn.close()

        if not acct:
            conn = get_connection(db_path)
            conn.execute("UPDATE outbox SET status='failed', error='Account not found' WHERE id=?", (outbox_id,))
            conn.commit()
            conn.close()
            continue

        attachments = [(r['filename'], r['content_type'], bytes(r['data'])) for r in att_rows] or None

        ok_sent, msg = send_message(
            account=dict(acct),
            to=row['to_addrs'],
            subject=row['subject'] or '',
            body=row['body_text'] or '',
            cc=row['cc_addrs'] or None,
            bcc=row['bcc_addrs'] or None,
            reply_to_msg_id=row['reply_to_msg_id'],
            references=row['references_hdr'],
            request_receipt=bool(row['request_receipt']),
            attachments=attachments,
        )

        conn = get_connection(db_path)
        if ok_sent:
            conn.execute("DELETE FROM outbox WHERE id=?", (outbox_id,))
            if row.get('draft_id'):
                try:
                    conn.execute("DELETE FROM messages WHERE id=?", (row['draft_id'],))
                except Exception:
                    pass
            sent += 1
            log.info("Outbox: sent queued message id=%d", outbox_id)
        else:
            attempts = row['attempts'] + 1
            status   = 'failed' if attempts >= 10 else 'pending'
            conn.execute("""
                UPDATE outbox SET attempts=?, last_attempt=datetime('now','localtime'),
                status=?, error=? WHERE id=?
            """, (attempts, status, msg, outbox_id))
        conn.commit()
        conn.close()

    return sent


def get_outbox_items(db_path: str) -> list:
    from core.database import get_connection
    conn = get_connection(db_path)
    rows = conn.execute("""
        SELECT o.id, o.account_id, o.to_addrs, o.subject, o.created_at,
               o.last_attempt, o.attempts, o.status, o.error,
               a.name as account_name, a.email as account_email
        FROM outbox o
        LEFT JOIN accounts a ON a.id = o.account_id
        ORDER BY o.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def start_outbox_retry(db_path: str):
    def _loop():
        while True:
            time.sleep(60)
            try:
                n = retry_outbox(db_path)
                if n:
                    log.info("Outbox retry: sent %d queued message(s)", n)
            except Exception as e:
                log.error("Outbox retry loop: %s", e)

    threading.Thread(target=_loop, daemon=True, name="outbox-retry").start()
