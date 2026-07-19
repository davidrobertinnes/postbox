import sqlite3
import os


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        pass
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.row_factory = sqlite3.Row
    return conn


def initialise_database(db_path: str) -> None:
    conn = get_connection(db_path)
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT NOT NULL,
        provider TEXT DEFAULT 'imap',
        imap_host TEXT,
        imap_port INTEGER DEFAULT 993,
        imap_ssl INTEGER DEFAULT 1,
        smtp_host TEXT,
        smtp_port INTEGER DEFAULT 587,
        smtp_ssl INTEGER DEFAULT 0,
        username TEXT,
        auth_type TEXT DEFAULT 'password',
        oauth_token TEXT,
        last_sync TEXT,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS folders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        display_name TEXT,
        role TEXT,
        uid_validity INTEGER,
        uid_next INTEGER DEFAULT 1,
        message_count INTEGER DEFAULT 0,
        unread_count INTEGER DEFAULT 0,
        UNIQUE(account_id, name)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        folder_id INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
        uid INTEGER NOT NULL,
        message_id TEXT,
        thread_id TEXT,
        from_addr TEXT,
        from_name TEXT,
        to_addrs TEXT,
        cc_addrs TEXT,
        subject TEXT,
        date TEXT,
        snippet TEXT,
        flags TEXT DEFAULT '[]',
        has_attachments INTEGER DEFAULT 0,
        body_fetched INTEGER DEFAULT 0,
        ai_priority INTEGER,
        ai_category TEXT,
        UNIQUE(account_id, folder_id, uid)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS message_bodies (
        message_id INTEGER PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
        body_text TEXT,
        body_html TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS attachments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
        filename TEXT,
        content_type TEXT,
        size INTEGER,
        part_id TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS ai_cache (
        thread_id TEXT PRIMARY KEY,
        summary TEXT,
        actions TEXT,
        cached_at TEXT
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS contacts (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        name            TEXT NOT NULL,
        email           TEXT NOT NULL,
        email_alt       TEXT,
        phone           TEXT,
        company         TEXT,
        dbox_contact_id INTEGER,
        source          TEXT DEFAULT 'manual',
        last_emailed    TEXT,
        notes           TEXT,
        created_at      TEXT DEFAULT (datetime('now')),
        UNIQUE(email)
    )""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email)")

    c.execute("""CREATE TABLE IF NOT EXISTS rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        condition_field TEXT NOT NULL,
        condition_op TEXT NOT NULL,
        condition_value TEXT NOT NULL,
        action TEXT NOT NULL,
        action_folder_id INTEGER,
        active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS sender_lists (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
        email TEXT NOT NULL,
        list_type TEXT NOT NULL,
        UNIQUE(account_id, email, list_type)
    )""")

    # Indices
    c.execute("CREATE INDEX IF NOT EXISTS idx_msg_account_folder ON messages(account_id, folder_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_msg_date ON messages(date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_msg_thread ON messages(thread_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_folders_role ON folders(role)")

    # Migrations — add columns to existing tables if not present
    try:
        c.execute("ALTER TABLE accounts ADD COLUMN needs_reauth INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE accounts ADD COLUMN signature TEXT")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE messages ADD COLUMN receipt_to TEXT")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE messages ADD COLUMN receipt_sent INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE messages ADD COLUMN draft_meta TEXT")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE messages ADD COLUMN trashed_at TEXT")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE rules ADD COLUMN priority INTEGER DEFAULT 0")
    except Exception:
        pass

    conn.commit()
    conn.close()
