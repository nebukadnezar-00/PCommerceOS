"""What differs between macOS and Windows: the secret store, the cloud folder for backups, desktop
notifications, and the openssl-compatible backup encryption.

ONE FILE, COPIED AS-IS into every OS Suite app (FinanceOS/backend, CommerceOS/backend, …) — change it in
FinanceOS and copy it over. It imports nothing from the module around it.

Secrets: on macOS the `security` tool, so items already in the Keychain keep working without a
"python wants to use your keychain" prompt; elsewhere the `keyring` package (Windows Credential
Manager, Linux Secret Service)."""
import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("os-suite.platform")

IS_MAC = sys.platform == "darwin"
IS_WIN = sys.platform.startswith("win")

DEFAULT_ACCOUNT = "os-suite"


def secret_store_name():
    """How the secret store is called in the UI."""
    if IS_MAC:
        return "Anahtar Zinciri"
    if IS_WIN:
        return "Windows Kimlik Bilgisi Yöneticisi"
    return "sistem anahtar deposu"


# ------------------------------------------------------------ secrets

def _keyring():
    import keyring             # not installed on macOS (requirements marker)
    return keyring


def secret_get(service, account=None):
    """The stored secret, or None. account=None: any account under this service (macOS), the default
    account elsewhere."""
    if IS_MAC:
        args = ["security", "find-generic-password", *(["-a", account] if account else []), "-s", service, "-w"]
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        return (r.stdout.rstrip("\n") or None) if r.returncode == 0 else None
    try:
        return _keyring().get_password(service, account or DEFAULT_ACCOUNT) or None
    except Exception as e:
        log.info("secret store unavailable: %s", e)
        return None


def secret_account(service):
    """macOS: the account name of the service's item (no password read); elsewhere None."""
    if not IS_MAC:
        return None
    try:
        r = subprocess.run(["security", "find-generic-password", "-s", service],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    for line in r.stdout.splitlines():
        if '"acct"' in line and "=" in line:
            v = line.split("=", 1)[1].strip()
            return v.strip('"') if v.startswith('"') else None
    return None


def _quote(v):
    if any(c in v for c in '"\\\n\r'):
        raise ValueError("Tırnak, ters bölü ve satır sonu kullanılamaz")
    return f'"{v}"'


def secret_set(service, account, secret):
    """Store (or replace) a secret. macOS: `security -i` on stdin, so it never shows up in `ps`."""
    account = account or DEFAULT_ACCOUNT
    if IS_MAC:
        cmd = f"add-generic-password -U -a {_quote(account)} -s {_quote(service)} -w {_quote(secret)}\n"
        r = subprocess.run(["security", "-i"], input=cmd, capture_output=True, text=True, timeout=10)
        if r.returncode != 0 or "error" in (r.stderr or "").lower():
            raise RuntimeError(f"{secret_store_name()}'ne yazılamadı")
        return
    try:
        _keyring().set_password(service, account, secret)
    except Exception as e:
        raise RuntimeError(f"{secret_store_name()}'ne yazılamadı: {e}") from e


def secret_delete(service, account=None):
    """Remove the item (every item of the service when account is None on macOS)."""
    if IS_MAC:
        for _ in range(5):                 # more than one item may carry the service name
            r = subprocess.run(["security", "delete-generic-password", *(["-a", account] if account else []),
                                "-s", service], capture_output=True, text=True, timeout=10)
            if r.returncode != 0:
                break
        return
    try:
        _keyring().delete_password(service, account or DEFAULT_ACCOUNT)
    except Exception:
        pass                               # nothing stored


# ------------------------------------------------------------ cloud folder for backups

def cloud_root():
    """(folder, name) of the synced cloud drive, or (None, None) when there is none."""
    if IS_MAC:
        p = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs"
        return (p, "iCloud Drive") if p.is_dir() else (None, None)
    if IS_WIN:
        for var in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            v = os.environ.get(var)
            if v and Path(v).is_dir():
                return Path(v), "OneDrive"
    return None, None


# ------------------------------------------------------------ desktop notification

_PS_TOAST = r"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$x = $t.GetElementsByTagName('text')
$x.Item(0).AppendChild($t.CreateTextNode($env:OS_SUITE_TITLE)) | Out-Null
$x.Item(1).AppendChild($t.CreateTextNode($env:OS_SUITE_MESSAGE)) | Out-Null
$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show([Windows.UI.Notifications.ToastNotification]::new($t))
"""


def notify(title, message):
    """Desktop notification, best effort: never blocks, never raises."""
    try:
        if IS_MAC:
            esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
            args = ["osascript", "-e", f'display notification "{esc(message)}" with title "{esc(title)}" sound name "Glass"']
            env = None
        elif IS_WIN:
            # the text goes through the environment, so nothing in it is ever run as script
            args = ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", _PS_TOAST]
            env = {**os.environ, "OS_SUITE_TITLE": title, "OS_SUITE_MESSAGE": message}
        else:
            args, env = ["notify-send", title, message], None
        subprocess.Popen(args, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         **({"creationflags": 0x08000000} if IS_WIN else {}))      # CREATE_NO_WINDOW
    except Exception as e:
        log.info("notification failed: %s", e)


# ------------------------------------------------------------ backup encryption

# Same format as `openssl enc -aes-256-cbc -salt -pbkdf2 -iter 200000 -md sha256`, so backups made
# with macOS's openssl open here and the other way round: "Salted__" + 8-byte salt + ciphertext, key and
# IV from PBKDF2-HMAC-SHA256.
_MAGIC = b"Salted__"
_ITER = 200_000


def _cipher(secret, salt):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=48, salt=salt, iterations=_ITER)
    km = kdf.derive(secret.encode("utf-8"))
    return Cipher(algorithms.AES(km[:32]), modes.CBC(km[32:]))


def encrypt_file(src, dst, secret):
    from cryptography.hazmat.primitives import padding
    salt = os.urandom(8)
    enc = _cipher(secret, salt).encryptor()
    pad = padding.PKCS7(128).padder()
    with open(src, "rb") as f, open(dst, "wb") as out:
        out.write(_MAGIC + salt)
        for chunk in iter(lambda: f.read(1 << 20), b""):
            out.write(enc.update(pad.update(chunk)))
        out.write(enc.update(pad.finalize()) + enc.finalize())


def decrypt_file(src, dst, secret):
    """Raises ValueError on a wrong passphrase or a damaged file."""
    from cryptography.hazmat.primitives import padding
    with open(src, "rb") as f, open(dst, "wb") as out:
        head = f.read(16)
        if len(head) != 16 or head[:8] != _MAGIC:
            raise ValueError("şifreli yedek biçimi tanınmadı")
        dec = _cipher(secret, head[8:]).decryptor()
        unpad = padding.PKCS7(128).unpadder()
        for chunk in iter(lambda: f.read(1 << 20), b""):
            out.write(unpad.update(dec.update(chunk)))
        try:
            out.write(unpad.update(dec.finalize()) + unpad.finalize())
        except ValueError as e:
            raise ValueError("yedek şifresi yanlış ya da dosya bozuk") from e
