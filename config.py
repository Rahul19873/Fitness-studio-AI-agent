import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE = Path(__file__).parent

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# First model tried, then the fallbacks in order if it is busy or unavailable.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
FALLBACK_MODELS = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
                   "gemini-3.7-flash", "gemini-3.8-flash"]

# Which business this assistant represents. One file per client.
BUSINESS_FILE = Path(os.getenv("BUSINESS_FILE", str(BASE / "business" / "sample_gym.md")))

DB_PATH = Path(os.getenv("DB_PATH", str(BASE / "data" / "frontdesk.db")))

# Chat logs are deleted after this many days (keep personal data only as long as needed).
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", "90"))

# Password for the owner's /admin page (username can be anything).
# If empty, the admin page is switched off.
ADMIN_KEY = os.getenv("ADMIN_KEY", "")

# ---- SaaS edition ----
# Long random text used to sign security tokens. Generate one with:
#   uv run python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY = os.getenv("SECRET_KEY", "")
# Your own password for the /super page where you add and manage clients.
SUPER_ADMIN_KEY = os.getenv("SUPER_ADMIN_KEY", "")
SITE_NAME = os.getenv("SITE_NAME", "Front Desk Assistant")
CONTACT_EMAIL = os.getenv("CONTACT_EMAIL", "")