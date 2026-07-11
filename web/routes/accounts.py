"""
Email account CRUD + IMAP connection testing.
"""
from flask import Blueprint, request
from web.shared import db, ok, err, dict_rows
from core.database import get_connection
from core.credentials import store_password, delete_password, delete_oauth_tokens
from core.imap_sync import test_connection, sync_folders, sync_all_folders_messages, start_sync

bp = Blueprint("accounts", __name__)


@bp.route("/api/accounts")
def api_accounts():
    conn = get_connection(db())
    rows = dict_rows(conn.execute(
        "SELECT id, name, email, provider, imap_host, imap_port, imap_ssl, "
        "smtp_host, smtp_port, smtp_ssl, username, auth_type, last_sync, active, needs_reauth "
        "FROM accounts ORDER BY id"
    ).fetchall())
    # Attach folder counts
    for row in rows:
        folder_row = conn.execute(
            "SELECT SUM(unread_count) as unread, SUM(message_count) as total "
            "FROM folders WHERE account_id=?",
            (row["id"],)
        ).fetchone()
        row["unread_count"] = folder_row["unread"] or 0
        row["message_count"] = folder_row["total"] or 0
    conn.close()
    return ok(rows)


@bp.route("/api/accounts", methods=["POST"])
def api_accounts_create():
    data = request.get_json() or {}
    password = data.pop("password", None)

    required = ["name", "email", "imap_host", "smtp_host", "username"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return err(f"Required: {', '.join(missing)}")

    conn = get_connection(db())
    try:
        # Test connection first if password supplied
        if password:
            ok_conn, msg = test_connection(data, password)
            if not ok_conn:
                conn.close()
                return err(f"IMAP connection failed: {msg}")

        cur = conn.execute("""
            INSERT INTO accounts (name, email, provider, imap_host, imap_port, imap_ssl,
                smtp_host, smtp_port, smtp_ssl, username, auth_type)
            VALUES (:name, :email, :provider, :imap_host, :imap_port, :imap_ssl,
                :smtp_host, :smtp_port, :smtp_ssl, :username, :auth_type)
        """, {
            "name": data["name"],
            "email": data["email"],
            "provider": data.get("provider", "imap"),
            "imap_host": data["imap_host"],
            "imap_port": int(data.get("imap_port", 993)),
            "imap_ssl": int(data.get("imap_ssl", 1)),
            "smtp_host": data["smtp_host"],
            "smtp_port": int(data.get("smtp_port", 587)),
            "smtp_ssl": int(data.get("smtp_ssl", 0)),
            "username": data["username"],
            "auth_type": data.get("auth_type", "password"),
        })
        account_id = cur.lastrowid
        conn.commit()

        if password:
            store_password(account_id, password)

        # Kick off initial sync (non-blocking)
        import threading
        threading.Thread(
            target=_initial_sync,
            args=(account_id, db()),
            daemon=True,
        ).start()

    except Exception as e:
        conn.close()
        return err(str(e))

    conn.close()
    return ok({"id": account_id})


def _initial_sync(account_id: int, db_path: str):
    sync_folders(account_id, db_path)
    sync_all_folders_messages(account_id, db_path)
    start_sync(account_id, db_path)


@bp.route("/api/sync", methods=["POST"])
def api_sync():
    """Trigger an immediate full sync of all folders for all accounts."""
    import threading
    data = request.get_json() or {}
    account_id = data.get("account_id")
    conn = get_connection(db())
    if account_id:
        rows = conn.execute("SELECT id FROM accounts WHERE id=? AND active=1", (account_id,)).fetchall()
    else:
        rows = conn.execute("SELECT id FROM accounts WHERE active=1").fetchall()
    conn.close()

    db_path = db()

    def _run():
        for row in rows:
            sync_all_folders_messages(row["id"], db_path)

    threading.Thread(target=_run, daemon=True).start()
    return ok({"syncing": len(rows)})


@bp.route("/api/settings/ai_key", methods=["GET"])
def api_ai_key_get():
    from core.credentials import get_api_key
    key = get_api_key()
    # Return masked key so UI can show whether one is set
    if key and len(key) > 8:
        masked = key[:4] + "•" * (len(key) - 8) + key[-4:]
    elif key:
        masked = "•" * len(key)
    else:
        masked = ""
    return ok({"set": bool(key), "masked": masked})


@bp.route("/api/settings/ai_key", methods=["POST"])
def api_ai_key_set():
    from core.credentials import store_api_key
    data = request.get_json() or {}
    key = (data.get("key") or "").strip()
    if not key:
        return err("key required")
    store_api_key(key)
    return ok()


@bp.route("/api/accounts/<int:aid>", methods=["PUT"])
def api_account_update(aid: int):
    data = request.get_json() or {}
    password = data.pop("password", None)
    conn = get_connection(db())
    row = conn.execute("SELECT id FROM accounts WHERE id=?", (aid,)).fetchone()
    if not row:
        conn.close()
        return err("Not found", 404)

    fields = ["name", "email", "provider", "imap_host", "imap_port", "imap_ssl",
              "smtp_host", "smtp_port", "smtp_ssl", "username"]
    updates = {k: data[k] for k in fields if k in data}
    if updates:
        set_clause = ", ".join(f"{k}=:{k}" for k in updates)
        updates["id"] = aid
        conn.execute(f"UPDATE accounts SET {set_clause} WHERE id=:id", updates)
        conn.commit()

    if password:
        store_password(aid, password)

    conn.close()
    return ok()


@bp.route("/api/accounts/<int:aid>", methods=["DELETE"])
def api_account_delete(aid: int):
    from core.imap_sync import stop_sync
    stop_sync(aid)
    conn = get_connection(db())
    delete_password(aid)
    delete_oauth_tokens(aid)
    conn.execute("DELETE FROM accounts WHERE id=?", (aid,))
    conn.commit()
    conn.close()
    return ok()


@bp.route("/api/settings/ms_client_id", methods=["GET"])
def api_ms_client_id_get():
    from core.credentials import get_ms_client_id
    cid = get_ms_client_id()
    masked = (cid[:8] + "…" + cid[-4:]) if cid and len(cid) > 12 else (cid or "")
    return ok({"set": bool(cid), "masked": masked})


@bp.route("/api/settings/ms_client_id", methods=["POST"])
def api_ms_client_id_set():
    from core.credentials import store_ms_client_id
    data = request.get_json() or {}
    cid = (data.get("client_id") or "").strip()
    if not cid:
        return err("client_id required")
    store_ms_client_id(cid)
    return ok()



@bp.route("/api/accounts/test", methods=["POST"])
def api_accounts_test():
    data = request.get_json() or {}
    password = data.get("password")
    if not password:
        return err("Password required")
    success, msg = test_connection(data, password)
    if success:
        return ok({"message": msg})
    return err(msg)
