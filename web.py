"""Web app.  Run:  uv run uvicorn web:app --reload
Customers chat at  http://127.0.0.1:8000
The owner sees leads at  http://127.0.0.1:8000/admin   (password = ADMIN_KEY in .env)
"""
import secrets
import threading
import time
import traceback

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

import config
import store
from agent import FrontDesk
from chatpage import CHAT_HTML
from webutil import RateLimiter, render_admin_html, valid_session_id

MAX_CHARS = 600                  # longest customer message accepted
MAX_SESSIONS = 300               # chats kept in memory at once
SESSION_TTL = 2 * 3600           # forget idle chats after 2 hours
limiter = RateLimiter(max_calls=30, window=600)   # 30 messages per 10 min per visitor

app = FastAPI(title="Front Desk Assistant", docs_url=None, redoc_url=None)
security = HTTPBasic()

# Load the business file once at start-up. If it is missing, fail right away.
# (After editing the business file, restart the server to pick up the change.)
_probe = FrontDesk()
BUSINESS_NAME, GREETING = _probe.name, _probe.greeting()
store.purge_old_messages()


class Session:
    def __init__(self, bot):
        self.bot, self.lock, self.last = bot, threading.Lock(), time.time()


SESSIONS: dict = {}
SESSIONS_LOCK = threading.Lock()


def get_session(sid: str) -> Session:
    with SESSIONS_LOCK:
        now = time.time()
        for k in [k for k, v in SESSIONS.items() if now - v.last > SESSION_TTL]:
            del SESSIONS[k]
        limiter.cleanup()
        s = SESSIONS.get(sid)
        if s is None:
            if len(SESSIONS) >= MAX_SESSIONS:
                raise HTTPException(503, "We're very busy right now. Please try again in a few minutes.")
            s = SESSIONS[sid] = Session(FrontDesk(session_id=sid))
        s.last = now
        return s


class ChatIn(BaseModel):
    session_id: str
    message: str


@app.get("/", response_class=HTMLResponse)
def home():
    return CHAT_HTML


@app.get("/api/info")
def info():
    return {"name": BUSINESS_NAME, "greeting": GREETING}


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    if not valid_session_id(body.session_id):
        raise HTTPException(400, "Invalid session.")
    msg = body.message.strip()
    if not msg:
        raise HTTPException(400, "Please type a message.")
    if len(msg) > MAX_CHARS:
        raise HTTPException(400, f"Please keep your message under {MAX_CHARS} characters.")
    ip = request.client.host if request.client else "unknown"
    if not limiter.allow(ip):
        raise HTTPException(429, "You're sending messages very quickly. Please wait a few minutes.")

    s = get_session(body.session_id)
    try:
        with s.lock:                      # one message at a time per chat
            return {"reply": s.bot.reply(msg)}
    except Exception:                     # noqa: BLE001
        traceback.print_exc()
        raise HTTPException(500, "Something went wrong. Please try again.")


def require_admin(creds: HTTPBasicCredentials = Depends(security)):
    if not config.ADMIN_KEY:
        raise HTTPException(503, "Admin page is off. Set ADMIN_KEY in .env to turn it on.")
    if not secrets.compare_digest(creds.password.encode("utf-8"),
                                  config.ADMIN_KEY.encode("utf-8")):
        raise HTTPException(401, "Wrong password.", headers={"WWW-Authenticate": "Basic"})


@app.get("/admin", response_class=HTMLResponse)
def admin(_: None = Depends(require_admin)):
    return render_admin_html(store.list_leads(), store.list_handoffs(), BUSINESS_NAME)


@app.get("/admin/leads.csv")
def admin_csv(_: None = Depends(require_admin)):
    path = config.DB_PATH.parent / "leads.csv"
    store.export_leads_csv(path)
    return FileResponse(path, media_type="text/csv", filename="leads.csv")
