"""
OAuth2 routes — Microsoft and Google sign-in flows.
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
        account_id = _create_ms_oauth_account(result)
        email = result.get("email") or "account"
        return redirect(f"/?oauth_success={quote(f'Outlook account {email} connected')}")
    except Exception as e:
        log.error("OAuth callback: %s", e)
        return redirect(f"/?oauth_error={quote(str(e))}")


@bp.route("/api/oauth/google/start", methods=["POST"])
def google_oauth_start():
    """Initiate Google OAuth2 flow. Returns {auth_url}."""
    from core.oauth_google import start_flow
    data = request.get_json() or {}
    account_data = {
        "name": (data.get("name") or "Gmail").strip() or "Gmail",
    }
    try:
        auth_url = start_flow(account_data)
        return ok({"auth_url": auth_url})
    except ValueError as e:
        return err(str(e))
    except Exception as e:
        log.error("Google OAuth start: %s", e)
        return err("Failed to start Google sign-in")


@bp.route("/oauth/callback/google")
def google_oauth_callback():
    """Receive Google redirect, exchange code, create account."""
    error = request.args.get("error")
    if error:
        return redirect(f"/?oauth_error={quote(error)}")

    state = request.args.get("state")
    if not state:
        return redirect("/?oauth_error=Missing+state+from+Google")

    try:
        from core.oauth_google import complete_flow
        result = complete_flow(state, request.url)
        account_id = _create_google_account(result)
        email = result.get("email") or "account"
        return redirect(f"/?oauth_success={quote(f'Gmail account {email} connected')}")
    except Exception as e:
        log.error("Google OAuth callback: %s", e)
        return redirect(f"/?oauth_error={quote(str(e))}")


def _create_ms_oauth_account(result: dict) -> int:
    return _create_oauth_account(
        result,
        provider="outlook_oauth",
        auth_type="oauth_microsoft",
        imap_host="outlook.office365.com", imap_port=993, imap_ssl=1,
        smtp_host="smtp.office365.com",    smtp_port=587, smtp_ssl=0,
        default_name="Outlook",
    )


def _create_google_account(result: dict) -> int:
    return _create_oauth_account(
        result,
        provider="gmail_oauth",
        auth_type="oauth_google",
        imap_host="imap.gmail.com", imap_port=993, imap_ssl=1,
        smtp_host="smtp.gmail.com", smtp_port=587, smtp_ssl=0,
        default_name="Gmail",
    )


def _create_oauth_account(
    result: dict, provider: str, auth_type: str,
    imap_host: str, imap_port: int, imap_ssl: int,
    smtp_host: str, smtp_port: int, smtp_ssl: int,
    default_name: str,
) -> int:
    import time as _time
    from core.database import get_connection
    from core.credentials import store_oauth_tokens
    from core.imap_sync import sync_folders, sync_all_folders_messages, start_sync, stop_sync

    data  = result["account_data"]
    email = result.get("email") or data.get("email", "")
    name  = data.get("name") or default_name

    conn = get_connection(db())
    existing = conn.execute(
        "SELECT id FROM accounts WHERE LOWER(email)=LOWER(?) AND auth_type=?",
        (email, auth_type)
    ).fetchone()

    if existing:
        account_id = existing["id"]
        conn.execute(
            "UPDATE accounts SET name=?, needs_reauth=0, active=1 WHERE id=?",
            (name, account_id)
        )
        is_reauth = True
    else:
        cur = conn.execute("""
            INSERT INTO accounts
                (name, email, provider, imap_host, imap_port, imap_ssl,
                 smtp_host, smtp_port, smtp_ssl, username, auth_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, email, provider, imap_host, imap_port, imap_ssl,
              smtp_host, smtp_port, smtp_ssl, email, auth_type))
        account_id = cur.lastrowid
        is_reauth = False

    conn.commit()
    conn.close()

    store_oauth_tokens(account_id, {
        "access_token":  result["access_token"],
        "refresh_token": result["refresh_token"],
        "expires_at":    result["expires_at"],
    })

    db_path = db()

    def _bg():
        if is_reauth:
            stop_sync(account_id)
            _time.sleep(1)
        sync_folders(account_id, db_path)
        sync_all_folders_messages(account_id, db_path)
        start_sync(account_id, db_path)

    threading.Thread(target=_bg, daemon=True).start()
    return account_id
