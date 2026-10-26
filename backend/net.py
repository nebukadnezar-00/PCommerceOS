"""Outgoing HTTP with a guard: only public http(s) addresses, every redirect hop re-checked, size capped.

Site URLs come from the user and product links from Gemini, so a request must never reach this computer,
the router or another device on the home network (SSRF)."""
import ipaddress
import shutil
import socket
import subprocess
from urllib.parse import urljoin, urlsplit

import requests

from . import config, platform_os


class Blocked(ValueError):
    pass


def check_url(url):
    """Raise Blocked unless `url` is http(s) and its host resolves only to public addresses."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise Blocked("Yalnızca http/https adresleri")
    if parts.username or parts.password:
        raise Blocked("Adreste kullanıcı bilgisi olamaz")
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or (443 if parts.scheme == "https" else 80),
                                   proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise Blocked("Alan adı bulunamadı")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global or ip.is_multicast:
            raise Blocked("Yerel ağ adreslerine istek atılmaz")


CURL = "/usr/bin/curl" if platform_os.IS_MAC else (shutil.which("curl") or "curl")   # Windows 10+: curl.exe


def _curl_once(url, max_bytes, connect_timeout, max_time):
    """(status, body, redirect location) through the system's curl."""
    try:
        p = subprocess.run(
            [CURL, "-sS", "--proto", "=https", "--compressed", "--max-time", str(max_time),
             *(["--connect-timeout", str(connect_timeout)] if connect_timeout else []),
             "--max-filesize", str(max_bytes), "-A", config.USER_AGENT,
             "-H", "Accept-Language: tr-TR,tr;q=0.9,en;q=0.6", "-w", "\n%{http_code} %{redirect_url}", url],
            capture_output=True, timeout=max_time + 5,
            **({"creationflags": 0x08000000} if platform_os.IS_WIN else {}))      # no console window
    except (OSError, subprocess.TimeoutExpired) as e:
        raise requests.ConnectionError(str(e))
    if p.returncode != 0:
        raise requests.ConnectionError(p.stderr.decode("utf-8", "replace").strip()[:200] or f"curl {p.returncode}")
    body, _, tail = p.stdout.rpartition(b"\n")
    code, _, location = tail.decode("ascii", "replace").partition(" ")
    return int(code or 0), body, location.strip()


def _browser_like_once(url, max_bytes, connect_timeout, max_time):
    """(status, body, location) with a Chrome-like TLS handshake (curl_cffi; installed off macOS only).
    Windows' curl.exe speaks through Schannel, which Cloudflare may refuse where macOS's curl gets in."""
    from curl_cffi import requests as cffi
    try:
        r = cffi.get(url, impersonate="chrome", allow_redirects=False, timeout=(connect_timeout or max_time, max_time),
                     headers={"Accept-Language": "tr-TR,tr;q=0.9,en;q=0.6"})
    except Exception as e:
        raise requests.ConnectionError(str(e)[:200])
    return r.status_code, r.content[:max_bytes], (r.headers.get("location") or "").strip()


def curl_get(url, max_bytes=3_000_000, max_redirects=3, connect_timeout=None, max_time=None):
    """GET through the system's curl: some sites behind Cloudflare (Akakçe) answer Python's TLS
    client with 403 but let curl through. Off macOS a 403 (or no curl) is retried with a Chrome-like
    handshake when curl_cffi is installed. Redirects are followed by hand, each hop checked like the
    first (Akakçe sends brand searches such as "iphone" on to a category page).
    connect_timeout / max_time (seconds) let a search give up quickly and try its next source.
    Returns (status, body bytes); raises Blocked or requests.RequestException."""
    max_time = max_time or config.HTTP_TIMEOUT
    for _ in range(max_redirects + 1):
        check_url(url)
        try:
            status, body, location = _curl_once(url, max_bytes, connect_timeout, max_time)
        except requests.ConnectionError:
            if platform_os.IS_MAC or not _has_cffi():
                raise
            status = 0
        if status in (0, 403) and not platform_os.IS_MAC and _has_cffi():
            status, body, location = _browser_like_once(url, max_bytes, connect_timeout, max_time)
        if status in (301, 302, 303, 307, 308) and location:
            url = urljoin(url, location)
            continue
        return status, body
    raise requests.TooManyRedirects("Çok fazla yönlendirme")


def _has_cffi():
    try:
        import curl_cffi  # noqa: F401
        return True
    except ImportError:
        return False


def get(url, max_bytes=3_000_000, max_redirects=5, **kw):
    """GET following redirects by hand (each hop checked). Returns the response with `.content` filled,
    truncated to max_bytes; raises Blocked or requests.RequestException."""
    headers = {"User-Agent": config.USER_AGENT, "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.6"}
    headers.update(kw.pop("headers", {}))
    for _ in range(max_redirects + 1):
        check_url(url)
        r = requests.get(url, headers=headers, timeout=config.HTTP_TIMEOUT, allow_redirects=False,
                         stream=True, **kw)
        if r.is_redirect and r.headers.get("location"):
            r.close()
            url = urljoin(url, r.headers["location"])
            continue
        body = b""
        for chunk in r.iter_content(65536):
            body += chunk
            if len(body) >= max_bytes:
                break
        r.close()
        r._content = body[:max_bytes]
        r.url = url
        return r
    raise requests.TooManyRedirects("Çok fazla yönlendirme")
