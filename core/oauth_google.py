"""
Google OAuth2 — Gmail IMAP/SMTP via XOAUTH2.

Requires BYOC (bring your own credentials): user registers a Google Cloud project,
enables Gmail API, creates Desktop app credentials, and enters client_id + client_secret
in the app's Google Integration settings.

Note: projects in "Testing" status have refresh tokens that expire after 7 days.
Workspace users can use "Internal" app type to avoid this.
"""
import logging
import os
import time

log = logging.getLogger(__name__)

_SCOPES       = ["https://mail.google.com/", "openid", "email"]
_REDIRECT_URI = "http://localhost:5200/oauth/callback/google"
_TOKEN_URI    = "https://oauth2.googleapis.com/token"

# Allow HTTP redirect URI for localhost (safe for local-only app)
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

# In-memory: state → {flow, account_data}
_pending: dict[str, dict] = {}


def _client_config() -> dict:
    from core.credentials import get_google_client_config
    cfg = get_google_client_config()
    if not cfg or not cfg.get("client_id") or not cfg.get("client_secret"):
        raise ValueError(
            "Google client ID and secret not configured — "
            "add them in Accounts → Google Integration"
        )
    return cfg


def start_flow(account_data: dict) -> str:
    """Initiate auth code flow. Returns the authorization URL."""
    from google_auth_oauthlib.flow import Flow
    cfg = _client_config()
    flow = Flow.from_client_config(
        {"installed": {
            "client_id":     cfg["client_id"],
            "client_secret": cfg["client_secret"],
            "redirect_uris": [_REDIRECT_URI],
            "auth_uri":      "https://accounts.google.com/o/oauth2/auth",
            "token_uri":     _TOKEN_URI,
        }},
        scopes=_SCOPES,
        redirect_uri=_REDIRECT_URI,
    )
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",   # always return refresh_token
    )
    _pending[state] = {"flow": flow, "account_data": account_data}
    return auth_url


def complete_flow(state: str, request_url: str) -> dict:
    """Exchange auth code (via full redirect URL) for tokens."""
    pending = _pending.pop(state, None)
    if not pending:
        raise ValueError("Unknown or expired OAuth state — please start the sign-in again")

    flow = pending["flow"]
    flow.fetch_token(authorization_response=request_url)
    credentials = flow.credentials

    # Resolve email via userinfo endpoint
    try:
        import requests as _req
        r = _req.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {credentials.token}"},
            timeout=10,
        )
        email = r.json().get("email", "") if r.ok else ""
    except Exception:
        email = ""

    return {
        "account_data":  pending["account_data"],
        "access_token":  credentials.token,
        "refresh_token": credentials.refresh_token or "",
        "expires_at":    credentials.expiry.timestamp() if credentials.expiry else time.time() + 3600,
        "email":         email,
    }


def get_valid_access_token(account_id: int, email: str) -> str:
    """Return a valid access token, refreshing if near expiry."""
    from core.credentials import get_oauth_tokens, store_oauth_tokens
    tokens = get_oauth_tokens(account_id)
    if not tokens:
        raise ValueError(f"No OAuth tokens for account {account_id} — re-authenticate")

    if tokens.get("expires_at", 0) - time.time() < 300:
        log.info("Refreshing Google OAuth token for account %d", account_id)
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        cfg = _client_config()
        creds = Credentials(
            token=tokens["access_token"],
            refresh_token=tokens["refresh_token"],
            token_uri=_TOKEN_URI,
            client_id=cfg["client_id"],
            client_secret=cfg["client_secret"],
            scopes=_SCOPES,
        )
        creds.refresh(Request())
        tokens = {
            "access_token":  creds.token,
            "refresh_token": creds.refresh_token or tokens["refresh_token"],
            "expires_at":    creds.expiry.timestamp() if creds.expiry else time.time() + 3600,
        }
        store_oauth_tokens(account_id, tokens)

    return tokens["access_token"]
