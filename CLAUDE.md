# Dogbox Mailman — Claude Code Context

> Read this before touching any file. It exists so conventions don't have to be
> re-explained each session.

---

## What This App Is

A local-only AI-powered email client. Users connect Gmail, Outlook, or any
IMAP account; all email is synced to a local SQLite file (`.pbox`). No cloud
backend, no subscription, no server. Target users: anyone who wants an AI
triage layer on their inbox without sending their email to a third-party SaaS.

**AI features are first-class.** Claude Haiku scores each message on arrival
(priority 1–3, category: invoice / support / personal / newsletter / etc.).
Claude Sonnet drafts replies, summarises threads, and extracts action items.
The AI key is user-supplied and stored in the OS keyring.

Users run `mail.py`, which opens the app in a Chromium app-mode window on
`localhost:5200`.

---

## Tech Stack

- **Web UI:** Flask + vanilla JS — no build step, no npm, no webpack.
  Launched via `mail.py`; opens in Chromium app-mode window.
- **Distribution:** folder pack — users run `mail.py` directly, no installer.
- **Database:** SQLite with WAL mode (`.pbox` file = entire mailbox).
- **Email sync:** IMAPClient with IDLE support; SMTP for send.
- **OAuth:** google-auth-oauthlib (Google), MSAL (Microsoft).
- **AI:** Anthropic SDK — Haiku for triage, Sonnet for drafts/summaries.
- **Credentials:** OS keyring (Windows Credential Manager) with JSON fallback.
- **Port:** 5200 (default, overridable via `--port`).

---

## Directory Layout

```
core/                   Business logic — pure Python, no web imports
  database.py           Schema init + migrations
  imap_sync.py          IDLE loop, folder/message sync, auth error detection
  imap_actions.py       mark_read, mark_unread, trash, move (DB first, IMAP write-back)
  smtp_send.py          SMTP send with XOAUTH2 support
  ai_client.py          Claude calls: triage_messages(), summarise_thread(), draft_reply()
  email_parser.py       MIME parsing, attachment extraction
  credentials.py        Keyring-backed storage (passwords, OAuth tokens, API keys)
  oauth_google.py       Google OAuth2 flow
  oauth_microsoft.py    Microsoft OAuth2 (MSAL public client)
web/
  server.py             Flask app init + blueprint registration
  shared.py             ok() / err() helpers, db() path resolver, dict_rows()
  routes/
    accounts.py         Account CRUD, sync trigger, AI key + MS client ID settings
    emails.py           List, fetch body, mark read/unread, trash, move, attachments
    compose.py          Send endpoint
    ai.py               Triage, summarise, extract actions, draft reply
    oauth.py            Google + Microsoft OAuth start/callback, account upsert
  static/
    postbox.css         Global stylesheet — all component styles
    js/
      emails.js         Email list + detail view (prefix: _em)
      accounts.js       Account CRUD wizard (prefix: _acct)
      compose.js        New/reply/forward compose (prefix: _cmp)
  templates/
    dashboard.html      SPA shell — navigation, sidebar, toast, shared JS helpers
mail.py                 Launcher only — do not edit for feature work
```

**The dependency arrow is one-way: `web/` imports from `core/`.
`core/` never imports from `web/`. No exceptions.**

---

## Before Making Any Change

1. **Read the relevant file sections first.** Never assume function signatures,
   field names, or DB schema. Check the actual file before writing code that calls them.
2. **Check `core/` before inventing a function.** If something already exists,
   find it — don't duplicate it.
3. **Credentials always go through `core/credentials.py`** — never read keyring
   or environment variables directly in routes or JS.

---

## Running and Testing

```bash
python mail.py          # launcher — opens on localhost:5200
# Routes and logic live in web/routes/*.py — those are the files to edit
```

**Never consider a change tested until the app has been run from the terminal
and the changed feature exercised.** Syntax errors and wrong function names only
appear at runtime.

---

## Web UI Conventions

### API calls
```js
// GET requests — always use apiFetch(), never raw fetch()
const msgs = await apiFetch('/api/emails?folder=inbox');
// apiFetch unwraps {ok:true, data:[...]} envelope, throws on error

// POST/PUT/DELETE — raw fetch() with a body is correct
const r = await fetch('/api/emails/123/trash', { method: 'POST' });
```

### Toast notifications
```js
// Success
toast('Email sent');
// Error — second argument is the string 'err', NOT a boolean
toast('IMAP connection failed', 'err');
```
**The function is `toast()` — never `showToast()`.**

### Modal pattern
```js
// Backdrop class is modal-bd — NOT modal-overlay (no CSS for that)
const bd = document.createElement('div');
bd.className = 'modal-bd';
bd.innerHTML = `<div class="modal-box">
  <div class="modal-hdr">…</div>
  <div class="modal-body">…</div>
  <div class="modal-foot">…</div>
</div>`;
document.body.appendChild(bd);
bd.addEventListener('click', e => { if (e.target === bd) bd.remove(); });
```

### Detail slide-over
Email detail opens in the right-side slide-over panel — **not** in a modal.
Use `detOpen(title)` / `detClose()`; CSS class `.open` triggers the animation.

### CSS rules
- All colours via CSS variables (`--accent`, `--border`, `--surface`, `--ink`,
  `--ink2`, `--ink3`, `--red`, `--green`, `--amber`, etc.) — **never hardcode colours**
- New component styles go at the end of `postbox.css` under a clearly named comment block
- Inline `style=` only for JS-driven dynamic values (toggles, computed widths)

### User content escaping
Always pass user-supplied strings through `esc()` before inserting into innerHTML:
```js
el.innerHTML = `<span>${esc(msg.from_name)}</span>`;
```
Never set innerHTML directly from API data without escaping.

### Server route shape
| Route type    | Response               |
|---------------|------------------------|
| GET list      | `ok([...])`            |
| GET single    | `ok({...})`            |
| POST/PUT      | `ok()` or `ok({id:n})` |
| Any error     | `err("message", code)` |

All routes live in `web/routes/` as Flask blueprints registered in `web/server.py`.

### JS module namespaces
Each module prefixes all globals to avoid collisions:

| Module          | Prefix  |
|-----------------|---------|
| `emails.js`     | `_em`   |
| `accounts.js`   | `_acct` |
| `compose.js`    | `_cmp`  |

Entry point function is always `page<ModuleName>()`.

---

## Hard Rules

1. **Never commit untested code.**
2. **Never import `web/` from `core/`.**
3. **Never hardcode colours** — use CSS variables.
4. **Never use `modal-overlay`** — use `modal-bd`.
5. **Never use raw `fetch().then(r=>r.json())` for GET requests** — use `apiFetch()`.
6. **Never use `showToast()`** — the function is `toast(msg)` / `toast(msg, 'err')`.
7. **Never guess function or field names** — read the file first.
8. **Never read credentials directly** — always go through `core/credentials.py`.
9. **Always run the session end protocol** (see below).

---

## Session End Protocol

At the end of every session, without being asked:

1. Update `NOTES.md` — tick off completed items, note any in-progress state or blockers.
2. Update `CHANGELOG.md` — append bullets under `## Unreleased` (create the block if absent) for every feature, fix, or change made this session. One bullet per logical change; include affected file(s). On release, `## Unreleased` is renamed to `## X.Y.Z — YYYY-MM-DD`.
3. Commit **everything** (all session work + NOTES.md + CHANGELOG.md) in a single commit.
4. Push to `origin master`.

Commit message format:
```
<type>: <short summary>

- file.py: what changed and why
- file.js: what changed and why

<side effects, decisions, or follow-up items if needed>
```

Types: `fix`, `feat`, `refactor`, `docs`, `chore`.

---

## Related Repos

| Repo | Path | Purpose |
|------|------|---------|
| `dbox` | `../dbox` | Dogbox Accounting — the main business management app. |
| `dbox-website` | `../dbox-website` | Static marketing site — dogboxsoftware.com.au. |
| `dbox-investments` | `../dbox-investments` | Dogbox Investments — CGT and portfolio tracking. |

Mailman is a standalone product. It does not share a database with the accounting app.

---

## Key Files

| File | Notes |
|------|-------|
| `NOTES.md` | Current session state and roadmap — always reflect changes here |
| `CHANGELOG.md` | Running session log + release notes — append under `## Unreleased` each session |
| `web/static/postbox.css` | Global stylesheet — append new classes at end under comment |
| `core/imap_sync.py` | IMAP sync engine — authoritative for how messages reach the DB |
| `core/ai_client.py` | All Claude calls — add new AI features here |
| `core/credentials.py` | All credential access — keyring + JSON fallback |
| `mail.py` | Launch script only — do not edit for feature work |
| `web/server.py` | Flask app init + blueprint registration |
| `web/templates/dashboard.html` | SPA shell — `apiFetch`, `toast`, `fmtDate`, `esc` defined here |
