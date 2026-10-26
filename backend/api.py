"""HTTP API: stores, quick (Akakçe) and deep (Gemini) search, search history."""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import ai, akakce, amazon, backup, cart, config, db, health, net, orders, pricing, providers, scheduler, sites, stores, tracking, usage

log = logging.getLogger("commerceos.api")

router = APIRouter()

def _query(q):
    q = re.sub(r"\s+", " ", (q or "").strip())
    if not 2 <= len(q) <= 120:
        raise HTTPException(400, "Aranacak ürünü yazın (2-120 karakter)")
    return q


def _scope(s):
    """"all", "mine" (every store of mine) or "mine:<group id>" (one group of my stores)."""
    if not sites.SCOPE_RE.match(s or ""):
        raise HTTPException(400, "Geçersiz kapsam")
    if s.startswith("mine:") and not sites.get_group(int(s[5:])):
        raise HTTPException(400, "Grup bulunamadı")
    return s


def _track_scope(s):
    """Price tracking counts all my stores or every store; a group search tracks as "mine"."""
    s = _scope(s)
    return "mine" if s.startswith("mine") else s


# ---------------------------------------------------------------- status

@router.get("/api/status")
def status():
    return {"ok": True, "ai_ready": providers.ready(),
            "ai": [{"provider": providers.PROVIDERS[p]["name"], "model": m} for p, m, _ in providers.chain()],
            "month": ai.tokens_this_month(), "health": health.summary(sites.all_sites()),
            "tracking": dict(tracking.run_state(), next_check=scheduler.next_check(),
                             items=db.one("SELECT COUNT(*) AS n FROM tracked")["n"]),
            "alerts_unseen": tracking.unseen_count(), "backup_warning": backup.warning(),
            "orders": orders.state()}


# ---------------------------------------------------------------- Rehber (first-run guide)

GUIDE_STEPS = ("sites", "ai", "search", "track", "mail")


def _guide_state():
    return db.loads(db.get_meta("guide"), {}) or {}


def _guide_mark(step):
    g = _guide_state()
    if step not in g.get("done", []):
        g["done"] = [*g.get("done", []), step]
        db.set_meta("guide", db.dumps(g))


class GuideIn(BaseModel):
    seen: Optional[bool] = None
    done: Optional[str] = None           # a step finished by hand ("sites": the hint's "Tamam")


@router.get("/api/guide")
def guide():
    """Which steps of the guide are done: read from what the user has actually set up or used."""
    g = _guide_state()
    one = lambda sql: db.one(sql)["n"] > 0
    done = {"sites": "sites" in g.get("done", []),
            "ai": providers.ready(),
            "search": one("SELECT COUNT(*) AS n FROM searches"),
            "track": one("SELECT COUNT(*) AS n FROM tracked") or one("SELECT COUNT(*) AS n FROM cart_items"),
            "mail": orders.mailbox.configured()}
    return {"steps": [{"id": k, "done": bool(done[k])} for k in GUIDE_STEPS],
            "seen": bool(g.get("seen"))}


@router.put("/api/guide")
def guide_update(body: GuideIn):
    g = _guide_state()
    if body.seen is not None:
        g["seen"] = body.seen
    if body.done:
        if body.done not in GUIDE_STEPS:
            raise HTTPException(400, "Bilinmeyen adım")
        g["done"] = sorted({*g.get("done", []), body.done})
    db.set_meta("guide", db.dumps(g))
    return guide()


@router.get("/api/glance")
def glance():
    """A one-line summary for a dashboard or widget (no network, no tokens)."""
    latest = db.one("SELECT title, new_price, store, kind, created_at FROM alerts WHERE seen=0 ORDER BY id DESC LIMIT 1")
    return {"tracked": db.one("SELECT COUNT(*) AS n FROM tracked")["n"],
            "alerts_unseen": tracking.unseen_count(), "latest_alert": latest,
            "orders_open": orders.open_count()}


# ---------------------------------------------------------------- stores

def _public(s):
    p = sites.logo_path(s)
    return {"id": s["id"], "name": s["name"], "url": s["url"], "domain": s["domain"], "group_id": s.get("group_id"),
            "position": s.get("position"),
            "search_url": s["search_url"] or sites.GOOGLE_SITE_SEARCH.format(domain=s["domain"]),
            "own_search": bool(s["search_url"]),
            "logo": f"/api/sites/{s['id']}/logo?v={int(p.stat().st_mtime)}" if p else None}


def _site_or_404(site_id):
    s = sites.get(site_id)
    if not s:
        raise HTTPException(404, "Site bulunamadı")
    return s


class SiteIn(BaseModel):
    url: str
    group_id: Optional[int] = None


class SiteName(BaseModel):
    name: str


class Order(BaseModel):
    ids: List[int]


class SiteOrder(BaseModel):
    """The complete new order of one group's stores; `group_id` None = "Diğer"."""
    ids: List[int]
    group_id: Optional[int] = None
    regroup: bool = False   # False: old clients that only reorder, keep every store's group


@router.get("/api/sites")
def list_sites():
    return [_public(s) for s in sites.all_sites()]


@router.post("/api/sites")
def add_site(body: SiteIn):
    try:
        site = _public(sites.add(body.url, body.group_id))
    except (sites.SiteError, net.Blocked) as e:
        raise HTTPException(400, str(e))
    _guide_mark("sites")
    return site


@router.patch("/api/sites/{site_id}")
def rename_site(site_id: int, body: SiteName):
    _site_or_404(site_id)
    try:
        return _public(sites.rename(site_id, body.name))
    except sites.SiteError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/sites/{site_id}")
def delete_site(site_id: int):
    if not sites.remove(site_id):
        raise HTTPException(404, "Site bulunamadı")
    _guide_mark("sites")
    return {"ok": True}


@router.put("/api/sites/order")
def order_sites(body: SiteOrder):
    _guide_mark("sites")
    if not body.regroup:
        sites.reorder(body.ids)
        return {"ok": True}
    try:
        sites.move(body.ids, body.group_id)
    except sites.SiteError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.post("/api/sites/{site_id}/logo")
def refresh_logo(site_id: int):
    _site_or_404(site_id)
    s = sites.refresh_logo(site_id)
    if not sites.logo_path(s):
        raise HTTPException(502, "Logo alınamadı")
    return _public(s)


@router.get("/api/sites/{site_id}/logo")
def site_logo(site_id: int):
    p = sites.logo_path(_site_or_404(site_id))
    if not p:
        raise HTTPException(404, "Logo yok")
    # the ?v= in the URL changes with the file, so the browser may keep it
    return FileResponse(p, media_type=sites.logo_type(p), headers={"Cache-Control": "max-age=2592000"})


# ---------------------------------------------------------------- search

def _cached(query, kind, product="", scope=None, hours=1.0):
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="seconds")
    sql = "SELECT * FROM searches WHERE query=? COLLATE NOCASE AND kind=? AND product=? AND created_at>=?"
    params = [query, kind, product, since]
    if scope:
        sql += " AND scope=?"
        params.append(scope)
    return db.one(sql + " ORDER BY id DESC LIMIT 1", params)


def _save(query, scope, kind, product, result, tokens=0):
    return db.execute("INSERT INTO searches(query, scope, kind, product, result, tokens, created_at) "
                      "VALUES(?,?,?,?,?,?,?)", (query, scope, kind, product, db.dumps(result), tokens, db.now_iso()))


def _present(row, scope=None):
    """A stored search as the UI shows it, with offers tied to the user's stores *now*
    (stores may have been added or removed since) and the scope filter applied."""
    res = db.loads(row["result"], {})
    scope = scope or row["scope"]
    my = sites.all_sites()
    in_scope = {s["id"] for s in sites.scope_sites(scope, my)}
    offers = []
    for o in res.get("offers") or []:
        s = sites.match_site(o["store"], my)
        o = dict(o, site_id=s["id"] if s else None)
        if scope == "all" or (s and s["id"] in in_scope):
            offers.append(o)
    tracked = in_cart = None
    check = None
    if row["kind"] == "quick" and res.get("product") and res.get("offers"):
        check = _price_check(res["product"]["path"], min(o["price"] for o in res["offers"]), row["created_at"])
    if row["kind"] == "quick" and res.get("product"):
        tracked = tracking.tracked_paths().get((res["product"]["path"], "mine" if scope.startswith("mine") else scope))
        in_cart = cart.item_id(res["product"]["path"])
    return dict(res, offers=offers, total_offers=len(res.get("offers") or []), id=row["id"], tracked_id=tracked, cart_id=in_cart,
                price_check=check,
                query=row["query"], scope=scope, kind=row["kind"], tokens=row["tokens"],
                created_at=row["created_at"])


PRICE_CHECK_DAYS = 30


def _price_check(path, current, at):
    """'Is this a good price?' from what we already know about the product in the last 30 days: the
    cheapest offer of every earlier search of it and its tracked checks (no request). None until
    there are prices from at least two days."""
    since = (datetime.fromisoformat(at) - timedelta(days=PRICE_CHECK_DAYS)).isoformat(timespec="seconds")
    points = []                                       # (day, lowest price)
    for r in db.rows("SELECT result, created_at FROM searches WHERE kind='quick' AND created_at>=? AND created_at<=? "
                     "AND result LIKE ?", (since, at, f'%"{path}"%')):
        d = db.loads(r["result"], {})
        if (d.get("product") or {}).get("path") == path and d.get("offers"):
            points.append((r["created_at"][:10], min(o["price"] for o in d["offers"])))
    for r in db.rows("SELECT h.price, h.checked_at FROM price_history h JOIN tracked t ON t.id = h.tracked_id "
                     "WHERE t.path=? AND t.scope='all' AND h.checked_at>=? AND h.checked_at<=?", (path, since, at)):
        points.append((r["checked_at"][:10], r["price"]))
    days = {}
    for day, price in points:
        days[day] = min(price, days.get(day, price))
    if len(days) < 2:
        return None
    low, avg = min(days.values()), sum(days.values()) / len(days)
    pct = round((current / avg - 1) * 100)
    if current <= low * 1.005:
        verdict = "lowest"
    elif pct <= -3:
        verdict = "below"
    elif pct >= 3:
        verdict = "above"
    else:
        verdict = "typical"
    span = (datetime.fromisoformat(at).date() - datetime.fromisoformat(min(days)).date()).days + 1
    return {"verdict": verdict, "pct": pct, "low": round(low, 2), "avg": round(avg, 2), "days": span,
            "points": len(days), "since": min(days)}


@router.get("/api/search")
def quick_search(q: str, scope: str = "all", product: str = "", refresh: bool = False):
    """Akakçe, no tokens. Without `product` the best match's offers are loaded; `product` (a path
    from the returned list) switches to another product of the same search."""
    q, scope = _query(q), _scope(scope)
    if product and not akakce.PRODUCT_PATH.match(product):
        raise HTTPException(400, "Geçersiz ürün")
    if not refresh:
        row = _cached(q, "quick", product, hours=config.QUICK_CACHE_HOURS)
        # an answer from the backup source is not reused: Akakçe may be back by now
        if row and (not db.loads(row["result"], {}).get("source") or akakce.paused_for()):
            return dict(_present(row, scope), from_cache=True)
    try:
        if product:
            base = _cached(q, "quick", "", hours=24 * 7)
            products = db.loads(base["result"], {}).get("products", []) if base else akakce.search(q)
        else:
            products = akakce.search(q)
        if not products and not product:
            health.report(True)
            return _backup_source(q, scope, "Akakçe'de bu aramayla ürün bulunamadı")
        path = product or products[0]["path"]
        detail = akakce.offers(path)
    except akakce.AkakceError as e:
        if health.unreachable(e):
            health.report(False)
            if not product:
                return _backup_source(q, scope, f"{e}")
        else:
            health.report_parse(False, e)       # the page came but its offers could not be read
        raise HTTPException(502, f"{e}. Derin arama deneyebilirsiniz.")
    health.report(True)
    health.report_parse(True)
    result = {"products": products[:12], "product": {"path": path, "title": detail["title"], "url": detail["url"]},
              "offers": detail["offers"]}
    rid = _save(q, scope, "quick", product, result)
    return dict(_present(db.one("SELECT * FROM searches WHERE id=?", (rid,)), scope), from_cache=False)


def _backup_source(q, scope, reason):
    """The first source could not help: Amazon TR's search, then the stores that answer a plain
    request (Vatan, MediaMarkt) — each gives up within seconds. No tokens. The UI names none of
    them; `reason` is kept for the log. Nothing anywhere is still an answer, so the page can offer
    the deep search."""
    log.info("quick search %r: %s; trying the other sources", q, reason)
    found, source = [], None
    try:
        found, source = amazon.search(q), "amazon"
    except amazon.AmazonError as e:
        log.warning("quick search %r: %s", q, e)
    if not found:
        found, source = stores.search(q), "stores"
    if not found:
        return {"query": q, "scope": scope, "kind": "quick", "products": [], "offers": [],
                "total_offers": 0, "empty": True}
    found.sort(key=lambda o: o["price"])
    result = {"products": [], "product": None, "offers": found, "source": source, "fallback_reason": reason}
    rid = _save(q, scope, "quick", "", result)
    return dict(_present(db.one("SELECT * FROM searches WHERE id=?", (rid,)), scope), from_cache=False)


class DeepIn(BaseModel):
    q: str
    scope: str = "all"
    refresh: bool = False


@router.post("/api/search/deep")
def deep_search(body: DeepIn):
    """Gemini + Google Search: spends tokens, so a recent identical search is reused."""
    q, scope = _query(body.q), _scope(body.scope)
    if not body.refresh:
        row = _cached(q, "deep", scope=scope, hours=config.DEEP_CACHE_HOURS)
        if row:
            return dict(_present(row), from_cache=True)
    my = sites.all_sites() if scope == "all" else sites.scope_sites(scope)
    if scope != "all" and not my:
        raise HTTPException(400, "Bu kapsamda site yok: önce site ekleyin")
    try:
        res = ai.deep_search(q, scope, my)
    except ai.AIUnavailable as e:
        raise HTTPException(503, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    tokens = res.pop("tokens")
    rid = _save(q, scope, "deep", "", res, tokens)
    return dict(_present(db.one("SELECT * FROM searches WHERE id=?", (rid,))), from_cache=False)


# ---------------------------------------------------------------- history

@router.get("/api/history")
def history(limit: int = 50):
    out = []
    for r in db.rows("SELECT * FROM searches WHERE product='' ORDER BY id DESC LIMIT ?", (min(limit, 200),)):
        res = db.loads(r["result"], {})
        prices = [o["price"] for o in res.get("offers") or []]
        out.append({"id": r["id"], "query": r["query"], "scope": r["scope"], "kind": r["kind"],
                    "tokens": r["tokens"], "created_at": r["created_at"], "offers": len(prices),
                    "min_price": min(prices) if prices else None,
                    "title": (res.get("product") or {}).get("title")})
    return out


@router.get("/api/history/{search_id}")
def history_item(search_id: int, scope: str = ""):
    """A stored search; with `scope`, filtered for that set of stores (no new request: the page uses
    this when the user switches between all stores and theirs)."""
    row = db.one("SELECT * FROM searches WHERE id=?", (search_id,))
    if not row:
        raise HTTPException(404, "Arama bulunamadı")
    return dict(_present(row, _scope(scope) if scope else None), from_cache=True)


@router.delete("/api/history/{search_id}")
def delete_history_item(search_id: int):
    row = db.one("SELECT query, kind FROM searches WHERE id=?", (search_id,))
    if row:
        # product switches of a quick search go with it
        if row["kind"] == "quick":
            db.execute("DELETE FROM searches WHERE kind='quick' AND query=? COLLATE NOCASE AND product<>''",
                       (row["query"],))
        db.execute("DELETE FROM searches WHERE id=?", (search_id,))
    return {"ok": True}


@router.delete("/api/history")
def clear_history():
    db.execute("DELETE FROM searches")
    return {"ok": True}


# ---------------------------------------------------------------- price tracking

class TrackIn(BaseModel):
    path: str
    title: str
    image: Optional[str] = None
    scope: str = "all"
    target_price: Optional[float] = None


class TrackPatch(BaseModel):
    target_price: Optional[float] = None
    clear_target: bool = False
    scope: Optional[str] = None


@router.get("/api/tracked")
def tracked_list():
    return tracking.all_items()


@router.post("/api/tracked")
def track(body: TrackIn):
    if body.image and not body.image.startswith("https://"):
        body.image = None
    # the offers were just read for the search: reuse them for the first price, no extra request
    row = _cached_product(body.path)
    offers = db.loads(row["result"], {}).get("offers") if row else None
    try:
        return tracking.add(body.path, body.title, body.image, _track_scope(body.scope), body.target_price, offers=offers)
    except tracking.TrackError as e:
        raise HTTPException(400, str(e))


def _cached_offer(url):
    """The offer with this product URL in a recent quick search (the other price sources)."""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec="seconds")
    for r in db.rows("SELECT * FROM searches WHERE kind='quick' AND created_at>=? ORDER BY id DESC LIMIT 50", (since,)):
        for o in db.loads(r["result"], {}).get("offers") or []:
            if o.get("url") == url:
                return o
    return None


def _cached_product(path):
    since = (datetime.now(timezone.utc) - timedelta(hours=config.QUICK_CACHE_HOURS)).isoformat(timespec="seconds")
    for r in db.rows("SELECT * FROM searches WHERE kind='quick' AND created_at>=? ORDER BY id DESC LIMIT 20", (since,)):
        if (db.loads(r["result"], {}).get("product") or {}).get("path") == path:
            return r
    return None


@router.patch("/api/tracked/{item_id}")
def track_update(item_id: int, body: TrackPatch):
    try:
        target = None if body.clear_target else (body.target_price if body.target_price is not None else ...)
        item = tracking.update(item_id, target_price=target, scope=_track_scope(body.scope) if body.scope else None)
    except tracking.TrackError as e:
        raise HTTPException(400, str(e))
    if not item:
        raise HTTPException(404, "Takip bulunamadı")
    return item


@router.delete("/api/tracked/{item_id}")
def track_delete(item_id: int):
    tracking.remove(item_id)
    return {"ok": True}


@router.post("/api/tracked/check")
def track_check_all():
    if not db.one("SELECT id FROM tracked LIMIT 1"):
        raise HTTPException(400, "Takipte ürün yok")
    if not tracking.start_check_all("manual"):
        raise HTTPException(409, "Kontrol zaten sürüyor")
    return {"ok": True}


@router.post("/api/tracked/{item_id}/check")
def track_check_one(item_id: int):
    try:
        row = tracking.check(item_id)
    except akakce.AkakceError as e:
        raise HTTPException(502, str(e))
    if not row:
        raise HTTPException(404, "Takip bulunamadı")
    return tracking.get(item_id)


@router.get("/api/alerts")
def alert_list():
    return {"unseen": tracking.unseen_count(), "items": tracking.alerts()}


@router.post("/api/alerts/seen")
def alerts_seen():
    tracking.mark_seen()
    return {"ok": True}


# ---------------------------------------------------------------- AI usage and cost (⚙ Ayarlar)

@router.get("/api/usage")
def usage_summary(period: str = "month"):
    if period not in usage.PERIODS:
        raise HTTPException(400, "Geçersiz dönem")
    return usage.summary(period)


class UsageSettings(BaseModel):
    prices: Optional[dict] = None    # {model: [input, output] USD per 1M tokens | None}


@router.put("/api/usage/settings")
def usage_settings(body: UsageSettings, request: Request):
    if not providers.is_local(request):
        raise HTTPException(403, "Ayarlar yalnızca uygulamanın çalıştığı bilgisayardan değiştirilebilir")
    try:
        if body.prices is not None:
            pricing.set_custom(body.prices)
    except (ValueError, TypeError, IndexError) as e:
        raise HTTPException(400, str(e) or "Geçersiz değer")
    return usage.summary("month")


# ---------------------------------------------------------------- mail connection (⚙ Ayarlar → E-posta)

class MailIn(BaseModel):
    user: str
    password: str


def _mail_state(request):
    configured = orders.mailbox.configured()
    return {"configured": configured, "user": orders.mailbox.mask(orders.mailbox.account()) if configured else "",
            "last_scan": db.get_meta("orders_last_scan"), "editable": providers.is_local(request)}


def _mail_local(request):
    if not providers.is_local(request):
        raise HTTPException(403, "E-posta bağlantısı yalnızca uygulamanın çalıştığı bilgisayardan değiştirilebilir")


@router.get("/api/settings/mail")
def mail_get(request: Request):
    return _mail_state(request)


@router.post("/api/settings/mail/test")
def mail_test(body: MailIn, request: Request):
    _mail_local(request)
    try:
        return {"ok": True, "message": orders.mailbox.test(body.user, body.password)}
    except orders.mailbox.MailError as e:
        return {"ok": False, "message": str(e)}


@router.put("/api/settings/mail")
def mail_save(body: MailIn, request: Request):
    _mail_local(request)
    try:
        message = orders.mailbox.save(body.user, body.password)
    except orders.mailbox.MailError as e:
        raise HTTPException(400, str(e))
    orders.start_scan("setup")
    return dict(_mail_state(request), message=message)


@router.delete("/api/settings/mail")
def mail_remove(request: Request):
    _mail_local(request)
    orders.mailbox.remove()
    return _mail_state(request)


# ---------------------------------------------------------------- orders (from the stores' emails)

class OrderPatch(BaseModel):
    delivered: Optional[bool] = None    # false reopens an order marked delivered by hand
    hidden: Optional[bool] = None


@router.get("/api/orders")
def order_list():
    return {"state": orders.state(), "items": orders.all_orders(), "archive": orders.archived()}


@router.post("/api/orders/scan")
def order_scan():
    if not orders.mailbox.configured():
        raise HTTPException(400, "E-posta bağlantısı kurulmadı")
    if not orders.start_scan("manual"):
        raise HTTPException(409, "Tarama zaten sürüyor")
    return {"ok": True}


@router.patch("/api/orders/{order_id}")
def order_update(order_id: int, body: OrderPatch):
    o = orders.update(order_id, delivered=body.delivered, hidden=body.hidden)
    if not o:
        raise HTTPException(404, "Sipariş bulunamadı")
    return o


# ---------------------------------------------------------------- shipping fees per store

class ShippingIn(BaseModel):
    store: str
    fee: Optional[float] = None
    free_over: Optional[float] = None


@router.put("/api/shipping")
def shipping_set(body: ShippingIn, scope: str = "all"):
    """What a store charges for shipping (both empty: forget it); answers with the cart, re-split."""
    try:
        cart.set_shipping(body.store, body.fee, body.free_over)
    except cart.CartError as e:
        raise HTTPException(400, str(e))
    return _cart_state(scope)


# ---------------------------------------------------------------- shopping list ("Bölerek al")

class CartIn(BaseModel):
    path: str
    title: str
    image: Optional[str] = None
    product: Optional[str] = None   # the result's product, when a store's offer of it is picked


class CartQty(BaseModel):
    qty: int


class CompareIn(BaseModel):
    scope: str = "all"


def _cart_state(scope="all"):
    """The list with each item's cheapest known price, and the split for `scope` (no network)."""
    scope = _scope(scope)
    items = cart.items()
    for it in items:
        offers = db.loads(it.pop("offers"), None)
        best = min(offers, key=lambda o: o["price"]) if offers else None
        it["last_price"], it["last_store"] = (best["price"], best["store"]) if best else (None, None)
    fees = {k: {"fee": v["fee"], "free_over": v["free_over"]} for k, v in cart.shipping_fees().items()}
    return {"items": items, "result": cart.split(scope), "shipping": fees}


def _product_image(path):
    """The product's picture from the searches that showed it (Akakçe offers carry none of their own)."""
    for r in db.rows("SELECT result FROM searches WHERE kind='quick' AND result LIKE ? ORDER BY id DESC LIMIT 5",
                     ("%" + path + "%",)):
        for p in db.loads(r["result"], {}).get("products") or []:
            if p.get("path") == path and str(p.get("image") or "").startswith("https://"):
                return p["image"]
    return None


def _fill_images():
    """Lines picked at one store before pictures were passed along get their product's picture."""
    for it in cart.items():
        if not it["image"] and it["product"]:
            image = _product_image(it["product"])
            if image:
                db.execute("UPDATE cart_items SET image=? WHERE id=?", (image, it["id"]))


@router.get("/api/cart")
def cart_get(scope: str = "all"):
    _fill_images()
    # items added before offers were stored (or whose first read failed) get read once here
    if any(not it["offers"] and not it["offers_error"] for it in cart.items()):
        cart.refresh(only_missing=True)
    return _cart_state(scope)


@router.post("/api/cart")
def cart_add(body: CartIn, scope: str = "all"):
    # the offers were just read for the search the product was added from: no extra request
    if cart.is_offer_item(body.path):
        # one store's offer from a search: its price comes from that search, never from the page
        offer = _cached_offer(body.path)
        offers = [offer] if offer else None
    else:
        row = _cached_product(body.path)
        offers = db.loads(row["result"], {}).get("offers") if row else None
    try:
        image = body.image or (_product_image(body.product) if body.product else None)
        _, moved_from = cart.add(body.path, body.title, image, offers=offers, product=body.product)
    except (cart.CartError, akakce.AkakceError) as e:
        raise HTTPException(400, str(e))
    st = _cart_state(scope)
    if moved_from:
        st["moved_from"] = {"path": moved_from["path"], "title": moved_from["title"]}
    return st


@router.patch("/api/cart/{item_id}")
def cart_qty(item_id: int, body: CartQty, scope: str = "all"):
    try:
        if not cart.set_qty(item_id, body.qty):
            raise HTTPException(404, "Ürün sepette yok")
    except cart.CartError as e:
        raise HTTPException(400, str(e))
    return _cart_state(scope)


@router.delete("/api/cart/{item_id}")
def cart_remove(item_id: int, scope: str = "all"):
    cart.remove(item_id)
    return _cart_state(scope)


@router.delete("/api/cart")
def cart_clear():
    cart.clear()
    return _cart_state()


@router.post("/api/cart/compare")
def cart_compare(body: CompareIn):
    """"Fiyatları güncelle": reads one Akakçe page per item (no tokens); a few seconds for a long list."""
    if not cart.items():
        raise HTTPException(400, "Sepet boş")
    scope = _scope(body.scope)
    cart.refresh()
    return _cart_state(scope)


# ---------------------------------------------------------------- store groups

class GroupIn(BaseModel):
    name: str


class GroupPatch(BaseModel):
    name: Optional[str] = None
    collapsed: Optional[bool] = None


@router.get("/api/groups")
def groups_list():
    return sites.all_groups()


@router.post("/api/groups")
def group_add(body: GroupIn):
    try:
        return sites.add_group(body.name)
    except sites.SiteError as e:
        raise HTTPException(400, str(e))


@router.patch("/api/groups/{group_id}")
def group_update(group_id: int, body: GroupPatch):
    try:
        g = sites.update_group(group_id, name=body.name, collapsed=body.collapsed)
    except sites.SiteError as e:
        raise HTTPException(400, str(e))
    if not g:
        raise HTTPException(404, "Grup bulunamadı")
    return g


@router.delete("/api/groups/{group_id}")
def group_delete(group_id: int):
    sites.remove_group(group_id)
    return {"ok": True}


@router.put("/api/groups/order")
def groups_order(body: Order):
    sites.reorder_groups(body.ids)
    return {"ok": True}
