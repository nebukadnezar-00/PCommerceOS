import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS sites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    url         TEXT NOT NULL,
    domain      TEXT NOT NULL UNIQUE,
    search_url  TEXT,            -- template with {q}
    logo        TEXT,            -- file name in data/logos, NULL = none yet
    position    INTEGER,
    added_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS searches (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    query       TEXT NOT NULL,
    scope       TEXT NOT NULL,   -- mine | all
    kind        TEXT NOT NULL,   -- quick (Akakçe) | deep (Gemini)
    product     TEXT,            -- Akakçe product chosen inside a quick search ('' = best match)
    result      TEXT NOT NULL,   -- JSON
    tokens      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS searches_lookup ON searches(query, scope, kind, product, created_at);
-- kept apart from searches so clearing the history does not hide what was spent
CREATE TABLE IF NOT EXISTS token_usage (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_tokens  INTEGER NOT NULL,
    output_tokens  INTEGER NOT NULL,
    total_tokens   INTEGER NOT NULL,
    created_at     TEXT NOT NULL
);
-- price tracking (Akakçe products; checked on a schedule, no tokens)
CREATE TABLE IF NOT EXISTS tracked (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    path          TEXT NOT NULL,       -- Akakçe product path
    title         TEXT NOT NULL,
    image         TEXT,
    scope         TEXT NOT NULL DEFAULT 'all',   -- mine | all: which stores count
    target_price  REAL,                -- NULL = tell me about any drop
    last_price    REAL,
    last_store    TEXT,
    last_url      TEXT,
    first_price   REAL,
    low_price     REAL,
    checked_at    TEXT,
    last_error    TEXT,
    created_at    TEXT NOT NULL,
    UNIQUE(path, scope)
);
CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tracked_id  INTEGER NOT NULL REFERENCES tracked(id) ON DELETE CASCADE,
    price       REAL NOT NULL,
    store       TEXT,
    checked_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS price_history_item ON price_history(tracked_id, checked_at);
CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tracked_id  INTEGER REFERENCES tracked(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,         -- target | drop
    title       TEXT NOT NULL,
    old_price   REAL,
    new_price   REAL NOT NULL,
    store       TEXT,
    url         TEXT,
    seen        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
-- groups of the user's stores (Elektronik, Market, …); a store without one is in "Diğer"
CREATE TABLE IF NOT EXISTS site_groups (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL UNIQUE,
    position   INTEGER,
    collapsed  INTEGER NOT NULL DEFAULT 0
);
-- the shopping list: Akakçe products, compared as "buy each where it is cheapest"
CREATE TABLE IF NOT EXISTS cart_items (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    path      TEXT NOT NULL UNIQUE,
    title     TEXT NOT NULL,
    image     TEXT,
    qty       INTEGER NOT NULL DEFAULT 1,
    added_at  TEXT NOT NULL
);
-- orders read from the stores' emails (one row per store + order number)
CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    site_id       INTEGER REFERENCES sites(id) ON DELETE SET NULL,
    store         TEXT NOT NULL,
    order_no      TEXT NOT NULL,       -- 'mail:<hash>' when the email had no order number
    title         TEXT,
    total         REAL,
    status        TEXT NOT NULL,       -- alindi | hazirlaniyor | kargoda | teslim | iptal | iade
    carrier       TEXT,
    tracking_no   TEXT,
    tracking_url  TEXT,
    ordered_at    TEXT,
    updated_at    TEXT,                -- date of the newest email
    delivered_at  TEXT,
    manual        INTEGER NOT NULL DEFAULT 0,   -- the user marked it delivered: emails no longer change it
    hidden        INTEGER NOT NULL DEFAULT 0,
    title_rank    INTEGER NOT NULL DEFAULT 0,   -- 2 product name, 1 quoted in a subject, 0 the bare subject
    total_paid    INTEGER NOT NULL DEFAULT 0,   -- total is what was charged, not a listed price
    assumed       INTEGER NOT NULL DEFAULT 0,   -- closed by AUTO_CLOSE_DAYS, no delivery mail came
    UNIQUE(store, order_no)
);
-- every email already read (order_id NULL = not an order email), so a scan never fetches it twice
CREATE TABLE IF NOT EXISTS order_mails (
    message_id   TEXT PRIMARY KEY,
    order_id     INTEGER REFERENCES orders(id) ON DELETE CASCADE,
    subject      TEXT,
    status       TEXT,
    received_at  TEXT
);
-- what a store charges for shipping, entered by the user (the price sources only say "free" or not)
CREATE TABLE IF NOT EXISTS store_shipping (
    store      TEXT PRIMARY KEY,   -- the store's name as the cart shows it
    fee        REAL,               -- per order; NULL = not known
    free_over  REAL                -- free from this order total on; NULL = never
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")   # removing a tracked product removes its history and alerts
    return conn


_conn = None


@contextmanager
def tx():
    global _conn
    with _lock:
        if _conn is None:
            _conn = _connect()
        try:
            yield _conn
            _conn.commit()
        except Exception:
            _conn.rollback()
            raise


def close():
    """Close the shared connection (tests switch config.DB_PATH between temp databases)."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def init():
    with tx() as c:
        c.executescript(SCHEMA)
        if "group_id" not in {r[1] for r in c.execute("PRAGMA table_info(sites)")}:
            c.execute("ALTER TABLE sites ADD COLUMN group_id INTEGER REFERENCES site_groups(id) ON DELETE SET NULL")
        ocols = {r[1] for r in c.execute("PRAGMA table_info(orders)")}
        for col in ("title_rank INTEGER NOT NULL DEFAULT 0", "total_paid INTEGER NOT NULL DEFAULT 0",
                    "assumed INTEGER NOT NULL DEFAULT 0"):
            if col.split()[0] not in ocols:
                c.execute(f"ALTER TABLE orders ADD COLUMN {col}")
        # which provider/model answered, for which part, and whether it was the backup (usage and cost)
        ucols = {r[1] for r in c.execute("PRAGMA table_info(token_usage)")}
        for col in ("provider TEXT", "model TEXT", "section TEXT", "backup INTEGER NOT NULL DEFAULT 0"):
            if col.split()[0] not in ucols:
                c.execute(f"ALTER TABLE token_usage ADD COLUMN {col}")
        ccols = {r[1] for r in c.execute("PRAGMA table_info(cart_items)")}
        # each item's last-read offers; `product`: the Akakçe product a single store's offer belongs to
        for col in ("offers TEXT", "offers_at TEXT", "offers_error TEXT", "product TEXT"):
            if col.split()[0] not in ccols:
                c.execute(f"ALTER TABLE cart_items ADD COLUMN {col}")


def rows(sql, params=()):
    with tx() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def one(sql, params=()):
    with tx() as c:
        r = c.execute(sql, params).fetchone()
        return dict(r) if r else None


def execute(sql, params=()):
    with tx() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid


def get_meta(key):
    r = one("SELECT value FROM meta WHERE key=?", (key,))
    return r["value"] if r else None


def set_meta(key, value):
    execute("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)", (key, value))


def dumps(v):
    return json.dumps(v, ensure_ascii=False)


def loads(v, default=None):
    if not v:
        return default
    try:
        return json.loads(v)
    except ValueError:
        return default
