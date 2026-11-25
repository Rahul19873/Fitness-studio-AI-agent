# Fitness Studio AI Agent

An AI front-desk assistant for gyms, salons and other local businesses.
It answers customer questions from the business's own information, collects
leads (with the customer's consent), and hands difficult chats to a human.

Built with Python, FastAPI, SQLite and the Gemini API.

> **Status:** working prototype (MVP). Not yet load-tested. See [Limitations](#limitations).

## What it does

- Answers questions about plans, prices, timings and trials, in English, Hindi or Hinglish
- Collects a lead (name, phone, interest, preferred time) only after the customer agrees
- Never confirms a booking: the team confirms every visit request
- Refuses medical, diet and injury advice, and hands those chats to a human
- Hands over to a human for complaints, refunds, or anything it is not sure about
- Does not collect a phone number from anyone who says they are under 18
- Keeps working through Gemini outages by switching to fallback models

## Two editions

| | Single business | SaaS (many businesses) |
|---|---|---|
| App | `web.py` | `saas.py` |
| Business details | a file in `business/` | stored in the database, edited by the owner |
| Chat page | `/` | `/c/<web-address>` |
| Owner page | `/admin` (one password) | `/c/<web-address>/admin` (each business has its own password) |
| Your admin page | n/a | `/super` |

The SaaS edition also has per-business monthly message limits, switching a
business on or off, and deleting a business with all of its data.

## Quick start (Windows PowerShell, with [uv](https://docs.astral.sh/uv/))

```powershell
uv sync                      # or: uv add google-genai python-dotenv fastapi uvicorn
copy .env.example .env       # then fill in the values (see below)
uv run test_offline.py       # checks that need no internet
uv run test_saas_offline.py
```

Chat in the terminal:

```powershell
uv run chat.py
```

Run the SaaS web app:

```powershell
uv run python -m uvicorn saas:app --reload
```

Then open `http://127.0.0.1:8000/super`, add a business, and visit
`http://127.0.0.1:8000/c/<web-address>`.

Run the single-business edition instead with `uv run python -m uvicorn web:app --reload`.

## Settings (environment variables)

Never commit real values. Locally they live in `.env` (ignored by git). On a
host such as Render, set them in its environment settings.

| Name | Needed for | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | both | Gemini API key. Use a **paid-tier** key for real customers |
| `GEMINI_MODEL` | optional | First model to try. Fallbacks are in `config.py` |
| `SECRET_KEY` | SaaS | Long random text used to sign form tokens |
| `SUPER_ADMIN_KEY` | SaaS | Password for `/super` |
| `SITE_NAME`, `CONTACT_EMAIL` | SaaS | Shown on the landing page |
| `DB_PATH` | both | Where the SQLite file lives. Keep it outside the code folder |
| `RETENTION_DAYS` | optional | Chat logs are deleted after this many days (default 90) |
| `ADMIN_KEY` | single business | Password for `/admin` |
| `BUSINESS_FILE` | single business | Which file in `business/` to use |

Generate a `SECRET_KEY`:

```powershell
uv run python -c "import secrets; print(secrets.token_hex(32))"
```

## Deploying (Render example)

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn saas:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"`
- Health check path: `/health`
- Set the environment variables above, and `PYTHON_VERSION`
- For real clients, use a paid instance with a **persistent disk**, and set
  `DB_PATH` to a file on that disk. Free instances sleep when idle and lose
  their files on restart.
- Run **one** server instance only (see Limitations).

## Project structure

```
saas.py            SaaS web app (many businesses)
web.py             single-business web app
agent.py           the assistant: prompt, Gemini chat, retries, model fallback
tools.py           actions the assistant may take (save lead, hand off to human)
store.py           SQLite storage; every query is scoped to one business
tenants.py         business accounts, password hashing, monthly limits
webutil.py         rate limiter, form tokens, owner/admin page rendering
chatpage.py        the customer chat page
chat.py            chat in the terminal
leads.py           list or export leads from the terminal
config.py          settings read from the environment
business/          business details for the single-business edition
test_offline.py, test_web_offline.py, test_saas_offline.py
```

## Security and privacy notes

- Passwords are stored as salted hashes, and repeated wrong logins are blocked
- Owner and admin forms use signed tokens against forged requests
- Everything customers type is escaped before it is shown to an owner
- CSV exports neutralise spreadsheet formulas
- One business can never read or delete another business's data (covered by tests)
- Chat logs are deleted after `RETENTION_DAYS`. Owners can delete individual leads
- The assistant tells customers it is an AI and asks permission before saving contact details
- Everything in a business's information is sent to Gemini on every chat, so
  **never put private or confidential information in it**
- Customer data (`data/`) and `.env` are never committed. Back up the data folder regularly


All rights reserved. (Choose a license before sharing this code publicly.)
