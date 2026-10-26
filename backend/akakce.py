"""Quick price comparison from Akakçe (no AI, no tokens).

Akakçe lists a product's offers from many Turkish stores. Two pages are read: the search results
(matching products with their lowest price) and one product page (every store's offer). Akakçe
changes its markup now and then; when nothing can be parsed, AkakceError tells the UI to offer the
deep (Gemini) search instead of showing an empty list."""
import html
import logging
import re
import threading
import time
from urllib.parse import parse_qs, quote_plus, unquote, urlsplit

import requests

from . import net

log = logging.getLogger("commerceos.akakce")

BASE = "https://www.akakce.com"
SEARCH = BASE + "/arama/?q={q}"
PRODUCT_PATH = re.compile(r"^/[a-z0-9\-]+/en-ucuz-[a-z0-9\-]+-fiyati,\d+\.html$")

ITEM = re.compile(r'<li data-pr="(\d+)"[^>]*>(.*?)</li>', re.S)
OFFER_LIST = re.compile(r'<ul id="PL"[^>]*>(.*?)</ul>', re.S)
OFFER = re.compile(r"<li[^>]*>(.*?)</li>", re.S)


class AkakceError(RuntimeError):
    pass


class Throttled(AkakceError):
    """Akakçe answered 429 (too many requests): no request goes out until the pause is over."""


# After a 429 we stay away for a while: every further request (searches, price checks, the health
# probe) would only extend Cloudflare's limit. The pause doubles while 429s keep coming.
PAUSE_FIRST = 5 * 60
PAUSE_MAX = 30 * 60
_pause = {"until": 0.0, "length": 0.0}
_pause_lock = threading.Lock()


def paused_for():
    """Seconds left of the pause after a 429 (0 = Akakçe may be asked)."""
    return max(0.0, _pause["until"] - time.time())


def _throttled_error():
    mins = max(1, round(paused_for() / 60))
    return Throttled(f"Fiyat kaynağı çok sık istek yüzünden kısa süre bekletiyor (yaklaşık {mins} dk)")


def _text(fragment):
    fragment = re.sub(r"<!--.*?-->", "", fragment or "", flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _first(pattern, s, group=1):
    m = re.search(pattern, s, re.S)
    return m.group(group) if m else None


def parse_price(fragment):
    """'12.837<i>,<!-- -->02<!-- --> TL </i>' → 12837.02"""
    t = _text(fragment).replace(" ", "")
    m = re.search(r"(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{1,2}))?TL", t)
    if not m:
        return None
    return float(m.group(1).replace(".", "") + "." + (m.group(2) or "0"))


def _fetch(url):
    if paused_for():
        raise _throttled_error()
    try:
        status, body = net.curl_get(url, connect_timeout=1, max_time=4)
    except (requests.RequestException, net.Blocked) as e:
        log.warning("akakce %s: %s", url, e)
        raise AkakceError("Fiyat kaynağına ulaşılamadı")
    if status == 429:
        with _pause_lock:
            length = min(PAUSE_MAX, _pause["length"] * 2) if _pause["length"] else PAUSE_FIRST
            _pause.update(until=time.time() + length, length=length)
        log.warning("akakce 429: pausing %d min", length // 60)
        raise _throttled_error()
    if status == 200:
        with _pause_lock:
            _pause["length"] = 0.0        # answering again: the next 429 starts with a short pause
    if status != 200:
        raise AkakceError(f"Fiyat kaynağı yanıt vermedi (HTTP {status})")
    return body.decode("utf-8", "replace")


def parse_search(page):
    """Products in the search results, in Akakçe's relevance order."""
    out = []
    for pid, body in ITEM.findall(page):
        name = _first(r'<h3 class="pn_v\d+">(.*?)</h3>', body)
        href = _first(r'<a href="([^"]+)"', body)
        if not name or not href or not PRODUCT_PATH.match(html.unescape(href)):
            continue  # "popular products" blocks and ads use other markup
        count = _first(r"\+(\d+)\s*FİYAT", _text(body))
        out.append({
            "id": pid,
            "name": _text(name),
            "path": html.unescape(href),
            "image": _first(r'<img[^>]+src="(https://[^"]+)"', body),
            "price": parse_price(_first(r'<span class="pt_v\d+">(.*?)</span>\s*</span>', body) or ""),
            "offers": int(count) + 1 if count else 1,
        })
    return out


def _seller_link(href):
    """'#/…&f=%2fr%2f%3fpr%3d1%26vd%3d2%26pg%3d3' → Akakçe's redirect to the store's product page."""
    q = parse_qs(urlsplit(html.unescape(href).lstrip("#")).query)
    target = unquote(q.get("f", [""])[0])
    if target.startswith("/r/?"):
        return BASE + target
    return None


def parse_product(page):
    """Every store's offer on a product page, cheapest first."""
    lst = OFFER_LIST.search(page)
    if not lst:
        return []
    offers = []
    for body in OFFER.findall(lst.group(1)):
        price = parse_price(_first(r'<span class="pt_v\d+ ?">(.*?)</span>', body) or "")
        store = _first(r'<span class="v_v\d+"><img[^>]*alt="([^"]*)"', body)
        if price is None or not store:
            continue
        seller = _first(r'<span class="v_v\d+"><img[^>]*/>\s*/([^<]+)', body)
        stock = _text(_first(r'<span class="stock_v\d+">(.*?)</span>', body) or "")
        rating = _first(r'<span title="(\d+) Yorum" class="r_v\d+[^"]*">([\d,]+)</span>', body, 2)
        reviews = _first(r'<span title="(\d+) Yorum"', body)
        offers.append({
            "store": html.unescape(store).strip(),
            "seller": html.unescape(seller).strip() if seller else None,
            "title": _text(_first(r'<span class="pn_v\d+">(.*?)</span>', body) or ""),
            "price": price,
            "currency": "TL",
            "free_shipping": "Ücretsiz kargo" in body,
            "stock": stock or None,
            "delivery": _text(_first(r'<span class="sd_v\d+"[^>]*>(.*?)</span>', body) or "") or None,
            "url": _seller_link(_first(r'<a href="([^"]+)"', body) or ""),
            "rating": float(rating.replace(",", ".")) if rating else None,   # store rating out of 10
            "reviews": int(reviews) if reviews else None,
        })
    offers.sort(key=lambda o: o["price"])
    return offers


def product_title(page):
    t = _first(r"<h1[^>]*>(.*?)</h1>", page)
    return _text(t) if t else None


def search(query):
    page = _fetch(SEARCH.format(q=quote_plus(query)))
    products = parse_search(page)
    if not products and "data-pr=" not in page:
        log.warning("akakce search: no product markup for %r", query)
    return products


def offers(path):
    if not PRODUCT_PATH.match(path or ""):
        raise AkakceError("Geçersiz ürün")
    page = _fetch(BASE + path)
    found = parse_product(page)
    if not found:
        raise AkakceError("Bu ürün için satıcı fiyatları okunamadı")
    return {"title": product_title(page), "url": BASE + path, "offers": found}
