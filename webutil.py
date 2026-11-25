"""Small, testable helpers for the web app (no web framework needed here)."""
import html
import re
import threading
import time
from collections import defaultdict, deque

SESSION_RE = re.compile(r"[A-Za-z0-9-]{8,64}")


def valid_session_id(value) -> bool:
    return bool(value) and bool(SESSION_RE.fullmatch(value))


class RateLimiter:
    """Allow at most `max_calls` per `window` seconds for each key (for example an IP)."""

    def __init__(self, max_calls, window, clock=time.time):
        self.max_calls, self.window, self.clock = max_calls, window, clock
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key) -> bool:
        now = self.clock()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max_calls:
                return False
            q.append(now)
            return True

    def blocked(self, key) -> bool:
        """True if this key has already used up its allowance (does not count a new hit)."""
        now = self.clock()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            return len(q) >= self.max_calls

    def cleanup(self):
        """Drop keys with no recent activity so memory does not grow forever."""
        now = self.clock()
        with self._lock:
            for k in [k for k, q in self._hits.items()
                      if not q or now - q[-1] > self.window]:
                del self._hits[k]


def _t(ts):
    return time.strftime("%d %b, %I:%M %p", time.localtime(ts))


def _e(value):
    return html.escape(str(value if value is not None else ""))


def render_admin_html(leads, handoffs, business_name) -> str:
    """Owner page. Everything customers typed is escaped, so nobody can inject
    code into the owner's browser through a name or a message."""
    lead_rows = "".join(
        f"<tr><td>{_t(r['created_at'])}</td><td>{_e(r['kind']).replace('_', ' ')}</td>"
        f"<td>{_e(r['name'])}</td><td>{_e(r['phone'])}</td><td>{_e(r['interest'])}</td>"
        f"<td>{_e(r['preferred_time'])}</td></tr>" for r in leads
    ) or '<tr><td colspan="6">No leads yet.</td></tr>'
    hand_rows = "".join(
        f"<tr><td>{_t(r['created_at'])}</td><td>{_e(r['reason'])}</td>"
        f"<td>{_e(r['last_message'])}</td></tr>" for r in handoffs
    ) or '<tr><td colspan="3">No hand-offs yet.</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Leads - {_e(business_name)}</title>
<style>
 :root {{ --bg:#f6f7f9; --card:#fff; --text:#1c2430; --muted:#667085; --line:#e4e7ec; --accent:#0f766e; }}
 @media (prefers-color-scheme: dark) {{
  :root {{ --bg:#10151c; --card:#18202a; --text:#e6e9ee; --muted:#9aa4b2; --line:#2a3442; --accent:#2dd4bf; }} }}
 body {{ margin:0; font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif; background:var(--bg); color:var(--text); padding:16px; }}
 h1 {{ font-size:20px; margin:0 0 4px; }} h2 {{ font-size:16px; margin:24px 0 8px; }}
 p {{ color:var(--muted); margin:0 0 12px; }} a {{ color:var(--accent); }}
 .wrap {{ max-width:960px; margin:0 auto; overflow-x:auto; }}
 table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:8px; }}
 th,td {{ text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; }}
 th {{ color:var(--muted); font-weight:600; font-size:13px; }}
</style></head><body><div class="wrap">
<h1>{_e(business_name)}: leads</h1>
<p>{len(leads)} leads, {len(handoffs)} hand-offs. This page refreshes every minute.
<a href="/admin/leads.csv">Download leads (CSV)</a></p>
<h2>Leads</h2>
<table><tr><th>When</th><th>Type</th><th>Name</th><th>Phone</th><th>Interested in</th><th>Preferred time</th></tr>{lead_rows}</table>
<h2>Needs a human</h2>
<table><tr><th>When</th><th>Reason</th><th>Customer said</th></tr>{hand_rows}</table>
</div></body></html>"""


# =====================================================================
# SaaS edition helpers
# =====================================================================
import hashlib
import hmac


def csrf_token(secret: str, scope: str) -> str:
    """A token only this server can create. Forms must send it back, so another
    website cannot make an owner's browser change data without their knowledge."""
    return hmac.new(secret.encode("utf-8"), f"csrf:{scope}".encode("utf-8"),
                    hashlib.sha256).hexdigest()


def csrf_ok(secret: str, scope: str, token) -> bool:
    return hmac.compare_digest(csrf_token(secret, scope), str(token or ""))


_CSS = """
 :root { --bg:#f6f7f9; --card:#fff; --text:#1c2430; --muted:#667085; --line:#e4e7ec; --accent:#0f766e; --accent-text:#fff; --danger:#b42318; }
 @media (prefers-color-scheme: dark) {
  :root { --bg:#10151c; --card:#18202a; --text:#e6e9ee; --muted:#9aa4b2; --line:#2a3442; --accent:#2dd4bf; --accent-text:#06231f; --danger:#f97066; } }
 * { box-sizing: border-box; }
 body { margin:0; font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif; background:var(--bg); color:var(--text); padding:16px; }
 h1 { font-size:20px; margin:0 0 4px; } h2 { font-size:16px; margin:28px 0 8px; }
 p { color:var(--muted); margin:0 0 12px; } a { color:var(--accent); }
 .wrap { max-width:980px; margin:0 auto; }
 .scroll { overflow-x:auto; }
 table { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); }
 th,td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
 th { color:var(--muted); font-weight:600; font-size:13px; }
 form { margin:0; }
 .card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:14px; }
 label { display:block; font-size:13px; color:var(--muted); margin:10px 0 4px; }
 input[type=text], input[type=password], input[type=number], textarea { width:100%; font:inherit; padding:8px 10px; border:1px solid var(--line); border-radius:6px; background:var(--bg); color:var(--text); }
 textarea { font-family:ui-monospace,Consolas,monospace; font-size:14px; }
 button { font:inherit; font-weight:600; border:0; border-radius:6px; padding:7px 14px; background:var(--accent); color:var(--accent-text); cursor:pointer; }
 button.danger { background:transparent; color:var(--danger); border:1px solid var(--danger); }
 .notice { background:var(--card); border:1px solid var(--accent); border-radius:8px; padding:10px 14px; margin:12px 0; }
 .row { display:flex; gap:8px; flex-wrap:wrap; align-items:center; }
 .muted { color:var(--muted); }
"""


def _page(title, body):
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{_e(title)}</title><style>{_CSS}</style></head>"
            f'<body><div class="wrap">{body}</div></body></html>')


def _post_form(action, fields, button, confirm=None, danger=False):
    hidden = "".join(f'<input type="hidden" name="{_e(k)}" value="{_e(v)}">'
                     for k, v in fields.items())
    on = f' onsubmit="return confirm(\'{confirm}\')"' if confirm else ""
    cls = ' class="danger"' if danger else ""
    return (f'<form method="post" action="{_e(action)}"{on}>{hidden}'
            f'<button type="submit"{cls}>{_e(button)}</button></form>')


def _notice(text):
    return f'<div class="notice">{_e(text)}</div>' if text else ""


def render_landing_html(site_name, contact_email="") -> str:
    contact = (f'<p>Interested? Email <a href="mailto:{_e(contact_email)}">{_e(contact_email)}</a></p>'
               if contact_email else "")
    body = (f"<h1>{_e(site_name)}</h1>"
            "<p>An AI assistant that answers customer questions, collects leads and hands "
            "difficult chats to your team, for gyms, salons and local businesses.</p>" + contact)
    return _page(site_name, body)


def render_owner_html(tenant, leads, handoffs, used, csrf, chat_url, notice="") -> str:
    slug = tenant["slug"]
    base = f"/c/{slug}/admin"

    lead_rows = "".join(
        f"<tr><td>{_t(r['created_at'])}</td><td>{_e(r['kind']).replace('_', ' ')}</td>"
        f"<td>{_e(r['name'])}</td><td>{_e(r['phone'])}</td><td>{_e(r['interest'])}</td>"
        f"<td>{_e(r['preferred_time'])}</td>"
        f"<td>{_post_form(base + '/delete-lead', {'csrf': csrf, 'id': r['id']}, 'Delete', 'Delete this lead permanently?', True)}</td></tr>"
        for r in leads) or '<tr><td colspan="7">No leads yet.</td></tr>'
    hand_rows = "".join(
        f"<tr><td>{_t(r['created_at'])}</td><td>{_e(r['reason'])}</td><td>{_e(r['last_message'])}</td></tr>"
        for r in handoffs) or '<tr><td colspan="3">No hand-offs yet.</td></tr>'

    body = f"""
<h1>{_e(tenant['name'])}</h1>
<p>Customer chat link: <a href="{_e(chat_url)}">{_e(chat_url)}</a><br>
This month: {used} of {tenant['monthly_limit']} customer messages used.</p>
{_notice(notice)}
<h2>Leads ({len(leads)})</h2>
<p><a href="{base}/leads.csv">Download leads (CSV)</a></p>
<div class="scroll"><table><tr><th>When</th><th>Type</th><th>Name</th><th>Phone</th><th>Interested in</th><th>Preferred time</th><th></th></tr>{lead_rows}</table></div>
<h2>Needs a human ({len(handoffs)})</h2>
<div class="scroll"><table><tr><th>When</th><th>Reason</th><th>Customer said</th></tr>{hand_rows}</table></div>
<h2>What the assistant knows about your business</h2>
<p>Edit prices, timings and FAQs here. New chats use the changes straight away.
Only include information you are happy for customers to see.</p>
<form method="post" action="{base}/info" class="card">
 <input type="hidden" name="csrf" value="{_e(csrf)}">
 <textarea name="info" rows="18">{_e(tenant['info'])}</textarea>
 <div class="row" style="margin-top:10px"><button type="submit">Save information</button></div>
</form>
<h2>Change your password</h2>
<form method="post" action="{base}/password" class="card">
 <input type="hidden" name="csrf" value="{_e(csrf)}">
 <label for="np">New password (at least 8 characters)</label>
 <input id="np" type="password" name="password" autocomplete="new-password">
 <div class="row" style="margin-top:10px"><button type="submit">Change password</button></div>
</form>"""
    return _page(f"{tenant['name']}: dashboard", body)


def render_super_html(tenants, csrf, base_url, notice="") -> str:
    rows = ""
    for t in tenants:
        slug = t["slug"]
        status = "Active" if t["active"] else "Switched off"
        toggle = _post_form("/super/toggle", {"csrf": csrf, "slug": slug},
                            "Switch off" if t["active"] else "Switch on")
        limit = (f'<form method="post" action="/super/limit" class="row">'
                 f'<input type="hidden" name="csrf" value="{_e(csrf)}">'
                 f'<input type="hidden" name="slug" value="{_e(slug)}">'
                 f'<input type="number" name="limit" value="{t["monthly_limit"]}" min="1" style="width:90px">'
                 f'<button type="submit">Set</button></form>')
        delete = (f'<form method="post" action="/super/delete" class="row" '
                  f'onsubmit="return confirm(\'Permanently delete this business and ALL its data?\')">'
                  f'<input type="hidden" name="csrf" value="{_e(csrf)}">'
                  f'<input type="hidden" name="slug" value="{_e(slug)}">'
                  f'<input type="text" name="confirm" placeholder="type {_e(slug)}" style="width:130px">'
                  f'<button type="submit" class="danger">Delete</button></form>')
        rows += (f"<tr><td><a href=\"/c/{_e(slug)}\">{_e(slug)}</a><br>"
                 f"<a href=\"/c/{_e(slug)}/admin\" class=\"muted\">owner page</a></td>"
                 f"<td>{_e(t['name'])}</td><td>{status}</td><td>{t['used']}</td>"
                 f"<td>{limit}</td><td>{toggle}</td><td>{delete}</td></tr>")
    rows = rows or '<tr><td colspan="7">No businesses yet. Add the first one below.</td></tr>'

    body = f"""
<h1>Clients</h1>
<p>{len(tenants)} businesses. Customer links look like {_e(base_url)}/c/<i>web-address</i></p>
{_notice(notice)}
<div class="scroll"><table><tr><th>Web address</th><th>Name</th><th>Status</th><th>Messages this month</th><th>Monthly limit</th><th></th><th>Remove</th></tr>{rows}</table></div>
<h2>Add a business</h2>
<form method="post" action="/super/create" class="card">
 <input type="hidden" name="csrf" value="{_e(csrf)}">
 <label for="s">Web address (letters, numbers, dashes)</label>
 <input id="s" type="text" name="slug" placeholder="fitzone-patna">
 <label for="n">Business name</label>
 <input id="n" type="text" name="name" placeholder="FitZone Patna">
 <label for="p">Owner password (at least 8 characters, share it privately)</label>
 <input id="p" type="text" name="password" autocomplete="off">
 <label for="l">Monthly message limit</label>
 <input id="l" type="number" name="limit" value="1000" min="1">
 <div class="row" style="margin-top:10px"><button type="submit">Create business</button></div>
</form>"""
    return _page("Clients", body)