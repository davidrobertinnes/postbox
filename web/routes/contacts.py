"""
Contacts — address book CRUD, autocomplete, and dbox import.
"""
from flask import Blueprint, request
from web.shared import db, ok, err, dict_rows
from core.database import get_connection

bp = Blueprint("contacts", __name__)


@bp.route("/api/contacts")
def api_contacts():
    q = request.args.get("q", "").strip()
    conn = get_connection(db())
    if q:
        rows = dict_rows(conn.execute("""
            SELECT * FROM contacts
            WHERE name LIKE ? OR email LIKE ? OR company LIKE ?
            ORDER BY name COLLATE NOCASE
        """, (f"%{q}%",) * 3).fetchall())
    else:
        rows = dict_rows(conn.execute(
            "SELECT * FROM contacts ORDER BY name COLLATE NOCASE"
        ).fetchall())
    conn.close()
    return ok(rows)


@bp.route("/api/contacts/autocomplete")
def api_contacts_autocomplete():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return ok([])
    conn = get_connection(db())
    rows = dict_rows(conn.execute("""
        SELECT id, name, email, company FROM contacts
        WHERE name LIKE ? OR email LIKE ? OR company LIKE ?
        ORDER BY name COLLATE NOCASE
        LIMIT 10
    """, (f"%{q}%",) * 3).fetchall())
    conn.close()
    return ok(rows)


@bp.route("/api/contacts", methods=["POST"])
def api_contacts_create():
    data  = request.get_json() or {}
    name  = (data.get("name")  or "").strip()
    email = (data.get("email") or "").strip().lower()
    if not name:  return err("Name is required")
    if not email: return err("Email is required")
    conn = get_connection(db())
    try:
        cur = conn.execute("""
            INSERT INTO contacts (name, email, email_alt, phone, company, notes, source)
            VALUES (?, ?, ?, ?, ?, ?, 'manual')
        """, (
            name, email,
            (data.get("email_alt") or "").strip() or None,
            (data.get("phone")     or "").strip() or None,
            (data.get("company")   or "").strip() or None,
            (data.get("notes")     or "").strip() or None,
        ))
        conn.commit()
        cid = cur.lastrowid
    except Exception as e:
        conn.close()
        return err("A contact with that email already exists" if "UNIQUE" in str(e) else str(e))
    conn.close()
    return ok({"id": cid})


@bp.route("/api/contacts/<int:cid>", methods=["GET"])
def api_contact_get(cid: int):
    conn = get_connection(db())
    row  = conn.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    conn.close()
    if not row: return err("Not found", 404)
    return ok(dict(row))


@bp.route("/api/contacts/<int:cid>", methods=["PUT"])
def api_contact_update(cid: int):
    data  = request.get_json() or {}
    name  = (data.get("name")  or "").strip()
    email = (data.get("email") or "").strip().lower()
    if not name:  return err("Name is required")
    if not email: return err("Email is required")
    conn = get_connection(db())
    try:
        conn.execute("""
            UPDATE contacts
            SET name=?, email=?, email_alt=?, phone=?, company=?, notes=?
            WHERE id=?
        """, (
            name, email,
            (data.get("email_alt") or "").strip() or None,
            (data.get("phone")     or "").strip() or None,
            (data.get("company")   or "").strip() or None,
            (data.get("notes")     or "").strip() or None,
            cid,
        ))
        conn.commit()
    except Exception as e:
        conn.close()
        return err("A contact with that email already exists" if "UNIQUE" in str(e) else str(e))
    conn.close()
    return ok()


@bp.route("/api/contacts/<int:cid>", methods=["DELETE"])
def api_contact_delete(cid: int):
    conn = get_connection(db())
    conn.execute("DELETE FROM contacts WHERE id=?", (cid,))
    conn.commit()
    conn.close()
    return ok()


@bp.route("/api/contacts/import_dbox", methods=["POST"])
def api_contacts_import_dbox():
    """Pull contacts from a running dbox instance at localhost:5100."""
    import urllib.request, json as _json
    try:
        with urllib.request.urlopen(
            "http://localhost:5000/api/ext/contacts", timeout=3
        ) as resp:
            payload = _json.loads(resp.read())
    except Exception as e:
        return err(f"Could not reach Dogbox — make sure it is running at localhost:5000 ({e})")

    if not payload.get("ok"):
        return err("Dogbox returned an error")

    imported = skipped = 0
    conn = get_connection(db())
    for c in payload.get("data", []):
        email = (c.get("email") or "").strip().lower()
        if not email:
            skipped += 1
            continue
        # If contact_person is set, they are the individual; name is the company
        person  = (c.get("contact_person") or "").strip()
        biz     = (c.get("name") or "").strip()
        name    = person if person else biz
        company = biz    if person else None
        if not name:
            skipped += 1
            continue
        try:
            conn.execute("""
                INSERT INTO contacts (name, email, phone, company, dbox_contact_id, source)
                VALUES (?, ?, ?, ?, ?, 'import_dbox')
                ON CONFLICT(email) DO UPDATE SET
                    name            = excluded.name,
                    phone           = excluded.phone,
                    company         = excluded.company,
                    dbox_contact_id = excluded.dbox_contact_id,
                    source          = CASE WHEN source='manual' THEN 'manual' ELSE 'import_dbox' END
            """, (
                name, email,
                (c.get("phone") or "").strip() or None,
                company,
                c.get("id"),
            ))
            imported += 1
        except Exception:
            skipped += 1
    conn.commit()
    conn.close()
    return ok({"imported": imported, "skipped": skipped})
