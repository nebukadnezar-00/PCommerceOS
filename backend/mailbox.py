"""Read-only IMAP access to the user's mailbox (order emails), with the password in the system's secret
store (macOS Keychain; elsewhere platform_os: Windows Credential Manager, address and password together).

The user enters their Gmail address and an app password in ⚙ Ayarlar → E-posta (save(): the login is
tried first, then the password goes to the Keychain). An item saved earlier in Terminal with
    security add-generic-password -s "CommerceOS Gmail" -a <adres> -w
is the same item and keeps working. Only Gmail is offered; iCloud/Yandex/Yahoo are the same code with
another host.
Outlook.com no longer accepts passwords over IMAP: forward its mail to Gmail instead."""
import email
import imaplib
import json
import logging
import re
import subprocess
import time
from datetime import datetime, timedelta, timezone
from email import policy

from . import config, platform_os

log = logging.getLogger("commerceos.mailbox")

PRESETS = {
    "gmail":  {"host": "imap.gmail.com",      "service": "CommerceOS Gmail"},
    "icloud": {"host": "imap.mail.me.com",    "service": "CommerceOS iCloud"},
    "yandex": {"host": "imap.yandex.com",     "service": "CommerceOS Yandex"},
    "yahoo":  {"host": "imap.mail.yahoo.com", "service": "CommerceOS Yahoo"},
}
TIMEOUT = 30


class MailError(RuntimeError):
    pass


def preset():
    return PRESETS.get(config.MAIL_PROVIDER, PRESETS["gmail"])


def credentials():
    """(address, app password) from the Keychain, or None when it has not been set up."""
    service = preset()["service"]
    if not platform_os.IS_MAC:
        try:
            v = json.loads(platform_os.secret_get(service) or "null")
            return (config.MAIL_USER or v["user"], v["password"]) if v and v.get("password") else None
        except (ValueError, KeyError, TypeError):
            return None
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", service, "-g"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    # the item's attributes go to stdout, the password ("password: "…"") to stderr
    acct = re.search(r'"acct"<blob>="([^"]*)"', r.stdout)
    pw = re.search(r'^password: "(.*)"$', r.stderr, re.M)
    user = config.MAIL_USER or (acct.group(1) if acct else "")
    if not (user and pw and pw.group(1)):
        return None
    return user, pw.group(1).replace(" ", "")   # Google shows app passwords in groups of four


_configured_cache = None      # (when, answer); None = not asked yet (monotonic time may start near 0)

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
APP_PASSWORD_RE = re.compile(r"^[A-Za-z]{16}$")     # Google's app passwords: 16 letters (shown in fours)


def account():
    """The address the Keychain item belongs to (no password is read), or None."""
    if not platform_os.IS_MAC:
        return (credentials() or (None,))[0]
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", preset()["service"]],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    acct = re.search(r'"acct"<blob>="([^"]*)"', r.stdout) if r.returncode == 0 else None
    return config.MAIL_USER or (acct.group(1) if acct else None)


def mask(address):
    name, _, domain = (address or "").partition("@")
    return f"{name[:2]}***@{domain}" if name and domain else ""


def _clean(user, password):
    user, password = (user or "").strip(), re.sub(r"\s+", "", password or "")
    if not EMAIL_RE.match(user):
        raise MailError("Geçerli bir Gmail adresi girin")
    if not APP_PASSWORD_RE.match(password):
        raise MailError("Bu bir uygulama şifresine benzemiyor; Gmail şifreni değil, Google'ın verdiği 16 harfli şifreyi gir")
    return user, password


def _login(user, password):
    """Log in and list the folders (no mail is read): {"all": …, "spam": …, "trash": …}."""
    host = preset()["host"]
    try:
        conn = imaplib.IMAP4_SSL(host, timeout=TIMEOUT)
    except (OSError, imaplib.IMAP4.error) as e:
        raise MailError("Gmail'e bağlantı kurulamadı; internet bağlantını kontrol et") from e
    try:
        try:
            conn.login(user, password)
        except imaplib.IMAP4.error as e:
            raise MailError("Şifre kabul edilmedi: adresi ve uygulama şifresini kontrol et") from e
        return _folders(conn)
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def test(user, password):
    user, password = _clean(user, password)
    folders = _login(user, password)
    extra = [name for kind, name in (("spam", "Spam"), ("trash", "Çöp kutusu")) if kind in folders]
    return "Giriş başarılı" + (f" · {' ve '.join(extra)} da taranacak" if extra else "")


def _keychain_write(user, password):
    """Through `security -i` on stdin, so the password never shows in `ps`; one item per service."""
    service = preset()["service"]
    _keychain_delete()
    if not platform_os.IS_MAC:
        try:
            platform_os.secret_set(service, None, json.dumps({"user": user, "password": password}))
        except RuntimeError as e:
            raise MailError(str(e)) from e
        return
    cmd = f'add-generic-password -U -a "{user}" -s "{service}" -w "{password}"\n'
    r = subprocess.run(["security", "-i"], input=cmd, capture_output=True, text=True, timeout=10)
    if r.returncode != 0 or "error" in (r.stderr or "").lower():
        raise MailError(f"{platform_os.secret_store_name()}'ne yazılamadı")


def _keychain_delete():
    if not platform_os.IS_MAC:
        platform_os.secret_delete(preset()["service"])
        return
    for _ in range(5):      # an item saved under another address too
        r = subprocess.run(["security", "delete-generic-password", "-s", preset()["service"]],
                           capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            break


def _forget():
    global _configured_cache
    _configured_cache = None


def save(user, password):
    """Tests the login, then keeps the password in the Keychain. Nothing is written when it fails."""
    message = test(user, password)
    user, password = _clean(user, password)
    _keychain_write(user, password)
    _forget()
    return message


def remove():
    _keychain_delete()
    _forget()


def configured():
    """Whether the Keychain item exists (checked at most once a minute: /api/status asks often). A "no"
    is asked again after 10 s: the Keychain can be slow to answer right after a restart, and the
    refresh button stays hidden while the mailbox counts as not set up."""
    global _configured_cache
    at, ok = _configured_cache or (None, False)
    if at is None or time.monotonic() - at > (60 if ok else 10):
        ok = credentials() is not None
        _configured_cache = (time.monotonic(), ok)
    return ok


def _folders(conn):
    """Gmail's special folders by flag (their names are localized: "[Gmail]/Tüm Postalar", "[Gmail]/Spam",
    "[Gmail]/Çöp Kutusu"): {"all": …, "spam": …, "trash": …}."""
    out = {}
    typ, data = conn.list()
    for line in data or []:
        line = line.decode("utf-8", "replace") if isinstance(line, bytes) else str(line)
        m = re.search(r'"([^"]+)"\s*$', line) or re.search(r"(\S+)\s*$", line)
        if not m:
            continue
        for flag, kind in (("\\All", "all"), ("\\Junk", "spam"), ("\\Trash", "trash")):
            if flag in line:
                out[kind] = '"%s"' % m.group(1)
    return out


def _all_mail(conn):
    return _folders(conn).get("all", "INBOX")


def _gmail_query(domains, days):
    froms = " ".join(f"from:{d}" for d in domains)
    names = " ".join(f'"{d}"' for d in domains)
    # mail forwarded from another address carries the store only in its body
    return (f"newer_than:{days}d ({{{froms}}} OR (subject:(sipariş OR kargo OR teslim OR iptal OR iade) "
            f"{{{names}}}))")


def _fetch_folder(conn, folder, kind, gmail, domains, days, known):
    typ, _ = conn.select(folder, readonly=True)
    if typ != "OK":
        return []
    if gmail:
        # sent as a UTF-8 literal: the query has Turkish letters
        conn.literal = _gmail_query(domains, days).encode("utf-8")
        typ, data = conn.uid("SEARCH", "CHARSET", "UTF-8", "X-GM-RAW")
    else:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
        crit = f'FROM "{domains[0]}"'
        for d in domains[1:]:
            crit = f'OR {crit} FROM "{d}"'
        typ, data = conn.uid("SEARCH", None, f"SINCE {since} {crit}")
    uids = (data[0] or b"").split() if typ == "OK" and data else []
    out = []
    for uid in uids:
        typ, head = conn.uid("FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
        raw = next((p[1] for p in head or [] if isinstance(p, tuple)), b"")
        mid = email.message_from_bytes(raw, policy=policy.default).get("Message-ID", "").strip()
        if mid and mid in known:
            continue
        typ, body = conn.uid("FETCH", uid, "(BODY.PEEK[])")
        raw = next((p[1] for p in body or [] if isinstance(p, tuple)), None)
        if raw:
            out.append((raw, kind))
    return out


def fetch(domains, days, known=frozenset()):
    """(raw message, folder) pairs from the stores' domains in the last `days` days, skipping Message-IDs
    in `known`. folder is "all", "spam" or "trash": order mail often lands in Spam, or is deleted by a
    filter. Opens every folder read-only and peeks, so nothing is marked as read."""
    creds = credentials()
    if not creds:
        raise MailError("E-posta bağlantısı kurulmadı")
    if not domains:
        return []
    host = preset()["host"]
    try:
        conn = imaplib.IMAP4_SSL(host, timeout=TIMEOUT)
    except (OSError, imaplib.IMAP4.error) as e:
        raise MailError(f"{host} adresine bağlanılamadı") from e
    try:
        try:
            conn.login(*creds)
        except imaplib.IMAP4.error as e:
            raise MailError("E-posta girişi reddedildi (uygulama şifresini kontrol edin)") from e
        gmail = host == PRESETS["gmail"]["host"]
        folders = _folders(conn)
        if not gmail or "all" not in folders:
            folders = {**folders, "all": "INBOX"} if not gmail else {"all": "INBOX", **folders}
        out = []
        for kind in ("all", "spam", "trash"):
            if kind in folders:
                out += _fetch_folder(conn, folders[kind], kind, gmail, domains, days, known)
        return out
    except imaplib.IMAP4.error as e:
        raise MailError(f"E-posta okunamadı: {e}") from e
    finally:
        try:
            conn.logout()
        except Exception:
            pass
