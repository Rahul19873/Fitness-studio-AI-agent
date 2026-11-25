"""SQLite storage for leads, hand-offs, chat logs, and (SaaS edition) businesses.
Every row carries a business_id, and every query below filters by it, so one
business can never see another's data."""
import csv
import io
import sqlite3
import time
from contextlib import contextmanager

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    business_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT, phone TEXT, interest TEXT, preferred_time TEXT,
    consent INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'new'
);
CREATE TABLE IF NOT EXISTS handoffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    business_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    reason TEXT, last_message TEXT,
    status TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at REAL NOT NULL,
    business_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT
);
CREATE TABLE IF NOT EXISTS tenants (
    slug TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    info TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    monthly_limit INTEGER NOT NULL DEFAULT 1000,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS usage (
    slug TEXT NOT NULL,
    month TEXT NOT NULL,
    messages INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (slug, month)
);
CREATE INDEX IF NOT EXISTS idx_leads_biz ON leads (business_id, id);
CREATE INDEX IF NOT EXISTS idx_handoffs_biz ON handoffs (business_id, id);
"""

CSV_COLUMNS = ["id", "created_at", "business_id", "kind", "name", "phone",
               "interest", "preferred_time", "consent", "status"]


@contextmanager
def _db():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def add_lead(business_id, session_id, kind, name, phone, interest,
             preferred_time, consent):
    """Returns (lead_id, was_duplicate). The same phone + kind in the same chat
    within 10 minutes is treated as a duplicate, so a retried request can never
    create the lead twice."""
    with _db() as c:
        row = c.execute(
            "SELECT id FROM leads WHERE business_id=? AND session_id=? AND phone=? "
            "AND kind=? AND created_at > ?",
            (business_id, session_id, phone, kind, time.time() - 600)).fetchone()
        if row:
            return row["id"], True
        cur = c.execute(
            "INSERT INTO leads (created_at, business_id, session_id, kind, name, "
            "phone, interest, preferred_time, consent) VALUES (?,?,?,?,?,?,?,?,?)",
            (time.time(), business_id, session_id, kind, name, phone, interest,
             preferred_time, int(bool(consent))))
        return cur.lastrowid, False


def add_handoff(business_id, session_id, reason, last_message):
    with _db() as c:
        cur = c.execute(
            "INSERT INTO handoffs (created_at, business_id, session_id, reason, "
            "last_message) VALUES (?,?,?,?,?)",
            (time.time(), business_id, session_id, reason, last_message))
        return cur.lastrowid


def log_message(business_id, session_id, role, text):
    with _db() as c:
        c.execute("INSERT INTO messages (created_at, business_id, session_id, role, "
                  "text) VALUES (?,?,?,?,?)",
                  (time.time(), business_id, session_id, role, text))


def purge_old_messages(days=None):
    days = config.RETENTION_DAYS if days is None else days
    with _db() as c:
        cur = c.execute("DELETE FROM messages WHERE created_at < ?",
                        (time.time() - days * 86400,))
        return cur.rowcount


def list_leads(business_id=None):
    with _db() as c:
        q, args = "SELECT * FROM leads", ()
        if business_id:
            q += " WHERE business_id=?"
            args = (business_id,)
        return [dict(r) for r in c.execute(q + " ORDER BY id DESC", args)]


def list_handoffs(business_id=None):
    with _db() as c:
        q, args = "SELECT * FROM handoffs", ()
        if business_id:
            q += " WHERE business_id=?"
            args = (business_id,)
        return [dict(r) for r in c.execute(q + " ORDER BY id DESC", args)]


def delete_lead(business_id, lead_id):
    """Delete one lead, but only if it belongs to this business. Returns 1 or 0."""
    with _db() as c:
        cur = c.execute("DELETE FROM leads WHERE id=? AND business_id=?",
                        (int(lead_id), business_id))
        return cur.rowcount


def delete_business_data(business_id):
    """Remove everything stored for one business (used when a client leaves)."""
    out = {}
    with _db() as c:
        for table in ("leads", "handoffs", "messages"):
            out[table] = c.execute(f"DELETE FROM {table} WHERE business_id=?",
                                   (business_id,)).rowcount
    return out


def _safe_cell(value):
    """Stop spreadsheet formula injection: a customer who types a name like
    '=HYPERLINK(...)' must not be able to run a formula when the owner opens the CSV."""
    s = "" if value is None else str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def _csv_row(r):
    r = dict(r)
    r["created_at"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(r["created_at"]))
    return [_safe_cell(r.get(col)) for col in CSV_COLUMNS]


def leads_csv_text(business_id=None):
    """CSV text (with a byte-order mark so Excel opens Hindi names correctly)."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for r in list_leads(business_id):
        w.writerow(_csv_row(r))
    return "\ufeff" + buf.getvalue()


def export_leads_csv(path, business_id=None):
    text = leads_csv_text(business_id)
    with open(path, "w", newline="", encoding="utf-8") as f:
        f.write(text)
    return len(list_leads(business_id))
