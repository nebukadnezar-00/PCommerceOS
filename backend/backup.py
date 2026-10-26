"""Daily SQLite backup to data/backups and, encrypted, to a cloud folder; keeps the last N days.

The cloud folder is iCloud Drive on a Mac and OneDrive on Windows ("CommerceOS Yedek" in it), or a
folder the user picks in ⚙ Ayarlar → Yedek (data/backup.json). The copy there is AES-256 encrypted in
openssl's format (platform_os), so files made on either OS open on the other. The passphrase lives in
the system's secret store: service "CommerceOS Yedek" if the user set one, otherwise the FinanceOS
backup passphrase ("FinanceOS Yedek") is reused, so one passphrase opens every backup. The cloud copy is
optional: without a passphrase nothing goes to the cloud and nothing warns about it."""
import json
import logging
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import config, platform_os, providers

log = logging.getLogger("commerceos.backup")

APP = "CommerceOS"
LOCAL_DIR = config.DB_PATH.parent / "backups"
SETTINGS_FILE = config.DB_PATH.parent / "backup.json"
PREFIX = "commerceos-"
KEYCHAIN_SERVICES = ("CommerceOS Yedek", "FinanceOS Yedek")      # own first; the first one is written
CLOUD_DIR = None              # tests: a fixed cloud folder instead of the detected one
MIN_PASSPHRASE = 8


def _today():
    return datetime.now(ZoneInfo(config.TIMEZONE)).strftime("%Y-%m-%d")


def _prune(folder, keep, suffix=".db"):
    files = sorted(folder.glob(f"{PREFIX}*{suffix}"))
    for old in files[:-keep] if keep > 0 else []:
        try:
            old.unlink()
        except OSError as e:
            log.warning("could not remove old backup %s: %s", old, e)


# ------------------------------------------------------------ where

def _settings():
    try:
        return json.loads(SETTINGS_FILE.read_text())
    except (OSError, ValueError):
        return {}


def cloud():
    """(folder, label): the chosen folder, else "<cloud drive>/CommerceOS Yedek", else (None, None)."""
    if CLOUD_DIR is not None:
        return Path(CLOUD_DIR), "bulut"
    custom = _settings().get("dir")
    if custom:
        return Path(custom), "seçilen klasör"
    root, name = platform_os.cloud_root()
    return (root / f"{APP} Yedek", name) if root else (None, None)


def set_dir(folder):
    """A folder of the user's choice (None: back to the detected cloud folder)."""
    data = _settings()
    if folder:
        p = Path(folder).expanduser()
        if not p.is_absolute():
            raise ValueError("Tam klasör yolu gir")
        if not p.parent.is_dir():
            raise ValueError("Bu klasörün bulunduğu yer yok")
        data["dir"] = str(p)
    else:
        data.pop("dir", None)
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, ensure_ascii=False))


# ------------------------------------------------------------ passphrase

def passphrase():
    """Backup passphrase from the secret store, or None when it has not been set."""
    for service in KEYCHAIN_SERVICES:
        v = platform_os.secret_get(service)
        if v:
            return v
    return None


def set_passphrase(secret):
    secret = secret or ""
    if len(secret) < MIN_PASSPHRASE:
        raise ValueError(f"Şifre en az {MIN_PASSPHRASE} karakter olmalı")
    platform_os.secret_set(KEYCHAIN_SERVICES[0], None, secret)
    _forget()


def _forget():
    global _cloud_error
    _cloud_error = None


def encrypt(src, dst, secret):
    """Encrypt, then decrypt into a temp file and check SQLite integrity before keeping it."""
    tmp = dst.with_name(dst.name + ".tmp")
    platform_os.encrypt_file(src, tmp, secret)
    with tempfile.TemporaryDirectory() as d:
        check = Path(d) / "check.db"
        platform_os.decrypt_file(tmp, check, secret)
        con = sqlite3.connect(check)
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("şifreli yedek doğrulanamadı")
        finally:
            con.close()
    tmp.replace(dst)


_cloud_error = None      # the last cloud copy's failure, once the user turned it on with a passphrase


def warning():
    """Shown in the status bar only when the cloud copy the user turned on has failed."""
    return _cloud_error


def _newest(folder, suffix):
    files = sorted(folder.glob(f"{PREFIX}*{suffix}")) if folder and folder.is_dir() else []
    return files[-1].name[len(PREFIX):len(PREFIX) + 10] if files else None


def status():
    """For ⚙ Ayarlar → Yedek. The passphrase itself is never returned."""
    folder, label = cloud()
    return {"local_dir": str(LOCAL_DIR), "keep": config.BACKUP_KEEP, "last_local": _newest(LOCAL_DIR, ".db"),
            "cloud_on": config.BACKUP_ICLOUD, "cloud_dir": str(folder) if folder else None, "cloud_name": label,
            "custom_dir": bool(_settings().get("dir")), "last_cloud": _newest(folder, ".db.enc"),
            "passphrase_set": bool(passphrase()), "store": platform_os.secret_store_name()}


def has_today():
    return (LOCAL_DIR / f"{PREFIX}{_today()}.db").exists()


def run():
    """Consistent copy via SQLite's online backup API (safe with WAL)."""
    if not config.DB_PATH.exists():
        return None
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    target = LOCAL_DIR / f"{PREFIX}{_today()}.db"
    tmp = target.with_suffix(".tmp")
    src = sqlite3.connect(config.DB_PATH)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
        dst.execute("PRAGMA journal_mode=DELETE")   # self-contained file: no -wal/-shm next to it
    finally:
        dst.close()
        src.close()
    tmp.replace(target)
    for side in [*LOCAL_DIR.glob(f"{PREFIX}*-shm"), *LOCAL_DIR.glob(f"{PREFIX}*-wal")]:
        side.unlink(missing_ok=True)                 # SQLite side files of the copy (it is not a live db)
    _prune(LOCAL_DIR, config.BACKUP_KEEP)
    log.info("backup written: %s", target)

    global _cloud_error
    folder, _ = cloud()
    secret = passphrase()
    if config.BACKUP_ICLOUD and folder and secret:       # no passphrase: the user has not opted in
        try:
            if not folder.parent.exists():
                raise FileNotFoundError(f"{folder.parent} bulunamadı")
            folder.mkdir(exist_ok=True)
            enc = folder / (target.name + ".enc")
            encrypt(target, enc, secret)
            for plain in folder.glob(f"{PREFIX}*.db"):      # older unencrypted copies
                plain.unlink()
                log.info("removed unencrypted cloud backup %s", plain.name)
            _prune(folder, config.BACKUP_KEEP, ".db.enc")
            log.info("encrypted backup written: %s", enc)
            _cloud_error = None
        except Exception as e:
            log.warning("cloud backup skipped: %s", e)
            _cloud_error = f"Bulut yedeği alınamadı: {e} (⚙ Ayarlar › Yedek)"
    return target


# ------------------------------------------------------------ ⚙ Ayarlar → Yedek

class BackupIn(BaseModel):
    passphrase: Optional[str] = None     # set or change; never sent back
    dir: Optional[str] = None            # a folder of the user's choice
    default_dir: bool = False            # back to the detected cloud folder


def make_router():
    """The /api/settings/backup endpoints (writes only from this computer, like the AI keys)."""
    router = APIRouter()

    def local(request):
        if not providers.is_local(request):
            raise HTTPException(403, "Bu ayar yalnızca uygulamanın çalıştığı bilgisayardan değiştirilebilir")

    def view(request):
        return dict(status(), editable=providers.is_local(request))

    @router.get("/api/settings/backup")
    def get_backup(request: Request):
        return view(request)

    @router.put("/api/settings/backup")
    def put_backup(body: BackupIn, request: Request):
        local(request)
        try:
            if body.passphrase is not None:
                set_passphrase(body.passphrase)
            if body.default_dir:
                set_dir(None)
            elif body.dir is not None:
                set_dir(body.dir.strip() or None)
        except (ValueError, RuntimeError) as e:
            raise HTTPException(400, str(e))
        return view(request)

    @router.post("/api/settings/backup/run")
    def run_now(request: Request):
        local(request)
        target = run()
        if not target:
            raise HTTPException(400, "Henüz yedeklenecek veri yok")
        return dict(view(request), message=f"Yedeklendi · {target.name}")

    return router


# ------------------------------------------------------------ restore helper (any OS, no openssl needed)

if __name__ == "__main__":
    # python -m backend.backup <file.db.enc> <out.db>   (asks for the backup passphrase)
    import getpass
    import sys
    if len(sys.argv) != 3:
        sys.exit("Kullanım: python -m backend.backup <yedek.db.enc> <çıkış.db>")
    try:
        platform_os.decrypt_file(sys.argv[1], sys.argv[2], getpass.getpass("Yedek şifresi: "))
    except ValueError as e:
        sys.exit(str(e))
    print("Açıldı:", sys.argv[2])
