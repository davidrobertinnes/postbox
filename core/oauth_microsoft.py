"""
Microsoft OAuth2 (MSAL) — IMAP/SMTP via XOAUTH2.

Flow:
  1. start_flow(account_data)  → auth_uri (redirect user here)
  2. complete_flow(state, code) → {account_data, access_token, refresh_token, expires_at, email}
  3. get_valid_access_token(account_id, email) → access_token (refreshes automatically)
"""
import base64
import logging
import time

log = logging.getLogger(__name__)

_SCOPES = [
    "https://outlook.office.com/IMAP.AccessAsUser.All",
    "https://outlook.office.com/SMTP.Send",
    "offline_access",
]
_REDIRECT_URI = "http://localhost:5200/oauth/callback/microsoft"
_AUTHORITY    = "https://login.microsoftonline.com/common"

# In-memory: state → {flow, account_data}  (process-scoped, cleared after use)
_pending: dict[str, dict] = {}


def _app():
    import msal
    from core.credentials import get_ms_client_id
    client_id = get_ms_client_id()
    if not client_id:
        raise ValueError("Microsoft client ID not configured — add it in Accounts → Microsoft Integration")
    return msal.PublicClientApplication(client_id, authority=_AUTHORITY)


def start_flow(account_data: dict) -> str:
    """Initiate auth code flow. Returns the authorization URL."""
    app = _app()
    flow = app.initiate_auth_code_flow(scopes=_SCOPES, redirect_uri=_REDIRECT_URI)
    _pending[flow["state"]] = {"flow": flow, "account_data": account_data}
    return flow["auth_uri"]


def complete_flow(state: str, code: str) -> dict:
    """Exchange auth code for tokens. Returns merged result dict."""
    pending = _pending.pop(state, None)
    if not pending:
        raise ValueError("Unknown or expired OAuth state — please start the sign-in again")

    app = _app()
    result = app.acquire_token_by_auth_code_flow(
        pending["flow"],
        {"code": code, "state": state},
    )
    if "error" in result:
        raise ValueError(f"{result['error']}: {result.get('error_description', '')}")

    claims = result.get("id_token_claims") or {}
    email = claims.get("preferred_username") or claims.get("email") or ""

    return {
        "account_data": pending["account_data"],
        "access_token":  result["access_token"],
        "refresh_token": result.get("refresh_token", ""),
        "expires_at":    time.time() + result.get("expires_in", 3600),
        "email":         email,
    }


def get_valid_access_token(account_id: int, email: str) -> str:
    """Return a valid access token, refreshing from keyring if near expiry."""
    from core.credentials import get_oauth_tokens, store_oauth_tokens
    tokens = get_oauth_tokens(account_id)
    if not tokens:
        raise ValueError(f"No OAuth tokens for account {account_id} — re-authenticate")

    if tokens.get("expires_at", 0) - time.time() < 300:
        log.info("Refreshing Microsoft OAuth token for account %d", account_id)
        app = _app()
        result = app.acquire_token_by_refresh_token(
            tokens["refresh_token"],
            scopes=_SCOPES,
        )
        if "error" in result:
            raise ValueError(f"Token refresh failed: {result.get('error_description', result.get('error', ''))}")
        tokens = {
            "access_token":  result["access_token"],
            "refresh_token": result.get("refresh_token") or tokens["refresh_token"],
            "expires_at":    time.time() + result.get("expires_in", 3600),
        }
        store_oauth_tokens(account_id, tokens)

    return tokens["access_token"]


def xoauth2_string(email: str, access_token: str) -> str:
    """Base64-encoded XOAUTH2 auth string for both IMAP and SMTP."""
    raw = f"user={email}\x01auth=Bearer {access_token}\x01\x01"
    return base64.b64encode(raw.encode()).decode()
