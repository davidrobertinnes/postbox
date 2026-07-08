# Changelog

## Unreleased

- web/templates/dashboard.html, web/static/js/emails.js: Renamed app to **Dogbox Mailman**; updated title, sidebar wordmark
- web_server.py: Changed DB file extension from `.db` to `.pbox`
- web_server.py, web/server.py: Updated all description strings to Dogbox Mailman
- web/templates/dashboard.html: Moved power/close button to top-right page header (matching dbox/investments); removed from sidebar footer
- web/static/postbox.css: Power button styled red (`.footer-icon-close`) with red hover, matching sibling apps
- web/templates/dashboard.html: Inbox subfolders now render as a collapsible tree directly under the Inbox nav item (toggle arrow) instead of a separate "Inbox Folders" section below
- web/templates/dashboard.html: Switched role-based sidebar items back to `navigate(role)` so active state highlights correctly; fixed `_refreshPage()` to handle folder-id keys (`f_X`) by calling `navigateFolder` instead of `navigate`
- web/static/postbox.css: Added `.nav-expand` style for subfolder toggle arrows
- core/imap_sync.py: Expanded `_FOLDER_ROLE_MAP` to cover provider variants — "Sent Items", "Deleted Items", "Sent Mail", "Bulk Mail", "Junk E-mail", etc.; fixes Internode and other non-standard IMAP servers
- core/imap_sync.py: Added `sync_all_folders_messages()` — single IMAP connection that syncs headers for every folder, not just INBOX; background loop now uses this instead of `sync_inbox`
- web/static/js/emails.js: Added `_emOffset` pagination state; reset on folder/search change; `_emLoad(append)` supports appending to existing list
- web/static/js/emails.js: Added "Load more" button (fetches next 200, appends) and "Load all" button (fetches all remaining in one request) shown when list is truncated
- web/routes/emails.py: Raised server-side message limit cap from 500 to 9999 to support Load All
- web/routes/accounts.py: Added `POST /api/sync` endpoint — triggers immediate `sync_all_folders_messages` for all active accounts in a background thread; fixed app-context bug (db() resolved on request thread, path passed to background thread)
- web/routes/accounts.py: `_initial_sync` now runs a full all-folder sync before starting the background loop, so new accounts populate all folders immediately
- web/templates/dashboard.html: Refresh button (↻) now calls `_syncAndRefresh()` — triggers `/api/sync`, reloads folder list, then refreshes current view; icon spins during sync
- web/static/postbox.css: Added `@keyframes spin` for refresh button animation
- core/imap_actions.py: New module — `mark_read`, `mark_unread`, `trash_message`, `move_message`; local DB updated first, IMAP write-back best-effort; `trash_message` uses MOVE with COPY+DELETE+expunge fallback; permanent expunge when already in trash
- web/routes/emails.py: Added `POST /api/emails/<id>/mark_read`, `mark_unread`, `trash`, `move`; removed duplicate `api_mark_read` stub that caused Flask registration error on startup
- web/static/js/emails.js: Auto-mark-read + row styling on email open; Mark Unread and Delete buttons in detail footer; `_emMarkUnread` and `_emTrash` functions; `data-msgid` attr on rows for DOM targeting
- web/static/postbox.css: Outline danger button variant (`.btn-outline.btn-danger`) for Delete button
- core/ai_client.py: Added `triage_messages()` — batch Claude Haiku call scoring messages with priority (1=urgent/2=normal/3=low) and category (invoice|support|personal|newsletter|etc); lazy `_client()` instantiation reads API key at call time, not import time
- core/credentials.py: Added `store_api_key` / `get_api_key` — keyring-backed Anthropic API key storage with env var fallback; service name `postbox_ai`
- web/routes/ai.py: Added `POST /api/ai/triage` — fetches unscored unread inbox messages, calls `triage_messages`, writes `ai_priority` + `ai_category` to DB, returns results for in-place UI update
- web/routes/emails.py: Added `priority=` filter param to `/api/emails` — server-side Urgent filter
- web/routes/accounts.py: Added `GET/POST /api/settings/ai_key` — masked key status + keyring storage
- web/static/js/emails.js: `_emPriorityFilter` state; All / ⚑ Urgent filter pills in inbox toolbar; `_emAutoTriage` fires after inbox load, updates messages in-place and re-renders; urgent rows get red left border + flag icon; category badge in subject cell
- web/static/js/accounts.js: AI Settings card at bottom of accounts page with API key input, save, and masked status display
- web/static/postbox.css: AI settings card, filter pill, priority indicator, and category badge styles
- web/static/js/emails.js: Move to… button in email detail footer; `_emMoveModal` fetches account folders, renders searchable list (search input + scrollable rows) excluding current folder and trash; `_emMoveToFolder` calls `POST /api/emails/<id>/move`, removes from list, toasts
- web/static/postbox.css: `.em-move-row` styles for folder picker modal
- core/imap_sync.py: Replaced 60s poll loop with IMAP IDLE; `_idle_watch()` enters IDLE, polls `idle_check(timeout=1)` so stop event interrupts within 1s, returns True on EXISTS/RECENT push; `_sync_loop_idle()` IDLEs on inbox for real-time new mail, reconnects every 29 min before server's 30-min timeout, full all-folder sync every 10 min; automatic 60s polling fallback for servers without IDLE capability; confirmed working against Internode (Dovecot)
- web/static/js/emails.js: HTML email iframe sandbox now includes `allow-popups` so links open in new tabs
- web/static/js/compose.js, emails.js: `composeNew()` accepts optional `accountId`; Compose button passes current account filter so new mail defaults to the active account when filtered to a single account
