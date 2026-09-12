"""
Outbox — view and manage queued/failed messages.
"""
from flask import Blueprint, request
from web.shared import db, ok, err
from core.database import get_connection

bp = Blueprint("outbox", __name__)


@bp.route("/api/outbox")
def api_outbox_list():
    from core.outbox import get_outbox_items
    return ok(get_outbox_items(db()))


@bp.route("/api/outbox/count")
def api_outbox_count():
    conn = get_connection(db())
    n = conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
    conn.close()
    return ok({"count": n})


@bp.route("/api/outbox/<int:oid>/retry", methods=["POST"])
def api_outbox_retry(oid: int):
    conn = get_connection(db())
    row = conn.execute("SELECT id FROM outbox WHERE id=?", (oid,)).fetchone()
    conn.close()
    if not row:
        return err("Not found", 404)

    conn = get_connection(db())
    conn.execute("UPDATE outbox SET status='pending', error=NULL, attempts=0 WHERE id=?", (oid,))
    conn.commit()
    conn.close()

    from core.outbox import retry_outbox
    retry_outbox(db())

    conn   = get_connection(db())
    still  = conn.execute("SELECT status, error FROM outbox WHERE id=?", (oid,)).fetchone()
    conn.close()

    if not still:
        return ok({"sent": True})
    return ok({"sent": False, "status": still["status"], "error": still["error"]})


@bp.route("/api/outbox/<int:oid>", methods=["DELETE"])
def api_outbox_delete(oid: int):
    conn = get_connection(db())
    conn.execute("DELETE FROM outbox WHERE id=?", (oid,))
    conn.commit()
    conn.close()
    return ok()
