"""
Email filter rules — applied to newly-arrived messages during sync.
Rules are checked after whitelist/blacklist. All actions produce local DB changes
immediately; IMAP moves (spam/trash/move) are carried out via imap_actions which
handles IMAP write-back in the same call.
"""
import json
import logging

log = logging.getLogger(__name__)


def _sender_matches(pattern: str, from_addr: str) -> bool:
    """Match from_addr against an exact email or @domain.com pattern."""
    pattern = pattern.lower().strip()
    if pattern.startswith('@'):
        return from_addr.endswith(pattern)
    return from_addr == pattern


def apply_rules_to_message(message_id: int, db_path: str) -> bool:
    """Apply rules to a message. Returns True if any rule or list entry fired."""
    from core.database import get_connection
    conn = get_connection(db_path)
    row = conn.execute("""
        SELECT m.*, f.role as folder_role
        FROM messages m JOIN folders f ON f.id = m.folder_id
        WHERE m.id=?
    """, (message_id,)).fetchone()
    if not row:
        conn.close()
        return False
    msg = dict(row)
    account_id = msg["account_id"]
    from_addr  = (msg.get("from_addr") or "").lower()

    # Whitelist — skip all rules for this sender/domain
    if from_addr:
        wl = conn.execute(
            "SELECT email FROM sender_lists WHERE account_id=? AND list_type='whitelist'",
            (account_id,)
        ).fetchall()
        if any(_sender_matches(r["email"], from_addr) for r in wl):
            conn.close()
            return False

    # Blacklist — auto-spam
    if from_addr:
        bl = conn.execute(
            "SELECT email FROM sender_lists WHERE account_id=? AND list_type='blacklist'",
            (account_id,)
        ).fetchall()
        if any(_sender_matches(r["email"], from_addr) for r in bl):
            conn.close()
            _do_action("spam", account_id, message_id, None, db_path)
            return True

    rules = [dict(r) for r in conn.execute(
        "SELECT * FROM rules WHERE account_id=? AND active=1 ORDER BY priority DESC, id",
        (account_id,)
    ).fetchall()]
    conn.close()

    fired = False
    for rule in rules:
        if _matches(rule, msg):
            fired = True
            terminal = _do_action(
                rule["action"], account_id, message_id,
                rule.get("action_folder_id"), db_path
            )
            if terminal:
                break

    return fired


def _matches(rule: dict, msg: dict) -> bool:
    field = rule["condition_field"]
    op    = rule["condition_op"]
    val   = (rule["condition_value"] or "").lower()

    if field == "from":
        hay = ((msg.get("from_addr") or "") + " " + (msg.get("from_name") or "")).lower()
    elif field == "to":
        hay = (msg.get("to_addrs") or "").lower()
    elif field == "subject":
        hay = (msg.get("subject") or "").lower()
    else:  # any
        hay = " ".join(str(msg.get(k) or "") for k in
                       ("from_addr", "from_name", "subject", "snippet")).lower()

    if op == "contains":     return val in hay
    if op == "not_contains": return val not in hay
    if op == "equals":       return hay.strip() == val
    if op == "starts_with":  return hay.strip().startswith(val)
    return False


def _do_action(action: str, account_id: int, msg_id: int,
               folder_id, db_path: str) -> bool:
    """Carry out one rule action. Returns True if this terminates the rule chain."""
    try:
        if action == "mark_read":
            from core.imap_actions import mark_read
            mark_read(msg_id, db_path)
            return False
        if action == "star":
            from core.imap_actions import toggle_starred
            from core.database import get_connection
            conn = get_connection(db_path)
            row = conn.execute("SELECT flags FROM messages WHERE id=?", (msg_id,)).fetchone()
            conn.close()
            if row and "\\Flagged" not in json.loads(row["flags"] or "[]"):
                toggle_starred(msg_id, db_path)
            return False
        if action == "move" and folder_id:
            from core.imap_actions import move_message
            move_message(msg_id, int(folder_id), db_path)
            return True
        if action == "trash":
            from core.imap_actions import trash_message
            trash_message(msg_id, db_path)
            return True
        if action == "spam":
            from core.imap_actions import mark_spam
            mark_spam(msg_id, db_path)
            return True
    except Exception as e:
        log.error("rule action=%s msg=%d: %s", action, msg_id, e)
    return action in ("move", "trash", "spam")
