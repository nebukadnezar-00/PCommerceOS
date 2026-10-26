"""Shopping list compared as "Bölerek al": every product bought where it is cheapest (no tokens).

Items are Akakçe products. Each item keeps the offers last read for it: taken from the search it was
added from (or read once when added), and read again for every item by "Fiyatları güncelle" (one
Akakçe page per product, with a short pause between them). The split is computed from those stored
offers on every view, so it shows as soon as a product is added and follows quantity and scope
changes without any request. Akakçe only says whether shipping is free, not what it costs, so an
order without free shipping is flagged and the total is marked "kargo hariç" — unless the user entered
what that store charges (store_shipping), which is then added to its order."""
import logging
import time

from urllib.parse import urlsplit

from . import akakce, db, health, sites, tracking

log = logging.getLogger("commerceos.cart")

MAX_QTY = 99
GAP_SECONDS = tracking.GAP_SECONDS


class CartError(ValueError):
    pass


# An item can also be one store's offer, picked from a result: its link is the item (a product page
# from the other price sources, or Akakçe's link to that seller), its price is the one the search
# showed (nothing reads it again).
OFFER_HOSTS = ("www.amazon.com.tr", "www.vatanbilgisayar.com", "www.mediamarkt.com.tr")
AKAKCE_OFFER = "/r/"


def is_offer_item(path):
    parts = urlsplit(path or "")
    if parts.scheme != "https" or len(path) > 500:
        return False
    return parts.hostname in OFFER_HOSTS or (parts.hostname == "www.akakce.com" and parts.path == AKAKCE_OFFER)


def _read(path):
    return akakce.offers(path)["offers"]


def items():
    return db.rows("SELECT * FROM cart_items ORDER BY id")


def item_id(path):
    r = db.one("SELECT id FROM cart_items WHERE path=?", (path,))
    return r["id"] if r else None


def _store_offers(iid, offers=None, error=None):
    db.execute("UPDATE cart_items SET offers=?, offers_at=?, offers_error=? WHERE id=?",
               (db.dumps(offers) if offers is not None else None, db.now_iso() if offers is not None else None,
                error, iid))


def _same_product(product):
    """The line already holding this product: picked at one of its stores, or added as the product."""
    if not product:
        return None
    return db.one("SELECT * FROM cart_items WHERE product=? OR path=? ORDER BY id LIMIT 1", (product, product))


def add(path, title, image=None, offers=None, offers_for=_read, product=None):
    """Adds the product or one store's offer of it (with its offers: given, or read once now), or one
    more of it. A product is on the list once: picking another of its stores moves its line there
    (same quantity). Returns (line, the line as it was before it moved, or None)."""
    if not (akakce.PRODUCT_PATH.match(path or "") or is_offer_item(path)):
        raise CartError("Geçersiz ürün")
    if is_offer_item(path) and not offers:
        raise CartError("Bu teklif artık bulunamadı; aramayı yenileyip tekrar ekleyin")
    if product is not None and not akakce.PRODUCT_PATH.match(product):
        raise CartError("Geçersiz ürün")
    existing = item_id(path)
    if existing:
        db.execute("UPDATE cart_items SET qty=MIN(qty + 1, ?) WHERE id=?", (MAX_QTY, existing))
        return db.one("SELECT * FROM cart_items WHERE id=?", (existing,)), None
    image = image if (image or "").startswith("https://") else None
    other = _same_product(product)
    if other:
        if offers is None:
            offers = offers_for(path)
        db.execute("UPDATE cart_items SET path=?, title=?, image=COALESCE(?, image), product=? WHERE id=?",
                   (path, (title or other["title"])[:200], image, product if path != product else None, other["id"]))
        _store_offers(other["id"], offers)
        return db.one("SELECT * FROM cart_items WHERE id=?", (other["id"],)), other
    iid = db.execute("INSERT INTO cart_items(path, title, image, qty, added_at, product) VALUES(?,?,?,1,?,?)",
                     (path, (title or "Ürün")[:200], image, db.now_iso(), product if path != product else None))
    if offers is None:
        try:
            offers = offers_for(path)
        except akakce.AkakceError as e:
            _store_offers(iid, None, str(e))      # stays on the list; "Fiyatları güncelle" tries again
            return db.one("SELECT * FROM cart_items WHERE id=?", (iid,)), None
    _store_offers(iid, offers)
    return db.one("SELECT * FROM cart_items WHERE id=?", (iid,)), None


def set_qty(iid, qty):
    if not 1 <= qty <= MAX_QTY:
        raise CartError(f"Adet 1 ile {MAX_QTY} arasında olmalı")
    db.execute("UPDATE cart_items SET qty=? WHERE id=?", (qty, iid))
    return db.one("SELECT * FROM cart_items WHERE id=?", (iid,))


def remove(iid):
    db.execute("DELETE FROM cart_items WHERE id=?", (iid,))


def clear():
    db.execute("DELETE FROM cart_items")


def _same_offer(old, offers):
    """The picked store's offer on a fresh read of its product page: same link, else same store and seller."""
    for o in offers:
        if o.get("url") == old.get("url"):
            return o
    for o in offers:
        if o.get("store") == old.get("store") and o.get("seller") == old.get("seller"):
            return o
    return None


def refresh(offers_for=_read, only_missing=False):
    """Read every item's Akakçe page again (or only items that have no offers yet). A store's offer
    picked from an Akakçe result is read from its product page; one from the other price sources keeps
    the price it was added with."""
    todo = [it for it in items() if not (only_missing and it["offers"])
            and (not is_offer_item(it["path"]) or it["product"])]
    for i, it in enumerate(todo):
        if i and GAP_SECONDS:
            time.sleep(GAP_SECONDS)
        try:
            if it["product"]:
                old = (db.loads(it["offers"], None) or [None])[0]
                fresh = _same_offer(old, offers_for(it["product"])) if old else None
                if fresh:
                    _store_offers(it["id"], [fresh])
                else:
                    db.execute("UPDATE cart_items SET offers_error=? WHERE id=?", ("Bu satıcı artık listede yok", it["id"]))
                continue
            _store_offers(it["id"], offers_for(it["path"]))
        except akakce.AkakceError as e:
            log.warning("cart %s: %s", it["path"], e)
            if not health.unreachable(e):
                health.report_parse(False, e)
            db.execute("UPDATE cart_items SET offers_error=? WHERE id=?", (str(e), it["id"]))


def shipping_fees():
    return {r["store"]: r for r in db.rows("SELECT * FROM store_shipping")}


def set_shipping(store, fee=None, free_over=None):
    store = (store or "").strip()[:80]
    if not store:
        raise CartError("Mağaza yok")
    for v in (fee, free_over):
        if v is not None and not 0 <= v <= 10000:
            raise CartError("Kargo ücreti 0 ile 10.000 TL arasında olmalı")
    if fee is None and free_over is None:
        db.execute("DELETE FROM store_shipping WHERE store=?", (store,))
    else:
        db.execute("INSERT OR REPLACE INTO store_shipping(store, fee, free_over) VALUES(?,?,?)", (store, fee, free_over))


def _shipping(total, free, cfg):
    """What an order of `total` costs to ship: 0 when free, the store's fee when known, None when not."""
    if free:
        return 0.0
    if not cfg:
        return None
    if cfg["free_over"] is not None and total >= cfg["free_over"]:
        return 0.0
    return cfg["fee"]


def split(scope):
    """Cheapest stored offer per item within `scope` ("all", "mine" or "mine:<group>"), grouped into
    one order per store. No network: reads only what refresh()/add() stored."""
    rows = items()
    if not rows:
        return None
    my = sites.all_sites()
    allowed = {s["id"] for s in sites.scope_sites(scope, my)}
    picks, missing = [], []
    by_store = {}   # store → {item id: its cheapest offer there}: for the "one store" totals
    for it in rows:
        offers = db.loads(it["offers"], None)
        if offers is None:
            missing.append({"id": it["id"], "title": it["title"], "reason": it["offers_error"] or "Fiyat henüz okunmadı"})
            continue
        best = None
        for o in offers:
            site = sites.match_site(o["store"], my)
            if scope != "all" and not (site and site["id"] in allowed):
                continue
            if best is None or o["price"] < best[0]["price"]:
                best = (o, site)
            store = by_store.setdefault(site["name"] if site else o["store"], {"site_id": site["id"] if site else None, "items": {}})
            prev = store["items"].get(it["id"])
            if prev is None or o["price"] < prev["price"]:
                store["items"][it["id"]] = o
        if not best:
            missing.append({"id": it["id"], "title": it["title"],
                            "reason": "Seçili mağazalarda teklif yok" if scope != "all" else "Teklif bulunamadı"})
            continue
        o, site = best
        picks.append({"id": it["id"], "title": it["title"], "image": it["image"], "qty": it["qty"],
                      "store": site["name"] if site else o["store"], "site_id": site["id"] if site else None,
                      "seller": o.get("seller"), "price": o["price"], "subtotal": round(o["price"] * it["qty"], 2),
                      "free_shipping": bool(o.get("free_shipping")), "url": o.get("url")})

    orders = {}
    for p in picks:
        order = orders.setdefault(p["store"], {"store": p["store"], "site_id": p["site_id"], "items": [],
                                               "total": 0.0, "free_shipping": True})
        order["items"].append(p)
        order["total"] = round(order["total"] + p["subtotal"], 2)
        order["free_shipping"] = order["free_shipping"] and p["free_shipping"]
    fees = shipping_fees()
    for o in orders.values():
        o["shipping"] = _shipping(o["total"], o["free_shipping"], fees.get(o["store"]))
        o["shipping_set"] = o["store"] in fees
        o["grand"] = round(o["total"] + (o["shipping"] or 0), 2)
    read = [it["offers_at"] for it in rows if it["offers_at"]]
    priced = {p["id"]: p for p in picks}
    total = round(sum(o["grand"] for o in orders.values()), 2)
    single = _single_store(by_store, priced, total, fees)
    return {"single": single, "scope": scope, "checked_at": min(read) if read else None, "items": picks,
            "orders": sorted(orders.values(), key=lambda o: -o["grand"]),
            "total": total, "missing": missing,
            "shipping_unknown": any(o["shipping"] is None for o in orders.values())}


def _single_store(by_store, priced, split_total, fees=None, limit=3):
    """Whole list from one store, for comparison with the split: stores that have every priced item,
    cheapest first, with the extra cost over the split. If no store has them all, the store that has
    the most of them (with what is missing)."""
    need = set(priced)
    if not need:
        return {"full": [], "best_partial": None}
    out = []
    for name, s in by_store.items():
        have = need & set(s["items"])
        goods = round(sum(s["items"][i]["price"] * priced[i]["qty"] for i in have), 2)
        free = all(s["items"][i].get("free_shipping") for i in have)
        ship = _shipping(goods, free, (fees or {}).get(name))
        total = round(goods + (ship or 0), 2)
        out.append({"store": name, "site_id": s["site_id"], "count": len(have), "of": len(need), "total": total,
                    "extra": round(total - split_total, 2) if have == need else None,
                    "free_shipping": free, "shipping": ship,
                    "missing": [priced[i]["title"] for i in need - have]})
    full = sorted((o for o in out if o["count"] == len(need)), key=lambda o: o["total"])[:limit]
    partial = None
    if not full and len(need) > 1:
        partial = max(out, key=lambda o: (o["count"], -o["total"]), default=None)
    return {"full": full, "best_partial": partial}
