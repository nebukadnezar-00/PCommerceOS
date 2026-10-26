"""Third source for the quick search: the search pages of stores that answer a plain request
(Vatan, MediaMarkt; no AI, no tokens). Both sell electronics only, so for other products they
simply find nothing. Results go through the same filter as the Amazon backup: every query word in
the title, no accessory the query did not ask for."""
import html
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, quote_plus, urljoin

import requests

from . import amazon, net

log = logging.getLogger("commerceos.stores")

MAX_RESULTS = 12


def _offer(store, title, price, url, image=None):
    return {"store": store, "seller": None, "title": title[:200], "price": price, "currency": "TL",
            "free_shipping": False, "stock": None, "delivery": None, "url": url, "image": image,
            "rating": None, "reviews": None}


def _price(text):
    """'8.999' / '8.999,90' → 8999.0 / 8999.9"""
    m = re.search(r"(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{1,2}))?", text or "")
    return float(m.group(1).replace(".", "") + "." + (m.group(2) or "0")) if m else None


# ---------------------------------------------------------------- Vatan

VATAN = "https://www.vatanbilgisayar.com"
VATAN_SEARCH = VATAN + "/arama/{q}/"
VATAN_CARD = re.compile(r'<div class="product-list product-list--list-page">(.*?)'
                        r'(?=<div class="product-list product-list--list-page">|\Z)', re.S)


def parse_vatan(page, query):
    out = []
    for card in VATAN_CARD.findall(page):
        link = re.search(r'class="product-list-link" href="(https://www\.vatanbilgisayar\.com/[^"]+)"', card)
        name = re.search(r'class="product-list__product-name">\s*<h3>(.*?)</h3>', card, re.S)
        price = re.search(r"class='product-list__price'>([^<]+)<", card) or \
            re.search(r'class="product-list__price">([^<]+)<', card)
        if not (link and name and price):
            continue
        title = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", name.group(1)))).strip()
        value = _price(price.group(1))
        if value and amazon.matches(title, query):
            img = re.search(r'data-src="(https://cdn\.vatanbilgisayar\.com/[^"]+)"', card)
            out.append(_offer("Vatan Bilgisayar", title, value, link.group(1), img.group(1) if img else None))
    return out[:MAX_RESULTS]


# ---------------------------------------------------------------- MediaMarkt

MEDIAMARKT = "https://www.mediamarkt.com.tr"
MEDIAMARKT_SEARCH = MEDIAMARKT + "/tr/search.html?query={q}"


def parse_mediamarkt(page, query):
    """MediaMarkt lists its results as schema.org JSON in the page head."""
    out = []
    for block in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        if not isinstance(data, dict) or data.get("@type") != "ItemList":
            continue
        for el in data.get("itemListElement") or []:
            item = (el or {}).get("item") or {}
            title = re.sub(r"\s+", " ", str(item.get("name") or "")).strip()
            try:
                value = float((item.get("offers") or {}).get("price"))
            except (TypeError, ValueError):
                continue
            url = urljoin(MEDIAMARKT, str(item.get("url") or ""))
            if title and value > 0 and url.startswith(MEDIAMARKT + "/") and amazon.matches(title, query):
                image = item.get("image") if str(item.get("image") or "").startswith("https://") else None
                out.append(_offer("MediaMarkt", title, value, url, image))
    return out[:MAX_RESULTS]


# ---------------------------------------------------------------- both

SOURCES = (
    ("Vatan", lambda q: VATAN_SEARCH.format(q=quote(q)), parse_vatan),
    ("MediaMarkt", lambda q: MEDIAMARKT_SEARCH.format(q=quote_plus(q)), parse_mediamarkt),
)


def _one(name, url, parse, query):
    try:
        status, body = net.curl_get(url, connect_timeout=1, max_time=4)
    except (requests.RequestException, net.Blocked) as e:
        log.warning("%s search: %s", name, e)
        return []
    if status != 200:
        log.warning("%s search: HTTP %s", name, status)
        return []
    try:
        return parse(body.decode("utf-8", "replace"), query)
    except Exception:
        log.exception("%s search could not be read", name)
        return []


def search(query):
    """Both stores at once; their offers together, cheapest first. Never raises: a store that does
    not answer just adds nothing."""
    with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
        jobs = [pool.submit(_one, name, url(query), parse, query) for name, url, parse in SOURCES]
        offers = [o for j in jobs for o in j.result()]
    return sorted(offers, key=lambda o: o["price"])
