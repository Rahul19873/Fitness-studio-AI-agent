"""SaaS edition: many businesses on one server.

Run:  uv run uvicorn saas:app --reload

  /                        simple landing page
  /c/<name>                a business's customer chat
  /c/<name>/admin          that business owner's dashboard (password = their own)
  /super                   YOUR page for adding and managing clients (password = SUPER_ADMIN_KEY)
"""
import secrets
import threading
import time
import traceback
from urllib.parse import parse_qs

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

import config
import store
import tenants
from agent import FrontDesk
from chatpage import CHAT_HTML
from webutil import (RateLimiter, csrf_ok, csrf_token, render_landing_html,
                     render_owner_html, render_super_html, valid_session_id)

MAX_CHARS = 600
MAX_SESSIONS = 500
SESSION_TTL = 2 * 3600
MAX_FORM_BYTES = 60_000

chat_limiter = RateLimiter(max_calls=30, window=600)     # messages per visitor
login_limiter = RateLimiter(max_calls=8, window=900)     # failed logins per visitor

SECRET = config.SECRET_KEY
if not SECRET:
    SECRET = secrets.token_hex(32)
    print("WARNING: SECRET_KEY is not set. A temporary one is used, so forms that were "
          "open before a restart will need a refresh. Set SECRET_KEY in .env.")

app = FastAPI(title=config.SITE_NAME, docs_url=None, redoc_url=None)
security = HTTPBasic()
store.purge_old_messages()


@app.middleware("http")
async def safe_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


# ------------------------------------------------------------------ helpers
def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def read_form(request: Request) -> dict:
    body = await request.body()
    if len(body) > MAX_FORM_BYTES:
        raise HTTPException(413, "That is too much text.")
    parsed = parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items()}


def check_csrf(data: dict, scope: str):
    if not csrf_ok(SECRET, scope, data.get("csrf")):
        raise HTTPException(403, "This form expired. Please go back, refresh the page and try again.")


def html(content: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(content, status_code=status, headers={"Cache-Control": "no-store"})


# ---------------------------------------------------------- chat sessions
class Session:
    def __init__(self, bot):
        self.bot, self.lock, self.last = bot, threading.Lock(), time.time()


SESSIONS: dict = {}
SESSIONS_LOCK = threading.Lock()


def get_session(tenant: dict, sid: str) -> Session:
    key = f"{tenant['slug']}:{sid}"
    with SESSIONS_LOCK:
        now = time.time()
        for k in [k for k, v in SESSIONS.items() if now - v.last > SESSION_TTL]:
            del SESSIONS[k]
        chat_limiter.cleanup()
        s = SESSIONS.get(key)
        if s is None:
            if len(SESSIONS) >= MAX_SESSIONS:
                raise HTTPException(503, "We're very busy right now. Please try again in a few minutes.")
            s = SESSIONS[key] = Session(FrontDesk(tenant=tenant, session_id=sid))
        s.last = now
        return s


def active_tenant(slug: str) -> dict:
    t = tenants.get_tenant(slug)
    if not t or not t["active"]:
        raise HTTPException(404, "This chat isn't available.")
    return t


# -------------------------------------------------------- public: chat
@app.get("/", response_class=HTMLResponse)
def landing():
    return render_landing_html(config.SITE_NAME, config.CONTACT_EMAIL)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/c/{slug}", response_class=HTMLResponse)
def chat_page(slug: str):
    return CHAT_HTML          # the page itself shows "not available" if the business is unknown


@app.get("/api/c/{slug}/info")
def info(slug: str):
    t = active_tenant(slug)
    return {"name": t["name"], "greeting": FrontDesk(tenant=t).greeting()}


class ChatIn(BaseModel):
    session_id: str
    message: str


@app.post("/api/c/{slug}/chat")
def chat(slug: str, body: ChatIn, request: Request):
    t = active_tenant(slug)
    if not valid_session_id(body.session_id):
        raise HTTPException(400, "Invalid session.")
    msg = body.message.strip()
    if not msg:
        raise HTTPException(400, "Please type a message.")
    if len(msg) > MAX_CHARS:
        raise HTTPException(400, f"Please keep your message under {MAX_CHARS} characters.")
    if not chat_limiter.allow(client_ip(request)):
        raise HTTPException(429, "You're sending messages very quickly. Please wait a few minutes.")

    allowed, _used, _limit = tenants.check_and_count(t["slug"])
    if not allowed:
        return {"reply": "Sorry, this assistant can't take more messages right now. "
                         "Please contact the business directly."}

    s = get_session(t, body.session_id)
    try:
        with s.lock:
            return {"reply": s.bot.reply(msg)}
    except Exception:                                    # noqa: BLE001
        traceback.print_exc()
        raise HTTPException(500, "Something went wrong. Please try again.")


# ------------------------------------------------------ owner dashboard
def owner_auth(slug: str, request: Request,
               creds: HTTPBasicCredentials = Depends(security)) -> dict:
    key = f"{client_ip(request)}:{slug}"
    if login_limiter.blocked(key):
        raise HTTPException(429, "Too many wrong passwords. Please try again in 15 minutes.")
    t = tenants.verify_tenant(slug, creds.password)       # the username is ignored
    if not t:
        login_limiter.allow(key)                          # records a failed attempt
        raise HTTPException(401, "Wrong password.",
                            headers={"WWW-Authenticate": 'Basic realm="Owner login"'})
    return t


def owner_page(request: Request, t: dict, notice: str = "") -> HTMLResponse:
    slug = t["slug"]
    return html(render_owner_html(
        t, store.list_leads(slug), store.list_handoffs(slug),
        tenants.usage_this_month(slug), csrf_token(SECRET, f"owner:{slug}"),
        str(request.base_url).rstrip("/") + f"/c/{slug}", notice))


@app.get("/c/{slug}/admin", response_class=HTMLResponse)
def owner_home(request: Request, t: dict = Depends(owner_auth)):
    return owner_page(request, t)


@app.get("/c/{slug}/admin/leads.csv")
def owner_csv(t: dict = Depends(owner_auth)):
    return Response(store.leads_csv_text(t["slug"]), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{t["slug"]}-leads.csv"',
                             "Cache-Control": "no-store"})


@app.post("/c/{slug}/admin/info", response_class=HTMLResponse)
async def owner_save_info(request: Request, t: dict = Depends(owner_auth)):
    data = await read_form(request)
    check_csrf(data, f"owner:{t['slug']}")
    try:
        tenants.update_info(t["slug"], data.get("info", ""))
        notice = "Saved. New chats use the updated information."
    except ValueError as e:
        notice = str(e)
    return owner_page(request, tenants.get_tenant(t["slug"]), notice)


@app.post("/c/{slug}/admin/password", response_class=HTMLResponse)
async def owner_change_password(request: Request, t: dict = Depends(owner_auth)):
    data = await read_form(request)
    check_csrf(data, f"owner:{t['slug']}")
    try:
        tenants.set_password(t["slug"], data.get("password", ""))
        notice = "Password changed. Your browser will ask you to log in again with the new one."
    except ValueError as e:
        notice = str(e)
    return owner_page(request, t, notice)


@app.post("/c/{slug}/admin/delete-lead", response_class=HTMLResponse)
async def owner_delete_lead(request: Request, t: dict = Depends(owner_auth)):
    data = await read_form(request)
    check_csrf(data, f"owner:{t['slug']}")
    try:
        n = store.delete_lead(t["slug"], data.get("id", ""))     # only this business's own leads
        notice = "Lead deleted." if n else "That lead was not found."
    except ValueError:
        notice = "That lead was not found."
    return owner_page(request, t, notice)


# --------------------------------------------------- your admin (/super)
def require_super(request: Request, creds: HTTPBasicCredentials = Depends(security)):
    if not config.SUPER_ADMIN_KEY:
        raise HTTPException(503, "Set SUPER_ADMIN_KEY in .env to turn on the /super page.")
    key = f"{client_ip(request)}:super"
    if login_limiter.blocked(key):
        raise HTTPException(429, "Too many wrong passwords. Please try again in 15 minutes.")
    ok = secrets.compare_digest(creds.password.encode("utf-8"),
                                config.SUPER_ADMIN_KEY.encode("utf-8"))
    if not ok:
        login_limiter.allow(key)
        raise HTTPException(401, "Wrong password.",
                            headers={"WWW-Authenticate": 'Basic realm="Admin"'})


def super_page(request: Request, notice: str = "") -> HTMLResponse:
    return html(render_super_html(tenants.list_tenants(), csrf_token(SECRET, "super"),
                                  str(request.base_url).rstrip("/"), notice))


@app.get("/super", response_class=HTMLResponse)
def super_home(request: Request, _: None = Depends(require_super)):
    return super_page(request)


@app.post("/super/create", response_class=HTMLResponse)
async def super_create(request: Request, _: None = Depends(require_super)):
    data = await read_form(request)
    check_csrf(data, "super")
    try:
        t = tenants.create_tenant(data.get("slug", ""), data.get("name", ""),
                                  data.get("password", ""),
                                  monthly_limit=data.get("limit") or 1000)
        notice = (f"Created. Customer chat: /c/{t['slug']}   Owner page: /c/{t['slug']}/admin   "
                  "Share the owner password privately.")
    except (ValueError, TypeError) as e:
        notice = str(e)
    return super_page(request, notice)


@app.post("/super/toggle", response_class=HTMLResponse)
async def super_toggle(request: Request, _: None = Depends(require_super)):
    data = await read_form(request)
    check_csrf(data, "super")
    t = tenants.get_tenant(data.get("slug", ""))
    if t:
        tenants.set_active(t["slug"], not t["active"])
    return super_page(request, "Updated." if t else "Business not found.")


@app.post("/super/limit", response_class=HTMLResponse)
async def super_limit(request: Request, _: None = Depends(require_super)):
    data = await read_form(request)
    check_csrf(data, "super")
    t = tenants.get_tenant(data.get("slug", ""))
    try:
        if not t:
            raise ValueError("Business not found.")
        tenants.set_limit(t["slug"], data.get("limit", ""))
        notice = "Limit updated."
    except ValueError as e:
        notice = str(e)
    return super_page(request, notice)


@app.post("/super/delete", response_class=HTMLResponse)
async def super_delete(request: Request, _: None = Depends(require_super)):
    data = await read_form(request)
    check_csrf(data, "super")
    t = tenants.get_tenant(data.get("slug", ""))
    if not t:
        notice = "Business not found."
    elif data.get("confirm", "").strip().lower() != t["slug"]:
        notice = f"Not deleted. Type the web address ({t['slug']}) in the box to confirm."
    else:
        c = tenants.delete_tenant(t["slug"])
        notice = (f"Deleted {t['slug']}: {c['leads']} leads, {c['handoffs']} hand-offs "
                  f"and {c['messages']} chat messages removed.")
    return super_page(request, notice)
