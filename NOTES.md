# Dogbox Mailman — Session Notes

## Current state (2026-07-14)

### Session 2026-07-14 (4) — signatures, star/flag, bulk mark-read, search operators, AI draft modal, auto-refresh

- **Signatures** — `signature TEXT` column added to accounts table (migration); edit form in accounts panel has a signature textarea; new messages auto-inject signature below a `-- ` separator; switching accounts in compose replaces the signature
- **Star/flag** — star column (☆/★) added to email list; click toggles `\\Flagged` IMAP flag without opening email; Star/Unstar button in detail footer; `is:starred` search operator supported
- **Bulk mark-read** — "✓ All read" button in toolbar (inbox and folder views); marks all visible messages read in DB and IMAP; `POST /api/emails/mark_all_read` route
- **Search operators** — `from:`, `subject:`, `has:attachment`, `is:unread`, `is:starred` now parsed server-side; freetext remainder used for full-text search as before
- **AI draft modal** — `window.prompt()` replaced with proper textarea modal; Ctrl+Enter submits; Cancel closes
- **Auto-refresh** — inbox now polls every 2 minutes for new mail and runs triage; timer cleared on folder navigation

### Next items (priority order)

1. **Google verification** — submit for production publishing to remove 7-day token limit and 100-user cap
2. **Microsoft OAuth testing** — get Azure app registered and test end-to-end (deferred — Azure requires credit card)

---

### Session 2026-07-14 (3) — compose: file attachments

- Attach button in compose footer opens file picker (multi-file supported)
- Selected files shown as removable chips above the footer
- FormData replaces JSON on send so binary data carries correctly
- Backend builds multipart/mixed with body as multipart/alternative sub-part
- Files cleared on modal open/close; backend accepts both form-data and JSON

### Session 2026-07-14 (2) — compose: CC, BCC, Reply All

- CC field added to compose modal (always visible)
- BCC field added (hidden behind "+ BCC" toggle in header)
- Reply All added — To=sender, CC=original To+CC minus own address, button in detail footer
- Modal title now reflects context: New Message / Reply / Reply All / Forward
- BCC wired through backend (smtp_send.py + compose.py); SMTP envelope only, not headers

### Session 2026-07-14 (1) — bug fixes across sync, preview panel, and flags

- DB lock contention fixed — sync functions now use three-phase pattern (read DB → IMAP → write DB); connection no longer held open during network I/O
- Junk folder was always empty — `navigate('junk')` passed `folder=junk` but DB role is `spam`; aliased in `pageEmails`
- Attachment badge false positives fixed — `_has_attachments` heuristic now skips `ALTERNATIVE` and `RELATED` subtypes; body fetch corrects `has_attachments` from actual parsed attachments
- Preview panel: AI summary/actions boxes hidden until content arrives (CSS `display:none` + JS show on load)
- Preview panel: date now shows full date+time; CC field added to meta strip; iframe height re-measured 800ms after load for images
- Thread ID chaining fixed for 3+ message chains — parent lookup resolves root thread_id
- Flags format fixed in `mark_read` (JSON parse, not substring) and `mark_unread` (dead entries removed)
- Unread row styling in JS now uses `JSON.parse(flags).includes('\\Seen')` not substring match
- DB indices added on `messages(account_id, folder_id)`, `messages(date)`, `messages(thread_id)`, `folders(role)`

### Next items (priority order)

1. **Google verification** — submit for production publishing to remove 7-day token limit and 100-user cap
2. **Microsoft OAuth testing** — get Azure app registered and test end-to-end (deferred — Azure requires credit card)

---

## Current state (2026-07-12)

### Session 2026-07-12 (2) — category filtering, bulk move, triage fallback, bug fixes

- Search focus loss fixed — focus and cursor restored after `_emRender`; 300ms debounce added
- Scroll preservation fixed — `scrollTop` now correctly restored in `_emRender(keepScroll)`
- Category filter pills in inbox toolbar — filter by invoice/support/personal/newsletter/etc
- Bulk move — "Move all N…" modal moves all messages in active category to chosen folder
- Rule-based triage fallback in `core/ai_client.py` — works without an API key
- Triage query now covers all untriaged messages, not just unread

### Session 2026-07-12 (1) — launcher rename + CLAUDE.md added

- Launcher renamed `web_server.py` → `mail.py`
- `CLAUDE.md` created — full context file covering app overview, tech stack, directory layout, web UI conventions, hard rules, and session end protocol

---

## State as of 2026-07-11

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
