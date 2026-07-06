"""
AI feature endpoints — summarise, draft reply, extract actions.
"""
import json
from flask import Blueprint, request
from web.shared import db, ok, err, dict_rows
from core.database import get_connection
from core.ai_client import summarise_thread, draft_reply, extract_actions

bp = Blueprint("ai_routes", __name__)


@bp.route("/api/ai/summarise", methods=["POST"])
def api_summarise():
    data = request.get_json() or {}
    thread_id = data.get("thread_id")
    if not thread_id:
        return err("thread_id required")

    conn = get_connection(db())

    # Check cache
    cached = conn.execute(
        "SELECT summary FROM ai_cache WHERE thread_id=?", (thread_id,)
    ).fetchone()
    if cached and cached["summary"]:
        conn.close()
        return ok({"summary": cached["summary"], "cached": True})

    # Fetch thread messages
    messages = dict_rows(conn.execute("""
        SELECT m.from_name, m.from_addr, m.subject, m.date,
               b.body_text
        FROM messages m
        LEFT JOIN message_bodies b ON b.message_id = m.id
        WHERE m.thread_id=?
        ORDER BY m.date ASC
    """, (thread_id,)).fetchall())
    conn.close()

    if not messages:
        return err("Thread not found", 404)

    summary = summarise_thread(messages)

    # Cache it
    conn = get_connection(db())
    conn.execute("""
        INSERT OR REPLACE INTO ai_cache (thread_id, summary, cached_at)
        VALUES (?, ?, datetime('now','localtime'))
    """, (thread_id, summary))
    conn.commit()
    conn.close()

    return ok({"summary": summary, "cached": False})


@bp.route("/api/ai/draft", methods=["POST"])
def api_draft():
    data = request.get_json() or {}
    thread_id = data.get("thread_id")
    intent = data.get("intent", "").strip()
    account_id = data.get("account_id")

    if not thread_id or not intent:
        return err("thread_id and intent required")

    conn = get_connection(db())
    messages = dict_rows(conn.execute("""
        SELECT m.from_name, m.from_addr, m.subject, m.date, b.body_text
        FROM messages m
        LEFT JOIN message_bodies b ON b.message_id = m.id
        WHERE m.thread_id=?
        ORDER BY m.date ASC
    """, (thread_id,)).fetchall())

    account_name = ""
    if account_id:
        row = conn.execute("SELECT name FROM accounts WHERE id=?", (account_id,)).fetchone()
        if row:
            account_name = row["name"]

    conn.close()

    if not messages:
        return err("Thread not found", 404)

    draft = draft_reply(messages, intent, account_name)
    return ok({"draft": draft})


@bp.route("/api/ai/actions", methods=["POST"])
def api_actions():
    data = request.get_json() or {}
    thread_id = data.get("thread_id")
    if not thread_id:
        return err("thread_id required")

    conn = get_connection(db())

    # Check cache
    cached = conn.execute(
        "SELECT actions FROM ai_cache WHERE thread_id=?", (thread_id,)
    ).fetchone()
    if cached and cached["actions"]:
        conn.close()
        try:
            return ok({"actions": json.loads(cached["actions"]), "cached": True})
        except Exception:
            pass

    messages = dict_rows(conn.execute("""
        SELECT b.body_text
        FROM messages m
        LEFT JOIN message_bodies b ON b.message_id = m.id
        WHERE m.thread_id=?
        ORDER BY m.date ASC
    """, (thread_id,)).fetchall())
    conn.close()

    if not messages:
        return err("Thread not found", 404)

    actions = extract_actions(messages)
    actions_json = json.dumps(actions)

    conn = get_connection(db())
    conn.execute("""
        INSERT INTO ai_cache (thread_id, actions, cached_at)
        VALUES (?, ?, datetime('now','localtime'))
        ON CONFLICT(thread_id) DO UPDATE SET actions=excluded.actions
    """, (thread_id, actions_json))
    conn.commit()
    conn.close()

    return ok({"actions": actions, "cached": False})
