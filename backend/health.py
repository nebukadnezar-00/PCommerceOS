"""Health shown in the header: can the quick search reach Akakçe and still read its pages (no tokens),
is deep search set up.

Two background checks, so the status poll never waits on the network:
- reachability: Akakçe's home page, every few minutes;
- page structure: a known search and its first product page, every few hours, to notice when Akakçe
  changes its markup and the parser silently finds nothing. Real searches and price checks report
  what they saw too, so a breakage shows up as soon as it happens.
Until a check has run its state is None ("checking")."""
import logging
import threading
import time

import requests

from . import akakce as akakce_pages, config, net, providers

log = logging.getLogger("commerceos.health")

PROBE_URL = "https://www.akakce.com/"
PROBE_EVERY = 300        # seconds between reachability checks while it works
RETRY_EVERY = 60         # sooner while it is down
PARSE_QUERY = "airpods pro 2"   # always has products and many offers
PARSE_EVERY = 6 * 3600   # structure check while it works
PARSE_RETRY = 1800       # sooner while broken (or unknown)

_lock = threading.Lock()
_state = {"ok": None, "checked_at": 0.0, "error": None, "running": False}
_parse = {"ok": None, "checked_at": 0.0, "error": None, "running": False}


def _probe():
    if akakce_pages.paused_for():
        # do not ask while Akakçe is limiting us: that only extends the limit
        with _lock:
            _state.update(ok=False, error="çok sık istek, bekletiyor (HTTP 429)", checked_at=time.time(), running=False)
        return
    try:
        status, _ = net.curl_get(PROBE_URL, max_bytes=300_000)
        ok, err = status == 200, (None if status == 200 else f"HTTP {status}")
    except (requests.RequestException, net.Blocked) as e:
        ok, err = False, str(e)[:120]
    if not ok:
        log.warning("akakce probe failed: %s", err)
    with _lock:
        _state.update(ok=ok, error=err, checked_at=time.time(), running=False)


def unreachable(error):
    """An AkakceError about the network (not about the page): says nothing about the markup."""
    msg = str(error)
    return isinstance(error, akakce_pages.Throttled) or "ulaşılamadı" in msg or "yanıt vermedi" in msg


def _parse_probe():
    """Search a known query and read its first product: both must yield something."""
    ok, err = None, None
    try:
        products = akakce_pages.search(PARSE_QUERY)
        if not products:
            ok, err = False, "arama sonuçları okunamadı"
        else:
            akakce_pages.offers(products[0]["path"])   # raises when no offer can be read
            ok = True
    except akakce_pages.AkakceError as e:
        if not unreachable(e):
            ok, err = False, str(e)[:120]
    except Exception as e:                            # a parser crash is a markup change too
        log.exception("akakce structure check")
        ok, err = False, f"okuma hatası ({type(e).__name__})"
    if ok is False:
        log.warning("akakce structure check failed: %s", err)
    with _lock:
        if ok is not None:                            # offline: keep what we knew
            _parse.update(ok=ok, error=err)
        _parse.update(checked_at=time.time(), running=False)


def report(result):
    """A real search already told us how Akakçe is doing; no need to probe separately."""
    with _lock:
        _state.update(ok=result, error=None if result else "son arama başarısız", checked_at=time.time())


def report_parse(ok, error=None):
    """A real search or price check read (or failed to read) Akakçe's offers."""
    with _lock:
        _parse.update(ok=ok, error=None if ok else str(error)[:120], checked_at=time.time())


def _kick(state, every, retry, target):
    age = time.time() - state["checked_at"]
    if age > (every if state["ok"] else retry) and not state["running"]:
        state["running"] = True
        threading.Thread(target=target, daemon=True).start()


def akakce():
    with _lock:
        _kick(_state, PROBE_EVERY, RETRY_EVERY, _probe)
        # the markup can only be checked while the site answers
        if _state["ok"]:
            _kick(_parse, PARSE_EVERY, PARSE_RETRY, _parse_probe)
        return {"ok": _state["ok"], "error": _state["error"], "parse_ok": _parse["ok"], "parse_error": _parse["error"]}


def summary(sites_list):
    ak = akakce()
    issues = []
    if ak["ok"] is False:
        issues.append("Ana fiyat kaynağı şu an yanıt vermiyor; hızlı arama diğer kaynaklarla devam ediyor")
    elif ak["parse_ok"] is False:
        issues.append(f"Fiyat sayfalarının yapısı değişmiş olabilir: fiyatlar okunamıyor ({ak['parse_error']}). "
                      "Hızlı arama ve fiyat takibi sonuç vermeyebilir; derin arama çalışır.")
    if not providers.ready():
        issues.append("Yapay zekâ sağlayıcısı yok: derin arama kapalı (⚙ Ayarlar)")
    no_logo = [s["name"] for s in sites_list if not s.get("logo")]
    return {"akakce": ak["ok"], "akakce_parse": ak["parse_ok"], "ai_ready": providers.ready(),
            "issues": issues, "sites": len(sites_list), "missing_logos": no_logo}
