"""Price tracking: Akakçe products re-priced on a schedule (no tokens), with alerts.

Each check stores the best offer (only the user's stores when the item's scope is "mine") in
price_history. An alert is raised when the price reaches the target price for the first time, or,
without a target, when it drops by at least DROP_MIN_PCT since the previous check."""
import logging
import threading
import time

from . import akakce, config, db, health, sites

log = logging.getLogger("commerceos.tracking")

GAP_SECONDS = 2.0   # pause between Akakçe pages during a full check, to stay polite
HISTORY_POINTS = 90

_lock = threading.Lock()
_run = {"running": False, "started_at": None, "finished_at": None, "checked": 0, "errors": 0}


class TrackError(ValueError):
    pass


def _best(offers, scope, my_sites):
    if scope == "mine":
        offers = [o for o in offers if sites.match_site(o["store"], my_sites)]
    return min(offers, key=lambda o: o["price"]) if offers else None


def _alert(item, kind, old, new, offer):
    db.execute("INSERT INTO alerts(tracked_id, kind, title, old_price, new_price, store, url, created_at) "
               "VALUES(?,?,?,?,?,?,?,?)",
               (item["id"], kind, item["title"], old, new, offer["store"], offer.get("url"), db.now_iso()))
    log.info("alert %s: %s %s → %s (%s)", kind, item["title"], old, new, offer["store"])


def check(item_id, offers=None):
    """Re-price one tracked product; returns the updated row. `offers` skips the Akakçe request
    (used when the product was just read for a search)."""
    item = db.one("SELECT * FROM tracked WHERE id=?", (item_id,))
    if not item:
        return None
    now = db.now_iso()
    try:
        if offers is None:
            offers = akakce.offers(item["path"])["offers"]
    except akakce.AkakceError as e:
        db.execute("UPDATE tracked SET checked_at=?, last_error=? WHERE id=?", (now, str(e), item_id))
        if not health.unreachable(e):
            health.report_parse(False, e)
        raise
    best = _best(offers, item["scope"], sites.all_sites())
    if not best:
        msg = "Sitelerinde şu an teklif yok" if item["scope"] == "mine" else "Teklif bulunamadı"
        db.execute("UPDATE tracked SET checked_at=?, last_error=? WHERE id=?", (now, msg, item_id))
        return db.one("SELECT * FROM tracked WHERE id=?", (item_id,))

    old, new, target = item["last_price"], best["price"], item["target_price"]
    if target is not None:
        if new <= target and (old is None or old > target):
            _alert(item, "target", old, new, best)
    elif old is not None and new < old * (1 - config.DROP_MIN_PCT / 100):
        _alert(item, "drop", old, new, best)

    db.execute("INSERT INTO price_history(tracked_id, price, store, checked_at) VALUES(?,?,?,?)",
               (item_id, new, best["store"], now))
    db.execute("UPDATE tracked SET last_price=?, last_store=?, last_url=?, checked_at=?, last_error=NULL, "
               "first_price=COALESCE(first_price, ?), low_price=MIN(COALESCE(low_price, ?), ?) WHERE id=?",
               (new, best["store"], best.get("url"), now, new, new, new, item_id))
    return db.one("SELECT * FROM tracked WHERE id=?", (item_id,))


def check_all(reason="manual"):
    """Re-price every tracked product, one Akakçe page at a time. Returns False if already running."""
    with _lock:
        if _run["running"]:
            return False
        _run.update(running=True, started_at=db.now_iso(), checked=0, errors=0)
    try:
        ids = [r["id"] for r in db.rows("SELECT id FROM tracked ORDER BY id")]
        log.info("tracking check (%s): %d products", reason, len(ids))
        for i, tid in enumerate(ids):
            if i:
                time.sleep(GAP_SECONDS)
            try:
                check(tid)
                _run["checked"] += 1
            except akakce.Throttled as e:
                _run["errors"] += 1
                log.warning("tracking stopped: %s", e)
                break
            except akakce.AkakceError as e:
                _run["errors"] += 1
                log.warning("tracking %s: %s", tid, e)
            except Exception:
                _run["errors"] += 1
                log.exception("tracking %s", tid)
        db.set_meta("track_last_run", db.now_iso())
    finally:
        with _lock:
            _run.update(running=False, finished_at=db.now_iso())
    return True


def start_check_all(reason="manual"):
    if _run["running"]:
        return False
    threading.Thread(target=check_all, args=(reason,), daemon=True).start()
    return True


def run_state():
    return dict(_run, last_run=db.get_meta("track_last_run"))


# ---------------------------------------------------------------- items

def add(path, title, image=None, scope="all", target_price=None, offers=None):
    if not akakce.PRODUCT_PATH.match(path or ""):
        raise TrackError("Geçersiz ürün")
    if scope not in ("mine", "all"):
        raise TrackError("Geçersiz kapsam")
    if target_price is not None and target_price <= 0:
        raise TrackError("Hedef fiyat sıfırdan büyük olmalı")
    existing = db.one("SELECT id FROM tracked WHERE path=? AND scope=?", (path, scope))
    if existing:
        raise TrackError("Bu ürün zaten takipte")
    tid = db.execute("INSERT INTO tracked(path, title, image, scope, target_price, created_at) VALUES(?,?,?,?,?,?)",
                     (path, (title or "Ürün")[:200], image, scope, target_price, db.now_iso()))
    try:
        check(tid, offers=offers)
    except akakce.AkakceError:
        pass   # stays in the list with the error; the next scheduled check tries again
    return get(tid)


def update(item_id, target_price=..., scope=None):
    item = db.one("SELECT * FROM tracked WHERE id=?", (item_id,))
    if not item:
        return None
    if target_price is not ...:
        if target_price is not None and target_price <= 0:
            raise TrackError("Hedef fiyat sıfırdan büyük olmalı")
        db.execute("UPDATE tracked SET target_price=? WHERE id=?", (target_price, item_id))
    if scope is not None and scope != item["scope"]:
        if scope not in ("mine", "all"):
            raise TrackError("Geçersiz kapsam")
        if db.one("SELECT id FROM tracked WHERE path=? AND scope=? AND id<>?", (item["path"], scope, item_id)):
            raise TrackError("Bu ürün bu kapsamla zaten takipte")
        # another set of stores: the old prices say nothing about the new scope
        db.execute("DELETE FROM price_history WHERE tracked_id=?", (item_id,))
        db.execute("UPDATE tracked SET scope=?, last_price=NULL, first_price=NULL, low_price=NULL WHERE id=?",
                   (scope, item_id))
        try:
            check(item_id)
        except akakce.AkakceError:
            pass
    return get(item_id)


def remove(item_id):
    db.execute("DELETE FROM tracked WHERE id=?", (item_id,))


def get(item_id):
    r = db.one("SELECT * FROM tracked WHERE id=?", (item_id,))
    return _public(r) if r else None


def _public(r, my_sites=None):
    hist = db.rows("SELECT price, store, checked_at FROM price_history WHERE tracked_id=? "
                   "ORDER BY checked_at DESC LIMIT ?", (r["id"], HISTORY_POINTS))[::-1]
    out = dict(r, history=hist)
    site = sites.match_site(r["last_store"] or "", my_sites if my_sites is not None else sites.all_sites())
    out["site_id"] = site["id"] if site else None
    out["change_pct"] = (round((r["last_price"] / r["first_price"] - 1) * 100, 1)
                         if r["last_price"] and r["first_price"] else None)
    out["at_target"] = bool(r["target_price"] and r["last_price"] and r["last_price"] <= r["target_price"])
    out["unseen_alerts"] = db.one("SELECT COUNT(*) AS n FROM alerts WHERE tracked_id=? AND seen=0", (r["id"],))["n"]
    return out


def all_items():
    my = sites.all_sites()
    return [_public(r, my) for r in db.rows("SELECT * FROM tracked ORDER BY id DESC")]


def tracked_paths():
    return {(r["path"], r["scope"]): r["id"] for r in db.rows("SELECT id, path, scope FROM tracked")}


# ---------------------------------------------------------------- alerts

def alerts(limit=30):
    return db.rows("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))


def unseen_count():
    return db.one("SELECT COUNT(*) AS n FROM alerts WHERE seen=0")["n"]


def mark_seen():
    db.execute("UPDATE alerts SET seen=1 WHERE seen=0")
