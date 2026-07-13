"""
Filter rules and sender list (whitelist/blacklist) endpoints.
"""
from flask import Blueprint, request
from web.shared import db, ok, err, dict_rows
from core.database import get_connection

bp = Blueprint("rules", __name__)


# ── Rules ──────────────────────────────────────────────────────────────────────

@bp.route("/api/rules")
def api_rules_list():
    account_id = request.args.get("account", type=int)
    conn = get_connection(db())
    params = []
    where  = ""
    if account_id:
        where = "WHERE r.account_id=?"
        params.append(account_id)
    rows = dict_rows(conn.execute(f"""
        SELECT r.*, a.name as account_name, a.email as account_email,
               f.name as action_folder_name
        FROM rules r
        JOIN accounts a ON a.id = r.account_id
        LEFT JOIN folders f ON f.id = r.action_folder_id
        {where}
        ORDER BY r.account_id, r.id
    """, params).fetchall())
    conn.close()
    return ok(rows)


@bp.route("/api/rules", methods=["POST"])
def api_rules_create():
    data = request.get_json() or {}
    required = ["account_id", "name", "condition_field", "condition_op",
                "condition_value", "action"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return err(f"Required: {', '.join(missing)}")
    conn = get_connection(db())
    cur = conn.execute("""
        INSERT INTO rules (account_id, name, condition_field, condition_op,
                           condition_value, action, action_folder_id, active)
        VALUES (:account_id, :name, :condition_field, :condition_op,
                :condition_value, :action, :action_folder_id, 1)
    """, {
        "account_id":       int(data["account_id"]),
        "name":             data["name"],
        "condition_field":  data["condition_field"],
        "condition_op":     data["condition_op"],
        "condition_value":  data["condition_value"],
        "action":           data["action"],
        "action_folder_id": data.get("action_folder_id") or None,
    })
    conn.commit()
    conn.close()
    return ok({"id": cur.lastrowid})


@bp.route("/api/rules/<int:rid>", methods=["PUT"])
def api_rules_update(rid: int):
    data = request.get_json() or {}
    conn = get_connection(db())
    fields = ["name", "condition_field", "condition_op", "condition_value",
              "action", "action_folder_id", "active"]
    updates = {k: data[k] for k in fields if k in data}
    if updates:
        set_clause = ", ".join(f"{k}=:{k}" for k in updates)
        updates["id"] = rid
        conn.execute(f"UPDATE rules SET {set_clause} WHERE id=:id", updates)
        conn.commit()
    conn.close()
    return ok()


@bp.route("/api/rules/<int:rid>", methods=["DELETE"])
def api_rules_delete(rid: int):
    conn = get_connection(db())
    conn.execute("DELETE FROM rules WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    return ok()


# ── Sender Lists ───────────────────────────────────────────────────────────────

@bp.route("/api/sender_lists")
def api_sender_lists():
    account_id = request.args.get("account", type=int)
    list_type  = request.args.get("type")
    conn = get_connection(db())
    params = []
    where  = []
    if account_id:
        where.append("account_id=?"); params.append(account_id)
    if list_type:
        where.append("list_type=?");  params.append(list_type)
    where_clause = ("WHERE " + " AND ".join(where)) if where else ""
    rows = dict_rows(conn.execute(
        f"SELECT * FROM sender_lists {where_clause} ORDER BY list_type, email",
        params
    ).fetchall())
    conn.close()
    return ok(rows)


@bp.route("/api/sender_lists", methods=["POST"])
def api_sender_lists_add():
    data = request.get_json() or {}
    account_id = data.get("account_id")
    email      = (data.get("email") or "").strip().lower()
    list_type  = data.get("list_type")
    if not account_id or not email or list_type not in ("whitelist", "blacklist"):
        return err("account_id, email, and list_type (whitelist|blacklist) required")
    conn = get_connection(db())
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO sender_lists (account_id, email, list_type) VALUES (?,?,?)",
            (int(account_id), email, list_type)
        )
        conn.commit()
    except Exception as e:
        conn.close()
        return err(str(e))
    conn.close()
    return ok({"inserted": cur.rowcount > 0})


@bp.route("/api/sender_lists/<int:sid>", methods=["DELETE"])
def api_sender_lists_delete(sid: int):
    conn = get_connection(db())
    conn.execute("DELETE FROM sender_lists WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    return ok()
