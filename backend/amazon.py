"""Backup source for the quick search: Amazon TR's own search page (no AI, no tokens).

Used only when Akakçe cannot be reached. Price comparison sites other than Akakçe (Cimri, Epey) and
most stores block automated requests; Amazon TR answers macOS curl. It is one store, and its
results mix in accessories, so results are kept only when their title contains every word of the
query and no accessory word ("uyumlu", "kılıf", ...) the query did not ask for, in Amazon's own
relevance order."""
import html
import logging
import re
import unicodedata
from urllib.parse import quote_plus

import requests

from . import net

log = logging.getLogger("commerceos.amazon")

BASE = "https://www.amazon.com.tr"
SEARCH = BASE + "/s?k={q}"
STORE = "Amazon TR"
RESULT = re.compile(r'(?=<div[^>]*data-component-type="s-search-result")')
MAX_RESULTS = 12
# titles that sell something *for* the product (cases, tips, cables) rather than the product itself
ACCESSORY = {"uyumlu", "icin", "kilif", "kilifi", "kapak", "kapagi", "koruyucu", "yedek", "uclari", "ucu",
             "silikon", "kablo", "kablosu", "adaptor", "aparat", "sticker", "kordon", "stand", "tutucu"}


class AmazonError(RuntimeError):
    pass


def _fold(s):
    s = (s or "").replace("İ", "i").replace("ı", "i")
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def _words(s):
    return [w for w in re.findall(r"[a-z0-9]+", _fold(s)) if w]


def _price(text):
    """'11.349,00 TL' → 11349.0"""
    m = re.search(r"(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{1,2}))?\s*TL", text or "")
    return float(m.group(1).replace(".", "") + "." + (m.group(2) or "0")) if m else None


def _title(part):
    """The product's name. Since October 2026 a result has two headings: the brand ("adidas") and
    the name without it ("Samba Og Erkek Günlük Spor Ayakkabı"); older pages had one full heading."""
    heads = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", h))).strip()
             for h in re.findall(r"<h2[^>]*>(.*?)</h2>", part, re.S)]
    heads = [h for h in heads if h]
    if not heads:
        return None
    name = heads[-1]
    if len(heads) > 1 and _fold(heads[0]) not in _fold(name):
        name = f"{heads[0]} {name}"
    return name


def matches(title, query):
    """Every word of the query in the title, and no accessory word the query did not ask for."""
    want, have = _words(query), set(_words(title))
    return all(w in have for w in want) and not (have & ACCESSORY) - set(want)


def parse(page, query):
    want = _words(query)
    out = []
    for part in RESULT.split(page)[1:]:
        asin = re.search(r'data-asin="([A-Z0-9]{10})"', part)
        name = _title(part)
        price = re.search(r'class="a-offscreen">([^<]+)<', part)
        if not (asin and name and price):
            continue
        value = _price(html.unescape(price.group(1)))
        have = set(_words(name))
        if not value or not all(w in have for w in want):
            continue
        if (have & ACCESSORY) - set(want):
            continue
        img = re.search(r'class="s-image"[^>]*src="(https://[^"]+)"', part)
        out.append({"store": STORE, "seller": None, "title": name[:200], "price": value, "currency": "TL",
                    "free_shipping": "Ücretsiz Kargo" in part or "ÜCRETSİZ kargo" in part,
                    "stock": None, "delivery": None, "url": f"{BASE}/dp/{asin.group(1)}",
                    "image": img.group(1) if img else None, "rating": None, "reviews": None})
        if len(out) >= MAX_RESULTS:
            break
    return out


def search(query):
    try:
        status, body = net.curl_get(SEARCH.format(q=quote_plus(query)), connect_timeout=1, max_time=5)
    except (requests.RequestException, net.Blocked) as e:
        log.warning("amazon search: %s", e)
        raise AmazonError("Amazon TR'ye de ulaşılamadı")
    if status != 200:
        raise AmazonError(f"Amazon TR yanıt vermedi (HTTP {status})")
    return parse(body.decode("utf-8", "replace"), query)
