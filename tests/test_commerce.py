import socket
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import ai, akakce, amazon, db, health, main, net, providers, sites, stores

REAL_KEY_FUNCS = {n: getattr(providers, n) for n in ("keychain_get", "keychain_set", "keychain_delete")}
from tests.conftest import fixture

REAL_PROBE = health._probe   # conftest swaps it out for every test
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 200


def client():
    return TestClient(main.app, base_url="http://127.0.0.1:8002")


class FakeResp:
    def __init__(self, status=200, body=b"", ctype="text/html", url="https://x"):
        self.status_code, self.content, self.url = status, body, url
        self.headers = {"content-type": ctype}
        self.text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body


# ---------------------------------------------------------------- Akakçe parsing

def test_parse_search_keeps_only_result_products():
    products = akakce.parse_search(fixture("akakce_search.html"))
    assert len(products) >= 10
    first = products[0]
    assert first["name"] == "AirPods Pro 2. Nesil Type-C"
    assert first["price"] == 12837.02
    assert first["offers"] == 14
    assert akakce.PRODUCT_PATH.match(first["path"])


def test_parse_product_offers_sorted_with_store_and_link():
    offers = akakce.parse_product(fixture("akakce_product.html"))
    assert len(offers) == 14
    assert offers == sorted(offers, key=lambda o: o["price"])
    o = offers[0]
    assert o["store"] == "idefix" and o["seller"] == "Terminal iletişim"
    assert o["price"] == 12837.02 and o["free_shipping"]
    assert o["url"].startswith("https://www.akakce.com/r/?pr=301549184")
    assert any(x["store"] == "Hepsiburada" for x in offers)


@pytest.mark.parametrize("raw,price", [
    ("12.837<i>,<!-- -->02<!-- --> TL </i>", 12837.02), ("999 TL", 999.0), ("1.250.000<i>,5 TL</i>", 1250000.5),
    ("fiyat yok", None)])
def test_parse_price(raw, price):
    assert akakce.parse_price(raw) == price


def test_broken_markup_gives_nothing_not_an_error():
    assert akakce.parse_search("<html>yeni tasarım</html>") == []
    assert akakce.parse_product("<html></html>") == []


# ---------------------------------------------------------------- addresses and SSRF

@pytest.mark.parametrize("raw,url,domain", [
    ("Trendyol.com", "https://trendyol.com", "trendyol.com"),
    ("https://www.n11.com/kampanya", "https://www.n11.com", "n11.com"),
    ("http://shop.example.com.tr", "http://shop.example.com.tr", "shop.example.com.tr")])
def test_normalize_url(raw, url, domain):
    assert sites.normalize_url(raw) == (url, domain)


@pytest.mark.parametrize("bad", ["", "ftp://x.com", "javascript:alert(1)", "localhost", "192.168.1.1"])
def test_normalize_url_rejects(bad):
    with pytest.raises(sites.SiteError):
        sites.normalize_url(bad)


@pytest.mark.parametrize("ip", ["127.0.0.1", "192.168.1.10", "10.0.0.5", "169.254.169.254", "::1", "fd00::1"])
def test_check_url_blocks_local_network(monkeypatch, ip):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", (ip, 443))])
    with pytest.raises(net.Blocked):
        net.check_url("https://evil.example.com/")


def test_check_url_blocks_other_schemes():
    for u in ("file:///etc/passwd", "gopher://x", "https://user:pw@example.com"):
        with pytest.raises(net.Blocked):
            net.check_url(u)


def test_redirect_to_local_address_is_blocked(monkeypatch):
    def resolve(host, *a, **k):
        return [(2, 1, 6, "", ("127.0.0.1" if host == "inner.example" else "93.184.216.34", 443))]
    monkeypatch.setattr(socket, "getaddrinfo", resolve)

    class Redirect:
        is_redirect = True
        headers = {"location": "http://inner.example/admin"}
        def close(self): pass
    monkeypatch.setattr(net.requests, "get", lambda *a, **k: Redirect())
    with pytest.raises(net.Blocked):
        net.get("https://shop.example.com/")


# ---------------------------------------------------------------- store matching and pages

def test_match_site_by_store_name():
    my = [{"id": 1, "name": "Amazon TR", "domain": "amazon.com.tr"},
          {"id": 2, "name": "MediaMarkt", "domain": "mediamarkt.com.tr"},
          {"id": 3, "name": "İtopya", "domain": "itopya.com"}]
    assert sites.match_site("Amazon.com.tr", my)["id"] == 1
    assert sites.match_site("Media Markt", my)["id"] == 2
    assert sites.match_site("itopya", my)["id"] == 3
    assert sites.match_site("Hepsiburada", my) is None


def test_inspect_reads_name_icons_and_opensearch(monkeypatch):
    page = b"""<html><head><title>Vatan Bilgisayar | Teknoloji Ma\xc4\x9fazas\xc4\xb1</title>
      <link rel="icon" href="/fav.ico" sizes="32x32"><link rel="apple-touch-icon" href="/apple.png" sizes="180x180">
      <link rel="icon" type="image/svg+xml" href="/logo.svg">
      <link rel="search" type="application/opensearchdescription+xml" href="/os.xml"></head></html>"""
    monkeypatch.setattr(net, "get", lambda url, **k: FakeResp(200, page, url="https://www.vatan.com/"))
    info = sites.inspect("https://www.vatan.com", "vatan.com")
    assert info["name"] == "Vatan Bilgisayar"
    assert info["icons"] == ["https://www.vatan.com/apple.png", "https://www.vatan.com/fav.ico"]
    assert info["opensearch"] == "https://www.vatan.com/os.xml"


def test_opensearch_template(monkeypatch):
    xml = (b'<OpenSearchDescription><Url type="application/x-suggestions+json" template="https://s/sug?q={searchTerms}"/>'
           b'<Url type="text/html" template="https://shop.com/ara?q={searchTerms}&amp;page={startPage?}"/></OpenSearchDescription>')
    monkeypatch.setattr(net, "get", lambda url, **k: FakeResp(200, xml, "application/xml"))
    assert sites.opensearch_template("https://shop.com/os.xml") == "https://shop.com/ara?q={q}"


def test_blocked_store_still_added_with_known_values(monkeypatch):
    calls = []

    def fake_get(url, **k):
        calls.append(url)
        if "google.com/s2/favicons" in url:
            return FakeResp(200, PNG, "image/png")
        return FakeResp(403, b"Cloudflare")
    monkeypatch.setattr(net, "get", fake_get)
    s = sites.add("hepsiburada.com")
    assert s["name"] == "Hepsiburada" and s["search_url"] == "https://www.hepsiburada.com/ara?q={q}"
    assert s["logo"] == "hepsiburada.com.png" and sites.logo_path(s).read_bytes() == PNG
    with pytest.raises(sites.SiteError):
        sites.add("https://www.hepsiburada.com/")


def test_logo_rejects_non_images(monkeypatch):
    monkeypatch.setattr(net, "get", lambda url, **k: FakeResp(200, b"<html>" + b"x" * 300, "text/html"))
    assert sites.fetch_logo("example.com", ["https://example.com/apple.png"]) is None


def test_seed_defaults_once_without_network():
    db.execute("DELETE FROM meta")
    sites.seed_defaults()
    names = [s["name"] for s in sites.all_sites()]
    assert names == ["Hepsiburada", "Amazon TR", "Trendyol", "n11"]
    [g] = sites.all_groups()                      # all in one group, shown open
    assert g["name"] == "Alışveriş" and not g["collapsed"]
    assert {s["group_id"] for s in sites.all_sites()} == {g["id"]}
    sites.remove(sites.all_sites()[0]["id"])
    sites.seed_defaults()  # a deleted default must not come back
    assert len(sites.all_sites()) == 3 and len(sites.all_groups()) == 1


# ---------------------------------------------------------------- API

def fake_akakce(monkeypatch, counter):
    def search(q):
        counter["search"] += 1
        return akakce.parse_search(fixture("akakce_search.html"))

    def offers(path):
        counter["offers"] += 1
        return {"title": "AirPods Pro 2. Nesil Type-C", "url": akakce.BASE + path,
                "offers": akakce.parse_product(fixture("akakce_product.html"))}
    monkeypatch.setattr(akakce, "search", search)
    monkeypatch.setattr(akakce, "offers", offers)


def test_quick_search_scope_cache_and_history(monkeypatch):
    n = {"search": 0, "offers": 0}
    fake_akakce(monkeypatch, n)
    db.execute("INSERT INTO sites(name,url,domain,search_url,added_at) VALUES('Hepsiburada','https://www.hepsiburada.com',"
               "'hepsiburada.com',NULL,'2026-01-01')")
    with client() as c:
        r = c.get("/api/search", params={"q": "airpods pro 2"}).json()
        assert r["kind"] == "quick" and len(r["offers"]) == 14 and not r["from_cache"]
        assert r["product"]["title"] == "AirPods Pro 2. Nesil Type-C"
        hb = [o for o in r["offers"] if o["store"] == "Hepsiburada"]
        assert hb and hb[0]["site_id"]

        mine = c.get("/api/search", params={"q": "AirPods  Pro 2", "scope": "mine"}).json()
        assert mine["from_cache"] and n == {"search": 1, "offers": 1}   # same search, no new request
        assert {o["store"] for o in mine["offers"]} == {"Hepsiburada"} and mine["total_offers"] == 14

        other = r["products"][1]["path"]
        c.get("/api/search", params={"q": "airpods pro 2", "product": other})
        assert n == {"search": 1, "offers": 2}                           # product list reused

        hist = c.get("/api/history").json()
        assert len(hist) == 1 and hist[0]["min_price"] == 12837.02        # product switches are not listed
        assert c.get(f"/api/history/{hist[0]['id']}").json()["from_cache"]
        c.delete(f"/api/history/{hist[0]['id']}")
        assert db.rows("SELECT * FROM searches") == []


def test_quick_search_every_source_down_suggests_deep(monkeypatch):
    def down(q):
        raise akakce.AkakceError("Akakçe yanıt vermedi (HTTP 503)")
    monkeypatch.setattr(akakce, "search", down)

    def amazon_down(q):
        raise amazon.AmazonError("Amazon TR'ye de ulaşılamadı")
    monkeypatch.setattr(amazon, "search", amazon_down)
    with client() as c:
        r = c.get("/api/search", params={"q": "dyson v15"})
    assert r.status_code == 200 and r.json()["empty"]          # the page offers the deep search


def test_third_source_when_akakce_and_amazon_fail(monkeypatch):
    def down(q):
        raise akakce.Throttled("Akakçe çok sık istek yüzünden bizi kısa süre bekletiyor (yaklaşık 5 dk)")
    monkeypatch.setattr(akakce, "search", down)
    monkeypatch.setattr(amazon, "search", lambda q: [])
    monkeypatch.setattr(stores, "search", lambda q: stores.parse_mediamarkt(fixture("mediamarkt_search.html"), q)
                        + stores.parse_vatan(fixture("vatan_search.html"), q))
    with client() as c:
        r = c.get("/api/search", params={"q": "airpods 4"}).json()
    assert r["source"] == "stores" and {o["store"] for o in r["offers"]} == {"MediaMarkt", "Vatan Bilgisayar"}
    assert [o["price"] for o in r["offers"]] == sorted(o["price"] for o in r["offers"])


def test_store_parsers():
    mm = stores.parse_mediamarkt(fixture("mediamarkt_search.html"), "airpods 4")
    assert mm[0]["title"].startswith("APPLE Airpods 4") and mm[0]["price"] == 6249.0
    assert all(o["url"].startswith("https://www.mediamarkt.com.tr/tr/product/") for o in mm)
    vt = stores.parse_vatan(fixture("vatan_search.html"), "airpods 4")
    assert {o["price"] for o in vt} == {8999.0, 7439.0} and all("vatanbilgisayar.com/" in o["url"] for o in vt)
    assert stores.parse_vatan(fixture("vatan_search.html"), "hunter bot") == []
    assert stores.parse_mediamarkt("<html>yeni tasarım</html>", "airpods") == []


def test_amazon_parse_drops_accessories():
    page = fixture("amazon_search.html")
    got = amazon.parse(page, "airpods 4")
    assert [o["price"] for o in got] == [6124.02, 8249.0]
    assert all(o["store"] == "Amazon TR" and o["url"].startswith("https://www.amazon.com.tr/dp/") for o in got)
    assert amazon.parse(page, "airpods pro 2") == []                 # only cases and ear tips match
    assert any("Kılıf" in o["title"] for o in amazon.parse(page, "airpods pro 2 kılıf"))


def test_akakce_down_falls_back_to_amazon(monkeypatch):
    def down(q):
        raise akakce.AkakceError("Akakçe'ye ulaşılamadı")
    monkeypatch.setattr(akakce, "search", down)
    monkeypatch.setattr(amazon, "search", lambda q: amazon.parse(fixture("amazon_search.html"), q)[::-1])
    with client() as c:
        r = c.get("/api/search", params={"q": "airpods 4"}).json()
        assert r["source"] == "amazon" and [o["price"] for o in r["offers"]] == [6124.02, 8249.0]
        assert r["product"] is None and r["tracked_id"] is None
        assert c.get("/api/status").json()["health"]["akakce"] is False


def test_amazon_parse_brand_and_name_headings():
    # since Oct 2026 each result has the brand and the rest of the name in two headings
    got = amazon.parse(fixture("amazon_search_2026.html"), "adidas ayakkabı")
    assert got and got[0]["title"] == "adidas Samba Og Erkek Günlük Spor Ayakkabı" and got[0]["price"] == 4799.4
    assert all("ayakkab" in o["title"].lower() for o in got)


def test_akakce_429_pauses_every_request(monkeypatch):
    calls = []

    def fake_curl(url, **kw):
        calls.append(url)
        return 429, b""
    monkeypatch.setattr(akakce.net, "curl_get", fake_curl)
    monkeypatch.setattr(akakce, "_pause", {"until": 0.0, "length": 0.0})
    with pytest.raises(akakce.Throttled):
        akakce.search("adidas")
    assert len(calls) == 1 and 4 * 60 < akakce.paused_for() <= 5 * 60
    with pytest.raises(akakce.Throttled):                 # paused: nothing goes out
        akakce.offers("/a/en-ucuz-b-fiyati,1.html")
    assert len(calls) == 1
    REAL_PROBE()                                          # nor from the header's health check
    assert len(calls) == 1 and health._state["ok"] is False and "429" in health._state["error"]
    akakce._pause["until"] = 0                            # pause over, still limited: twice as long
    with pytest.raises(akakce.Throttled):
        akakce.search("adidas")
    assert len(calls) == 2 and akakce.paused_for() > 9 * 60


def test_backup_result_is_not_reused_once_akakce_is_back(monkeypatch):
    monkeypatch.setattr(akakce, "_pause", {"until": 0.0, "length": 0.0})

    def limited(q):
        raise akakce.Throttled("Akakçe çok sık istek yüzünden bizi kısa süre bekletiyor (yaklaşık 5 dk)")
    monkeypatch.setattr(akakce, "search", limited)
    monkeypatch.setattr(amazon, "search", lambda q: amazon.parse(fixture("amazon_search_2026.html"), q))
    with client() as c:
        r = c.get("/api/search", params={"q": "adidas ayakkabı"}).json()
        assert r["source"] == "amazon" and r["offers"] and "bekletiyor" in r["fallback_reason"]
        akakce_called = []
        monkeypatch.setattr(akakce, "search", lambda q: akakce_called.append(q) or [])
        c.get("/api/search", params={"q": "adidas ayakkabı"})
        assert akakce_called == ["adidas ayakkabı"]       # asked Akakçe again, not the cached backup


def test_akakce_empty_tries_amazon(monkeypatch):
    monkeypatch.setattr(akakce, "search", lambda q: [])
    monkeypatch.setattr(amazon, "search", lambda q: [])
    with client() as c:
        assert c.get("/api/search", params={"q": "yok böyle ürün"}).json()["empty"]


def test_bad_input_rejected():
    with client() as c:
        assert c.get("/api/search", params={"q": "x"}).status_code == 400
        assert c.get("/api/search", params={"q": "ok ok", "scope": "x"}).status_code == 400
        assert c.get("/api/search", params={"q": "ok ok", "product": "https://evil/"}).status_code == 400


def test_deep_search_records_tokens_fixes_links_and_caches(monkeypatch):
    text = """```json
{"summary": "En ucuzu A101.", "offers": [
  {"store": "Hepsiburada", "title": "AirPods Pro 2", "price": "13499,90", "currency": "TL", "url": "https://hb/yok", "note": ""},
  {"store": "A101", "title": "AirPods Pro 2", "price": 12999, "url": "https://a101/var", "note": "Stokta"},
  {"store": "Bozuk", "price": "fiyat yok"}]}
```"""
    web = SimpleNamespace(uri="https://vertex/redirect", title="a101.com.tr", domain="a101.com.tr")
    raw = SimpleNamespace(candidates=[SimpleNamespace(grounding_metadata=SimpleNamespace(grounding_chunks=[SimpleNamespace(web=web)]))])
    resp = providers.Reply(text, "gemini", "gemini-2.5-flash", raw=raw, usage=(3000, 600))
    calls = []

    def fake_generate(prompt, on_usage=None, **kw):
        calls.append(prompt)
        on_usage(resp)
        return resp
    monkeypatch.setattr(providers, "generate", fake_generate)
    monkeypatch.setattr(ai, "_check_link", lambda u: "yok" not in u)
    db.execute("INSERT INTO sites(name,url,domain,search_url,added_at) VALUES('Hepsiburada','https://www.hepsiburada.com',"
               "'hepsiburada.com','https://www.hepsiburada.com/ara?q={q}','2026-01-01')")
    with client() as c:
        r = c.post("/api/search/deep", json={"q": "AirPods Pro 2", "scope": "all"}).json()
        assert [o["store"] for o in r["offers"]] == ["A101", "Hepsiburada"]
        hb = r["offers"][1]
        assert hb["link_fallback"] and hb["url"] == "https://www.hepsiburada.com/ara?q=AirPods+Pro+2"
        assert r["tokens"] == 3600 and r["sources"][0]["url"] == "https://vertex/redirect"
        again = c.post("/api/search/deep", json={"q": "airpods pro 2", "scope": "all"}).json()
        assert again["from_cache"] and len(calls) == 1
        month = c.get("/api/status").json()["month"]
        assert (month["tokens"], month["searches"]) == (3600, 1) and month["cost"] > 0
        u = c.get("/api/usage", params={"period": "month"}).json()
        assert u["tokens"] == 3600 and u["sections"][0]["key"] == "deep" and u["sections"][0]["requests"] == 1

        mine = c.post("/api/search/deep", json={"q": "AirPods Pro 2", "scope": "mine"}).json()
        assert "SADECE" in calls[-1] and "hepsiburada.com" in calls[-1]
        assert [o["store"] for o in mine["offers"]] == ["Hepsiburada"]


def test_deep_search_without_key(monkeypatch):
    with client() as c:
        r = c.post("/api/search/deep", json={"q": "airpods"})
    assert r.status_code == 503


def test_sites_api_and_foreign_host(monkeypatch):
    monkeypatch.setattr(net, "get", lambda url, **k: FakeResp(200, PNG, "image/png") if "favicons" in url
                        else FakeResp(403, b""))
    with client() as c:
        s = c.post("/api/sites", json={"url": "teknosa.com"}).json()
        assert s["name"] == "Teknosa" and s["logo"].startswith(f"/api/sites/{s['id']}/logo")
        assert c.get(s["logo"]).content == PNG
        assert c.patch(f"/api/sites/{s['id']}", json={"name": "Teknosa Mağaza"}).json()["name"] == "Teknosa Mağaza"
        assert c.post("/api/sites", json={"url": "teknosa.com"}).status_code == 400
        assert c.delete(f"/api/sites/{s['id']}").json()["ok"]
        assert c.post("/api/sites", json={"url": "x"}, headers={"origin": "https://evil.com"}).status_code == 403
    with TestClient(main.app, base_url="http://evil.example") as c:
        assert c.get("/api/sites").status_code == 403


def test_curl_get_splits_status_and_rejects_local(monkeypatch):
    seen = {}

    def run(args, **k):
        seen["args"] = args
        return SimpleNamespace(returncode=0, stdout=b"<html>\nok</html>\n200 ", stderr=b"")
    monkeypatch.setattr(net.subprocess, "run", run)
    assert net.curl_get("https://www.akakce.com/arama/?q=x") == (200, b"<html>\nok</html>")
    assert seen["args"][-1] == "https://www.akakce.com/arama/?q=x" and "=https" in seen["args"]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(net.Blocked):
        net.curl_get("https://www.akakce.com/")


def test_status_health_reports_issues(monkeypatch):
    with client() as c:
        h = c.get("/api/status").json()["health"]
        assert h["akakce"] is None and h["issues"] == ["Yapay zekâ sağlayıcısı yok: derin arama kapalı (⚙ Ayarlar)"]
        health.report(False)
        h = c.get("/api/status").json()["health"]
        assert h["akakce"] is False and any("fiyat kaynağı" in i for i in h["issues"])
        assert not any("Akakçe" in i or "Amazon" in i for i in h["issues"])     # sources are never named


def test_health_probe_records_result(monkeypatch):
    monkeypatch.setattr(net, "curl_get", lambda url, **k: (403, b"cloudflare"))
    REAL_PROBE()
    assert health._state["ok"] is False and health._state["error"] == "HTTP 403"
    monkeypatch.setattr(net, "curl_get", lambda url, **k: (200, b"ok"))
    REAL_PROBE()
    assert health._state["ok"] is True and not health._state["running"]


def test_quick_search_marks_akakce_healthy(monkeypatch):
    n = {"search": 0, "offers": 0}
    fake_akakce(monkeypatch, n)
    with client() as c:
        c.get("/api/search", params={"q": "airpods pro 2"})
        assert c.get("/api/status").json()["health"]["akakce"] is True


def test_reorder_sites():
    db.execute("DELETE FROM meta")
    sites.seed_defaults()
    ids = [s["id"] for s in sites.all_sites()]
    with client() as c:
        assert c.put("/api/sites/order", json={"ids": ids[::-1]}).json()["ok"]
        assert [s["id"] for s in c.get("/api/sites").json()] == ids[::-1]


REAL_PARSE_PROBE = health._parse_probe


def test_structure_check_outcomes(monkeypatch):
    product = akakce.parse_search(fixture("akakce_search.html"))
    monkeypatch.setattr(akakce, "search", lambda q: product)
    monkeypatch.setattr(akakce, "offers", lambda path: {"title": "", "url": "", "offers": [{"price": 1}]})
    REAL_PARSE_PROBE()
    assert health._parse["ok"] is True

    monkeypatch.setattr(akakce, "search", lambda q: [])                # markup changed: nothing parsed
    REAL_PARSE_PROBE()
    assert health._parse["ok"] is False and "okunamadı" in health._parse["error"]

    def offline(q):
        raise akakce.AkakceError("Akakçe'ye ulaşılamadı")
    monkeypatch.setattr(akakce, "search", offline)                      # offline says nothing about markup
    REAL_PARSE_PROBE()
    assert health._parse["ok"] is False and "okunamadı" in health._parse["error"]

    def crash(q):
        raise IndexError("x")
    monkeypatch.setattr(akakce, "search", crash)
    health.report_parse(True)
    REAL_PARSE_PROBE()
    assert health._parse["ok"] is False


def test_structure_issue_in_status_and_reports_from_search(monkeypatch):
    def unreadable(path):
        raise akakce.AkakceError("Bu ürün için satıcı fiyatları okunamadı")
    monkeypatch.setattr(akakce, "search", lambda q: akakce.parse_search(fixture("akakce_search.html")))
    monkeypatch.setattr(akakce, "offers", unreadable)
    with client() as c:
        assert c.get("/api/search", params={"q": "airpods"}).status_code == 502
        h = c.get("/api/status").json()["health"]
        assert h["akakce_parse"] is False and any("sayfalarının yapısı" in i for i in h["issues"])
        n = {"search": 0, "offers": 0}
        fake_akakce(monkeypatch, n)
        c.get("/api/search", params={"q": "airpods pro 2", "refresh": True})
        h = c.get("/api/status").json()["health"]
        assert h["akakce_parse"] is True and not any("sayfalarının yapısı" in i for i in h["issues"])


def test_curl_get_follows_redirects_checking_each_hop(monkeypatch):
    calls = []

    def run(args, **k):
        calls.append(args[-1])
        if len(calls) == 1:
            return SimpleNamespace(returncode=0, stdout=b"\n307 https://www.akakce.com/cep-telefonu/apple.html", stderr=b"")
        return SimpleNamespace(returncode=0, stdout=b"<li>apple</li>\n200 ", stderr=b"")
    monkeypatch.setattr(net.subprocess, "run", run)
    assert net.curl_get("https://www.akakce.com/arama/?q=iphone") == (200, b"<li>apple</li>")
    assert calls[1] == "https://www.akakce.com/cep-telefonu/apple.html"

    def to_local(args, **k):
        return SimpleNamespace(returncode=0, stdout=b"\n302 https://inner.example/", stderr=b"")
    monkeypatch.setattr(net.subprocess, "run", to_local)
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, *a, **k: [(2, 1, 6, "", ("10.0.0.2" if host == "inner.example" else "93.184.216.34", 443))])
    with pytest.raises(net.Blocked):
        net.curl_get("https://www.akakce.com/x")


def test_history_item_refilters_for_another_scope(monkeypatch):
    counter = {"search": 0, "offers": 0}
    fake_akakce(monkeypatch, counter)
    db.execute("INSERT INTO sites(name,url,domain,added_at) VALUES('Hepsiburada','https://www.hepsiburada.com','hepsiburada.com','2026-01-01')")
    with client() as c:
        r = c.get("/api/search", params={"q": "airpods pro 2"}).json()
        mine = c.get(f"/api/history/{r['id']}", params={"scope": "mine"}).json()
        assert mine["scope"] == "mine" and mine["offers"] and all(o["site_id"] for o in mine["offers"])
        assert len(mine["offers"]) < len(r["offers"]) and mine["total_offers"] == r["total_offers"]
        assert c.get(f"/api/history/{r['id']}", params={"scope": "bogus"}).status_code == 400
        assert counter == {"search": 1, "offers": 1}            # switching stores asked nothing again


def test_standalone_ai_settings_and_key_names(tmp_path, monkeypatch, fake_secrets):
    """Without the shared os-suite-ai.json the app keeps its own choice and names its keys after itself."""
    from backend import platform_os
    for name, fn in REAL_KEY_FUNCS.items():             # the real key functions, on a fake secret store
        monkeypatch.setattr(providers, name, fn)
    store = {}
    monkeypatch.setattr(platform_os, "secret_get", lambda s, a=None: store.get(s))
    monkeypatch.setattr(platform_os, "secret_set", lambda s, a, v: store.__setitem__(s, v))
    monkeypatch.setattr(providers, "SHARED", False)
    monkeypatch.setattr(providers, "APP_NAME", "CommerceOS")
    monkeypatch.setattr(providers, "SETTINGS_FILE", tmp_path / "data" / "ai.json")
    providers._cache.clear()
    providers.set_key("gemini", "AIzaTESTKEY123456")
    assert store == {"CommerceOS · Google Gemini": "AIzaTESTKEY123456"}
    providers.save_settings({"primary": {"provider": "gemini", "model": "gemini-2.5-flash"}, "backup": None})
    assert (tmp_path / "data" / "ai.json").exists()
    assert providers.chain() == [("gemini", "gemini-2.5-flash", "AIzaTESTKEY123456")]


def test_off_mac_a_refused_curl_retries_like_a_browser(monkeypatch):
    calls = []
    monkeypatch.setattr(net.platform_os, "IS_MAC", False)
    monkeypatch.setattr(net, "_has_cffi", lambda: True)
    monkeypatch.setattr(net, "_curl_once", lambda url, *a: calls.append("curl") or (403, b"cloudflare", ""))
    monkeypatch.setattr(net, "_browser_like_once", lambda url, *a: calls.append("cffi") or (200, b"<html>ok</html>", ""))
    assert net.curl_get("https://www.akakce.com/arama/?q=x") == (200, b"<html>ok</html>")
    assert calls == ["curl", "cffi"]
    monkeypatch.setattr(net.platform_os, "IS_MAC", True)          # macOS keeps curl's answer
    calls.clear()
    assert net.curl_get("https://www.akakce.com/arama/?q=x") == (403, b"cloudflare")
    assert calls == ["curl"]


# ---------------------------------------------------------------- backup

def test_backup_without_passphrase_stays_local_and_quiet(monkeypatch, tmp_path):
    from backend import backup, config
    (tmp_path / "icloud").mkdir()
    monkeypatch.setattr(config, "BACKUP_ICLOUD", True)
    client().get("/api/sites")                                     # creates the database
    assert backup.run().exists()
    assert not (tmp_path / "icloud" / "CommerceOS Yedek").exists()   # nothing sent to the cloud
    assert backup.warning() is None                                 # the cloud copy is optional


def test_backup_warns_only_when_the_chosen_cloud_copy_fails(monkeypatch, tmp_path):
    from backend import backup, config
    (tmp_path / "icloud").mkdir()
    monkeypatch.setattr(config, "BACKUP_ICLOUD", True)
    monkeypatch.setattr(backup, "passphrase", lambda: "en-az-8-karakter")
    monkeypatch.setattr(backup, "encrypt", lambda *a: (_ for _ in ()).throw(RuntimeError("disk dolu")))
    client().get("/api/sites")
    backup.run()
    assert "disk dolu" in backup.warning()
