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
