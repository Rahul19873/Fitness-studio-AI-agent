"""Businesses (tenants) in the SaaS edition: accounts, passwords, limits."""
import hashlib
import hmac
import re
import secrets
import sqlite3
import time

import store

SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{1,38}[a-z0-9]")      # 3 to 40 characters
RESERVED = {"admin", "api", "super", "static", "health", "c", "www", "app", "login"}
MAX_INFO_CHARS = 20000
ROUNDS = 200_000

INFO_TEMPLATE = """## About
(Describe the business in one or two lines.)

## Location and contact
- Address:
- Phone for the team:

## Timings
- Monday to Saturday:
- Sunday:

## Plans and prices
- (Plan name): Rs ...

## Trial
- (Describe any free trial or demo.)

## Services or classes
- (List them.)

## FAQs
- (Question)? (Answer.)

## Things the assistant must not answer (send to the team)
- Diet plans, supplements, injuries or medical questions
- Discounts, refunds, or special offers not listed above
"""


def _month():
    return time.strftime("%Y-%m")


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ROUNDS)
    return f"pbkdf2${ROUNDS}${salt.hex()}${h.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, rounds, salt_hex, hash_hex = stored.split("$")
        h = hashlib.pbkdf2_hmac("sha256", (password or "").encode("utf-8"),
                                bytes.fromhex(salt_hex), int(rounds))
        return hmac.compare_digest(h.hex(), hash_hex)
    except Exception:                                    # noqa: BLE001
        return False


_DUMMY_HASH = hash_password("not-a-real-password")      # keeps timing the same for unknown slugs


def _check_new_password(password):
    if not password or len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    if len(password) > 200:
        raise ValueError("Password is too long.")


def _check_info(info):
    info = (info or "").strip()
    if len(info) < 10:
        raise ValueError("Please add some information about the business.")
    if len(info) > MAX_INFO_CHARS:
        raise ValueError(f"Information is too long (maximum {MAX_INFO_CHARS:,} characters).")
    return info


# ------------------------------------------------------------------ tenants
def _public(row):
    d = dict(row)
    d.pop("password_hash", None)
    d["active"] = bool(d["active"])
    return d


def create_tenant(slug, name, password, info=None, monthly_limit=1000):
    slug = (slug or "").strip().lower()
    if not SLUG_RE.fullmatch(slug):
        raise ValueError("Web address must be 3 to 40 characters: letters, numbers "
                         "and dashes only (for example: fitzone-patna).")
    if slug in RESERVED:
        raise ValueError("That web address is reserved. Please choose another.")
    name = (name or "").strip()
    if not 2 <= len(name) <= 80:
        raise ValueError("Business name must be 2 to 80 characters.")
    _check_new_password(password)
    info = _check_info(info if info is not None else INFO_TEMPLATE)
    limit = int(monthly_limit)
    if not 1 <= limit <= 1_000_000:
        raise ValueError("Monthly limit must be between 1 and 1,000,000.")
    try:
        with store._db() as c:
            c.execute("INSERT INTO tenants (slug, name, info, password_hash, active, "
                      "monthly_limit, created_at) VALUES (?,?,?,?,1,?,?)",
                      (slug, name, info, hash_password(password), limit, time.time()))
    except sqlite3.IntegrityError:
        raise ValueError("That web address is already taken.")
    return get_tenant(slug)


def get_tenant(slug):
    slug = (slug or "").strip().lower()
    if not SLUG_RE.fullmatch(slug):
        return None
    with store._db() as c:
        row = c.execute("SELECT * FROM tenants WHERE slug=?", (slug,)).fetchone()
    return _public(row) if row else None


def verify_tenant(slug, password):
    """Return the tenant if the password is right, otherwise None."""
    slug = (slug or "").strip().lower()
    with store._db() as c:
        row = c.execute("SELECT password_hash FROM tenants WHERE slug=?", (slug,)).fetchone()
    if not row:
        check_password(password, _DUMMY_HASH)           # same work either way
        return None
    return get_tenant(slug) if check_password(password, row["password_hash"]) else None


def update_info(slug, info):
    info = _check_info(info)
    with store._db() as c:
        c.execute("UPDATE tenants SET info=? WHERE slug=?", (info, slug))


def set_password(slug, password):
    _check_new_password(password)
    with store._db() as c:
        c.execute("UPDATE tenants SET password_hash=? WHERE slug=?",
                  (hash_password(password), slug))


def set_active(slug, active):
    with store._db() as c:
        c.execute("UPDATE tenants SET active=? WHERE slug=?", (int(bool(active)), slug))


def set_limit(slug, limit):
    limit = int(limit)
    if not 1 <= limit <= 1_000_000:
        raise ValueError("Monthly limit must be between 1 and 1,000,000.")
    with store._db() as c:
        c.execute("UPDATE tenants SET monthly_limit=? WHERE slug=?", (limit, slug))


def list_tenants():
    with store._db() as c:
        rows = c.execute(
            "SELECT t.slug, t.name, t.active, t.monthly_limit, t.created_at, "
            "COALESCE(u.messages, 0) AS used FROM tenants t "
            "LEFT JOIN usage u ON u.slug = t.slug AND u.month = ? "
            "ORDER BY t.created_at DESC", (_month(),)).fetchall()
    return [dict(r, active=bool(r["active"])) for r in rows]


def usage_this_month(slug):
    with store._db() as c:
        row = c.execute("SELECT messages FROM usage WHERE slug=? AND month=?",
                        (slug, _month())).fetchone()
    return row["messages"] if row else 0


def check_and_count(slug):
    """Count one customer message against this month's limit.
    Returns (allowed, used, limit). When the limit is reached nothing more is counted."""
    m = _month()
    with store._db() as c:
        row = c.execute("SELECT monthly_limit FROM tenants WHERE slug=?", (slug,)).fetchone()
        if not row:
            return False, 0, 0
        limit = row["monthly_limit"]
        c.execute("INSERT OR IGNORE INTO usage (slug, month, messages) VALUES (?,?,0)", (slug, m))
        cur = c.execute("UPDATE usage SET messages = messages + 1 "
                        "WHERE slug=? AND month=? AND messages < ?", (slug, m, limit))
        used = c.execute("SELECT messages FROM usage WHERE slug=? AND month=?",
                         (slug, m)).fetchone()["messages"]
        return cur.rowcount == 1, used, limit


def delete_tenant(slug):
    """Remove a business and ALL its data. Returns what was deleted."""
    counts = store.delete_business_data(slug)
    with store._db() as c:
        counts["tenant"] = c.execute("DELETE FROM tenants WHERE slug=?", (slug,)).rowcount
        c.execute("DELETE FROM usage WHERE slug=?", (slug,))
    return counts
