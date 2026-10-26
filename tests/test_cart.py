import pytest

from backend import akakce, cart, db
from tests.test_commerce import client, fake_akakce

P1 = "/bluetooth-kulaklik/en-ucuz-airpods-pro-2-nesil-type-c-fiyati,301549184.html"
P2 = "/powerbank/en-ucuz-anker-powercore-20000-fiyati,111.html"
P3 = "/mouse/en-ucuz-logitech-mx-master-3s-fiyati,222.html"


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(cart, "GAP_SECONDS", 0)


def offers(*rows):
    return [{"store": s, "price": p, "free_shipping": f, "url": f"https://www.akakce.com/r/?{s}", "seller": None}
            for s, p, f in rows]


PAGES = {
    P1: offers(("idefix", 12837.02, True), ("Hepsiburada", 13000, True)),
    P2: offers(("Hepsiburada", 1149, True), ("Trendyol", 1199, False)),
    P3: offers(("Trendyol", 3499, False), ("Hepsiburada", 3600, True)),
}


def add_site(name, domain, group_id=None):
    return db.execute("INSERT INTO sites(name,url,domain,group_id,added_at) VALUES(?,?,?,?,'2026-01-01')",
                      (name, f"https://{domain}", domain, group_id))


def test_split_shows_as_soon_as_items_are_added():
    cart.add(P1, "AirPods", offers=PAGES[P1])
    cart.add(P2, "Anker", offers=PAGES[P2])
    cart.add(P2, "Anker")                     # same product again: quantity 2, nothing read
    cart.add(P3, "MX Master", offers_for=PAGES.__getitem__)   # no offers given: read once on add
    r = cart.split("all")
    assert [(p["title"], p["store"], p["qty"], p["subtotal"]) for p in r["items"]] == [
        ("AirPods", "idefix", 1, 12837.02), ("Anker", "Hepsiburada", 2, 2298.0), ("MX Master", "Trendyol", 1, 3499)]
    assert r["total"] == 18634.02 and len(r["orders"]) == 3 and r["checked_at"]
    assert {o["store"]: o["free_shipping"] for o in r["orders"]} == {"idefix": True, "Hepsiburada": True, "Trendyol": False}
    assert r["shipping_unknown"] and r["missing"] == []
    cart.set_qty(1, 3)                        # quantity changes the split without any request
    assert cart.split("all")["total"] == round(12837.02 * 3 + 2298 + 3499, 2)


def test_split_within_scope_missing_and_refresh():
    hb = add_site("Hepsiburada", "hepsiburada.com")
    cart.add(P1, "AirPods", offers=PAGES[P1])
    cart.add(P3, "MX Master", offers=PAGES[P3])

    def down(path):
        raise akakce.AkakceError("Akakçe yanıt vermedi (HTTP 503)")
    cart.add("/x/en-ucuz-yok-fiyati,9.html", "Kayıp", offers_for=down)
    r = cart.split("mine")
    assert [(p["store"], p["site_id"]) for p in r["items"]] == [("Hepsiburada", hb), ("Hepsiburada", hb)]
    assert len(r["orders"]) == 1 and r["orders"][0]["total"] == 16600 and not r["shipping_unknown"]
    assert r["missing"] == [{"id": 3, "title": "Kayıp", "reason": "Akakçe yanıt vermedi (HTTP 503)"}]
    cheaper = {P1: offers(("Hepsiburada", 9000, True)), P3: PAGES[P3],
               "/x/en-ucuz-yok-fiyati,9.html": offers(("Hepsiburada", 50, True))}
    cart.refresh(offers_for=cheaper.__getitem__)          # "Fiyatları güncelle"
    r = cart.split("mine")
    assert r["total"] == 9000 + 3600 + 50 and r["missing"] == []


def test_cart_api(monkeypatch):
    n = {"search": 0, "offers": 0}
    fake_akakce(monkeypatch, n)
    with client() as c:
        r = c.get("/api/search", params={"q": "airpods pro 2"}).json()
        assert r["cart_id"] is None
        state = c.post("/api/cart", json={"path": r["product"]["path"], "title": r["product"]["title"],
                                          "image": "http://insecure/x.jpg"}).json()
        it = state["items"][0]
        assert it["qty"] == 1 and it["image"] is None and it["last_price"] == 12837.02 and "offers" not in it
        assert state["result"]["total"] == 12837.02 and state["result"]["orders"][0]["store"] == "idefix"
        assert n["offers"] == 1                               # split straight from the search, no extra read
        assert c.get("/api/search", params={"q": "airpods pro 2"}).json()["cart_id"] == it["id"]
        assert c.patch(f"/api/cart/{it['id']}", json={"qty": 3}).json()["result"]["total"] == round(12837.02 * 3, 2)
        assert c.patch(f"/api/cart/{it['id']}", json={"qty": 0}).status_code == 400
        db.execute("INSERT INTO sites(name,url,domain,added_at) VALUES('Hepsiburada','https://hepsiburada.com','hepsiburada.com','x')")
        mine = c.get("/api/cart", params={"scope": "mine"}).json()["result"]
        assert mine["scope"] == "mine" and {o["store"] for o in mine["orders"]} == {"Hepsiburada"}
        res = c.post("/api/cart/compare", json={"scope": "all"}).json()["result"]
        assert res["total"] == round(12837.02 * 3, 2) and n["offers"] == 2
        assert c.post("/api/cart", json={"path": "https://evil/", "title": "x"}).status_code == 400
        c.delete("/api/cart")
        assert c.get("/api/cart").json() == {"items": [], "result": None, "shipping": {}}
        assert c.post("/api/cart/compare", json={"scope": "all"}).status_code == 400


def test_items_without_offers_are_read_once_on_view(monkeypatch):
    db.execute("INSERT INTO cart_items(path,title,qty,added_at) VALUES(?,?,1,'x')", (P2, "Anker"))   # an old item
    monkeypatch.setattr(akakce, "offers", lambda path: {"title": "", "url": "", "offers": PAGES[path]})
    with client() as c:
        assert c.get("/api/cart").json()["result"]["total"] == 1149


def test_single_store_totals():
    cart.add(P1, "AirPods", offers=PAGES[P1])
    cart.add(P2, "Anker", offers=PAGES[P2])
    cart.add(P2, "Anker")
    cart.add(P3, "MX Master", offers=PAGES[P3])
    r = cart.split("all")
    full = r["single"]["full"]
    # Hepsiburada has all three: 13000 + 2 × 1149 + 3600; Trendyol and idefix do not
    assert [(o["store"], o["total"], o["extra"]) for o in full] == [("Hepsiburada", 18898.0, round(18898 - 18634.02, 2))]
    assert full[0]["free_shipping"] and r["single"]["best_partial"] is None


def test_single_store_partial_when_no_store_has_everything():
    cart.add(P1, "AirPods", offers=offers(("idefix", 100, True)))
    cart.add(P2, "Anker", offers=offers(("Trendyol", 50, False), ("idefix", 60, True)))
    cart.add(P3, "MX Master", offers=offers(("Teknosa", 70, True)))
    s = cart.split("all")["single"]
    assert s["full"] == []
    assert (s["best_partial"]["store"], s["best_partial"]["count"], s["best_partial"]["missing"]) == ("idefix", 2, ["MX Master"])


def test_offer_from_the_other_sources_goes_into_the_cart(monkeypatch):
    from backend import akakce, amazon, stores
    from tests.conftest import fixture

    def limited(q):
        raise akakce.Throttled("Fiyat kaynağı çok sık istek yüzünden kısa süre bekletiyor (yaklaşık 5 dk)")
    monkeypatch.setattr(akakce, "search", limited)
    monkeypatch.setattr(amazon, "search", lambda q: [])
    monkeypatch.setattr(stores, "search", lambda q: stores.parse_mediamarkt(fixture("mediamarkt_search.html"), q))
    with client() as c:
        offer = c.get("/api/search", params={"q": "airpods 4"}).json()["offers"][0]
        st = c.post("/api/cart", json={"path": offer["url"], "title": offer["title"]}).json()
        [it] = st["items"]
        assert it["path"] == offer["url"] and it["last_price"] == offer["price"] == 6249.0
        assert st["result"]["orders"][0]["store"] == "MediaMarkt"
        # the price comes from the search, so a URL that no search showed is refused
        r = c.post("/api/cart", json={"path": "https://www.mediamarkt.com.tr/tr/product/_baska-1.html", "title": "x"})
        assert r.status_code == 400
        assert c.post("/api/cart", json={"path": "https://evil.example/x", "title": "x"}).status_code == 400
        # "Fiyatları güncelle" leaves a single store's offer as it is (nothing to read it from)
        called = []
        monkeypatch.setattr(cart, "_read", lambda p: called.append(p) or [])
        cart.refresh()
        assert called == [] and cart.items()[0]["offers"]


def test_one_store_offer_from_the_main_source_goes_into_the_cart(monkeypatch):
    fake_akakce(monkeypatch, {"search": 0, "offers": 0})
    with client() as c:
        r = c.get("/api/search", params={"q": "airpods pro 2"}).json()
        pick = r["offers"][3]                                # not the cheapest: the user wants this store
        assert pick["url"].startswith("https://www.akakce.com/r/?")
        st = c.post("/api/cart", json={"path": pick["url"], "title": pick["title"], "product": r["product"]["path"]}).json()
        [it] = st["items"]
        assert it["last_price"] == pick["price"]
        assert it["image"] == r["products"][0]["image"]           # the product's picture stands in
        assert st["result"]["orders"][0]["store"] == pick["store"]
        # only Akakçe's seller links, not any page of it
        assert c.post("/api/cart", json={"path": "https://www.akakce.com/arama/?q=x", "title": "x"}).status_code == 400


def test_picking_another_store_moves_the_line_and_back(monkeypatch):
    fake_akakce(monkeypatch, {"search": 0, "offers": 0})
    with client() as c:
        r = c.get("/api/search", params={"q": "airpods pro 2"}).json()
        product, a, b = r["product"]["path"], r["offers"][0], r["offers"][3]
        c.post("/api/cart", json={"path": a["url"], "title": a["title"], "product": product})
        c.post("/api/cart", json={"path": a["url"], "title": a["title"], "product": product})   # same store: 2
        st = c.post("/api/cart", json={"path": b["url"], "title": b["title"], "product": product}).json()
        [it] = st["items"]
        assert it["path"] == b["url"] and it["qty"] == 2 and it["last_price"] == b["price"]
        assert st["moved_from"] == {"path": a["url"], "title": a["title"]}
        back = c.post("/api/cart", json={"path": a["url"], "title": a["title"], "product": product}).json()
        [it] = back["items"]
        assert it["path"] == a["url"] and it["qty"] == 2 and back["moved_from"]["path"] == b["url"]
        # a line added as the product itself (tracked list) moves to the picked store too
        c.delete("/api/cart")
        c.post("/api/cart", json={"path": product, "title": "AirPods"})
        [it] = c.post("/api/cart", json={"path": b["url"], "title": b["title"], "product": product}).json()["items"]
        assert it["path"] == b["url"]


def test_refresh_reads_a_picked_store_from_its_product_page():
    old = {"store": "n11", "seller": "deflanka", "price": 7999.0, "url": "https://www.akakce.com/r/?pr=1", "free_shipping": True}
    cart.add(old["url"], "JBL", offers=[old], product=P1)
    page = [dict(old, price=7799.0), {"store": "Trendyol", "seller": None, "price": 7000.0, "url": "https://www.akakce.com/r/?pr=2"}]
    cart.refresh(offers_for=lambda p: page if p == P1 else [])
    [it] = cart.items()
    assert db.loads(it["offers"], None)[0]["price"] == 7799.0      # the same seller, not the cheapest
    cart.refresh(offers_for=lambda p: page[1:])                     # the seller has gone
    [it] = cart.items()
    assert db.loads(it["offers"], None)[0]["price"] == 7799.0 and it["offers_error"] == "Bu satıcı artık listede yok"


def test_shipping_fee_entered_for_a_store_is_added():
    cart.add(P1, "AirPods", offers=[{"store": "Trendyol", "price": 1000.0, "url": "u", "free_shipping": False}])
    r = cart.split("all")
    assert r["shipping_unknown"] and r["orders"][0]["shipping"] is None and r["total"] == 1000.0
    cart.set_shipping("Trendyol", 49.9, 1500)
    r = cart.split("all")
    o = r["orders"][0]
    assert o["shipping"] == 49.9 and o["grand"] == 1049.9 and r["total"] == 1049.9 and not r["shipping_unknown"]
    cart.add(P1, "AirPods")                                   # 2 × 1000 = 2000 ≥ 1500: free
    assert cart.split("all")["orders"][0]["shipping"] == 0.0
    with client() as c:
        st = c.put("/api/shipping", json={"store": "Trendyol", "fee": None, "free_over": None}).json()
        assert st["shipping"] == {} and st["result"]["shipping_unknown"]
        assert c.put("/api/shipping", json={"store": "Trendyol", "fee": -5}).status_code == 400
