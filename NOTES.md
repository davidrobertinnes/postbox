# Dogbox Mailman — Session Notes

## Current state (2026-07-11)

App is running and functional. All features from prior sessions are working.

### OAuth2 — implemented and tested

**Gmail OAuth2** — working end-to-end:
- Bundled Desktop app credentials (`core/oauth_google.py`) — same pattern as Thunderbird
- Google Cloud project: Dogbox Mailman, owned by dogboxsoftware@gmail.com (switched 2026-07-11)
- Consent screen: External / Testing mode — user must be listed as test user in Google Cloud Console → Audience → Test users
- Scope fix: `email` → `https://www.googleapis.com/auth/userinfo.email` (google-auth-oauthlib scope mismatch)
- IMAP XOAUTH2 via IMAPClient.oauth2_login(); SMTP XOAUTH2 via docmd AUTH
- Token refresh handled automatically in `get_valid_access_token`
- 7-day refresh token limit while in Testing mode — Google verification needed to remove

**Microsoft OAuth2** — implemented, not yet tested end-to-end:
- MSAL public client flow (no client secret needed)
- Requires user to register their own Azure app + enter client ID in MS Integration settings
- Redirect URI: `http://localhost:5200/oauth/callback/microsoft`

### Attachment download — implemented and working

- `GET /api/emails/<mid>/attachment/<att_id>` — re-fetches RFC822 from IMAP on demand, extracts attachment by index, streams as file download
- `core/imap_sync.py`: `fetch_raw()` — lightweight RFC822 fetch without storing anything
- `core/email_parser.py`: `extract_attachment_bytes(raw, index)` — extracts attachment bytes by zero-based index from MIME tree
- UI: attachment chips shown between meta strip and body in email detail view; click to download

### Re-auth flow — implemented

- `needs_reauth` column on accounts table; set when any auth/token error detected in sync loop, fetch_body, fetch_raw; cleared on successful IMAP connect or after OAuth re-auth
- Amber banner in main area shown when any account needs re-auth; checked on load + every 5 min
- Account edit panel shows warning + Re-authenticate button for affected accounts
- OAuth callback upserts tokens for existing account (same email+auth_type) rather than inserting duplicate; restarts sync thread

### Next items (priority order)

1. **Google verification** — submit for production publishing to remove 7-day token limit and 100-user cap; requires privacy policy page, CASA Tier 2 security assessment
2. **Microsoft OAuth testing** — get Azure app registered and test end-to-end (deferred — Azure requires credit card)

### Architecture

- Stack: Flask + vanilla JS + SQLite (`.pbox`)
- Port: 5200
- Auth types: `password`, `oauth_microsoft`, `oauth_google`
- OAuth tokens: keyring (`postbox_oauth` service, keyed by account_id)
- MS client ID: keyring (`postbox_ms` service)
- Google credentials: hardcoded in `core/oauth_google.py` — project owned by dogboxsoftware@gmail.com
