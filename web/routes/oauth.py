"""
Microsoft OAuth2 routes — start flow and handle callback.
"""
import logging
import threading
from urllib.parse import quote

from flask import Blueprint, request, redirect

from web.shared import db, ok, err

bp = Blueprint("oauth", __name__)
log = logging.getLogger(__name__)


@bp.route("/api/oauth/microsoft/start", methods=["POST"])
def ms_oauth_start():
    """Initiate Microsoft OAuth2 flow. Returns {auth_url}."""
    from core.oauth_microsoft import start_flow
    data = request.get_json() or {}
    account_data = {
        "name": (data.get("name") or "Outlook").strip() or "Outlook",
    }
    try:
        auth_url = start_flow(account_data)
        return ok({"auth_url": auth_url})
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        log.error("OAuth start: %s", e)
        return err("Failed to start OAuth flow")


@bp.route("/oauth/callback/microsoft")
def ms_oauth_callback():
    """Receive Microsoft redirect, exchange code, create account."""
    error = request.args.get("error")
    if error:
        desc = request.args.get("error_description", error)
        return redirect(f"/?oauth_error={quote(desc)}")

    code  = request.args.get("code")
    state = request.args.get("state")
    if not code or not state:
        return redirect("/?oauth_error=Missing+code+or+state+from+Microsoft")

    try:
        from core.oauth_microsoft import complete_flow
        result = complete_flow(state, code)
        account_id = _create_oauth_account(result)
        email = result.get("email") or "account"
        return redirect(f"/?oauth_success={quote(f'Outlook account {email} connected')}")
    except Exception as e:
        log.error("OAuth callback: %s", e)
        return redirect(f"/?oauth_error={quote(str(e))}")


def _create_oauth_account(result: dict) -> int:
    from core.database import get_connection
    from core.credentials import store_oauth_tokens
    from core.imap_sync import sync_folders, sync_all_folders_messages, start_sync

    data  = result["account_data"]
    email = result.get("email") or data.get("email", "")
    name  = data.get("name") or "Outlook"

    conn = get_connection(db())
    cur = conn.execute("""
        INSERT INTO accounts
            (name, email, provider, imap_host, imap_port, imap_ssl,
             smtp_host, smtp_port, smtp_ssl, username, auth_type)
        VALUES (?, ?, 'outlook_oauth',
                'outlook.office365.com', 993, 1,
                'smtp.office365.com', 587, 0,
                ?, 'oauth_microsoft')
    """, (name, email, email))
    account_id = cur.lastrowid
    conn.commit()
    conn.close()

    store_oauth_tokens(account_id, {
        "access_token":  result["access_token"],
        "refresh_token": result["refresh_token"],
        "expires_at":    result["expires_at"],
    })

    db_path = db()
    threading.Thread(
        target=lambda: (
            sync_folders(account_id, db_path),
            sync_all_folders_messages(account_id, db_path),
            start_sync(account_id, db_path),
        ),
        daemon=True,
    ).start()

    return account_id
