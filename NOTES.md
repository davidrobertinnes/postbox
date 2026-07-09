# Dogbox Mailman — Session Notes

## Current state (2026-07-09)

App is running and functional. All features from prior sessions are working.

### OAuth2 — implemented and tested this session

**Gmail OAuth2** — working end-to-end (tested 2026-07-09):
- Bundled Desktop app credentials (`core/oauth_google.py`) — same pattern as Thunderbird
- Google Cloud project: Dogbox Mailman, project ID in credentials
- Consent screen: External / Testing mode — user must be listed as test user in Google Cloud Console → Audience → Test users
- Scope fix: `email` → `https://www.googleapis.com/auth/userinfo.email` (google-auth-oauthlib scope mismatch)
- IMAP XOAUTH2 via IMAPClient.oauth2_login(); SMTP XOAUTH2 via docmd AUTH
- Token refresh handled automatically in `get_valid_access_token`
- 7-day refresh token limit while in Testing mode — will need Google verification to remove

**Microsoft OAuth2** — implemented, not yet tested end-to-end:
- MSAL public client flow (no client secret needed)
- Requires user to register their own Azure app + enter client ID in MS Integration settings
- Redirect URI: `http://localhost:5200/oauth/callback/microsoft`

### Next items (priority order)

1. **Re-auth flow** — detect expired refresh token (especially the 7-day Gmail issue), prompt user to re-authenticate rather than silent sync failure
2. **Microsoft OAuth testing** — get Azure app registered and test end-to-end
3. **Google verification** — submit for production publishing to remove 7-day token limit and 100-user cap
4. **OAuth2 for Gmail** — consider whether to apply for Google's verification/CASA audit for unrestricted publishing

### Architecture

- Stack: Flask + vanilla JS + SQLite (`.pbox`)
- Port: 5200
- Auth types: `password`, `oauth_microsoft`, `oauth_google`
- OAuth tokens: keyring (`postbox_oauth` service, keyed by account_id)
- MS client ID: keyring (`postbox_ms` service)
- Google credentials: hardcoded in `core/oauth_google.py`
