import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT.parent  # "the folder holding the apps"
load_dotenv(ROOT / ".env")


# AI keys and the provider choice: ⚙ Ayarlar → backend/providers.py (shared Keychain + os-suite-ai.json)

DB_PATH = ROOT / "data" / "commerce.db"
FRONTEND_DIR = ROOT / "frontend"

# How long a search result is reused from history before it is fetched again (hours)
QUICK_CACHE_HOURS = float(os.getenv("QUICK_CACHE_HOURS", "1"))
DEEP_CACHE_HOURS = float(os.getenv("DEEP_CACHE_HOURS", "6"))

TIMEZONE = os.getenv("TIMEZONE", "Europe/Istanbul")
# "HH:MM,HH:MM" — when tracked products are re-priced from Akakçe (no tokens)
TRACK_SCHEDULE = os.getenv("TRACK_SCHEDULE", "09:00,18:00")
# a drop smaller than this (percent) is not worth a notification when no target price is set
DROP_MIN_PCT = float(os.getenv("DROP_MIN_PCT", "1"))
# daily database backup (data/backups + encrypted copy in iCloud Drive)
BACKUP_KEEP = int(os.getenv("BACKUP_KEEP", "14"))
BACKUP_ICLOUD = os.getenv("BACKUP_ICLOUD", "1").strip() not in ("0", "false", "no", "")
# order emails (read-only IMAP; app password in the Keychain, see backend/mailbox.py)
MAIL_PROVIDER = os.getenv("MAIL_PROVIDER", "gmail").strip().lower()
MAIL_USER = os.getenv("MAIL_USER", "").strip()   # empty = the Keychain item's account


def track_times():
    out = []
    for part in TRACK_SCHEDULE.split(","):
        if part.strip():
            h, m = part.strip().split(":")
            out.append((int(h), int(m)))
    return out


# Host names the API answers to (DNS rebinding guard). A local reverse proxy sends Host 127.0.0.1:<port>.
ALLOWED_HOSTS = {h.strip().lower() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",") if h.strip()}

# Sent with every outgoing request (store home pages, Akakçe): an ordinary desktop browser
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")
HTTP_TIMEOUT = 12

# Stores added on first start (the user can remove any of them)
# a new user starts with these stores, in one open group
DEFAULT_GROUP = "Alışveriş"
DEFAULT_SITES = [
    "https://www.hepsiburada.com",
    "https://www.amazon.com.tr",
    "https://www.trendyol.com",
    "https://www.n11.com",
]
