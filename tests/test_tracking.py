from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from backend import akakce, backup, config, db, scheduler, tracking
from tests.conftest import fixture
from tests.test_commerce import client, fake_akakce

PATH = "/bluetooth-kulaklik/en-ucuz-airpods-pro-2-nesil-type-c-fiyati,301549184.html"


def offers(*pairs):
    return [{"store": s, "price": p, "url": f"https://www.akakce.com/r/?{s}"} for s, p in pairs]


def feed(monkeypatch, *rounds):
    """Each call to akakce.offers returns the next round of offers."""
    seq = list(rounds)
    monkeypatch.setattr(akakce, "offers", lambda path: {"title": "x", "url": "", "offers": seq.pop(0)})


def add_site(name, domain):
    db.execute("INSERT INTO sites(name,url,domain,added_at) VALUES(?,?,?,'2026-01-01')", (name, f"https://{domain}", domain))


def test_parse_rating():
    o = {x["store"]: x for x in akakce.parse_product(fixture("akakce_product.html"))}
    assert o["A101"]["rating"] == 7.1 and o["A101"]["reviews"] == 94
    assert o["Trendyol"]["rating"] is None


def test_drop_alert_without_target(monkeypatch):
    feed(monkeypatch, offers(("A", 1000), ("B", 1100)), offers(("A", 995)), offers(("B", 900)), offers(("B", 950)))
    item = tracking.add(PATH, "AirPods")
    assert item["last_price"] == 1000 and item["first_price"] == 1000 and tracking.unseen_count() == 0
    tracking.check(item["id"])            # -0.5 %: below DROP_MIN_PCT, no alert
    assert tracking.unseen_count() == 0
    tracking.check(item["id"])            # 995 → 900
    a = tracking.alerts()[0]
    assert (a["kind"], a["old_price"], a["new_price"], a["store"]) == ("drop", 995, 900, "B")
    tracking.check(item["id"])            # rises: nothing
    got = tracking.get(item["id"])
    assert tracking.unseen_count() == 1 and got["low_price"] == 900 and got["change_pct"] == -5.0
    assert [p["price"] for p in got["history"]] == [1000, 995, 900, 950]


def test_target_alert_only_when_crossing(monkeypatch):
    feed(monkeypatch, offers(("A", 1200)), offers(("A", 990)), offers(("A", 980)), offers(("A", 1100)), offers(("A", 999)))
    item = tracking.add(PATH, "AirPods", target_price=1000)
    for _ in range(4):
        tracking.check(item["id"])
    kinds = [(a["kind"], a["new_price"]) for a in tracking.alerts()][::-1]
    assert kinds == [("target", 990), ("target", 999)]     # 980 was already below: no repeat
    assert tracking.get(item["id"])["at_target"]


def test_scope_mine_counts_only_my_stores(monkeypatch):
    add_site("Hepsiburada", "hepsiburada.com")
    feed(monkeypatch, offers(("idefix", 900), ("Hepsiburada", 1000)), offers(("idefix", 800)))
    item = tracking.add(PATH, "AirPods", scope="mine")
    assert item["last_price"] == 1000 and item["last_store"] == "Hepsiburada" and item["site_id"]
    tracking.check(item["id"])            # only a foreign store left
    got = tracking.get(item["id"])
    assert got["last_price"] == 1000 and got["last_error"] == "Sitelerinde şu an teklif yok"


def test_add_validation_and_duplicates(monkeypatch):
    feed(monkeypatch, offers(("A", 1)))
    with pytest.raises(tracking.TrackError):
        tracking.add("https://evil/", "x")
    with pytest.raises(tracking.TrackError):
        tracking.add(PATH, "x", target_price=-5)
    tracking.add(PATH, "x")
    with pytest.raises(tracking.TrackError):
        tracking.add(PATH, "x")


def test_akakce_down_keeps_item_with_error(monkeypatch):
    def down(path):
        raise akakce.AkakceError("Akakçe yanıt vermedi (HTTP 503)")
    monkeypatch.setattr(akakce, "offers", down)
    item = tracking.add(PATH, "AirPods")
    assert item["last_price"] is None and "503" in item["last_error"]
    monkeypatch.setattr(tracking, "GAP_SECONDS", 0)
    assert tracking.check_all() and tracking.run_state()["errors"] == 1


def test_api_track_from_search_reuses_offers(monkeypatch):
    n = {"search": 0, "offers": 0}
    fake_akakce(monkeypatch, n)
    with client() as c:
        r = c.get("/api/search", params={"q": "airpods pro 2"}).json()
        assert r["tracked_id"] is None
        item = c.post("/api/tracked", json={"path": r["product"]["path"], "title": r["product"]["title"],
                                            "image": "https://cdn.akakce.com/x.jpg", "target_price": 12000}).json()
        assert n["offers"] == 1 and item["last_price"] == 12837.02          # no second Akakçe request
        assert c.get("/api/search", params={"q": "airpods pro 2"}).json()["tracked_id"] == item["id"]
        assert c.get("/api/search", params={"q": "airpods pro 2", "scope": "mine"}).json()["tracked_id"] is None
        assert c.patch(f"/api/tracked/{item['id']}", json={"clear_target": True}).json()["target_price"] is None
        assert c.patch(f"/api/tracked/{item['id']}", json={"target_price": 11000}).json()["target_price"] == 11000
        st = c.get("/api/status").json()
        assert st["tracking"]["items"] == 1 and st["alerts_unseen"] == 0
        g = c.get("/api/glance").json()
        assert g == {"tracked": 1, "alerts_unseen": 0, "latest_alert": None, "orders_open": 0}
        c.delete(f"/api/tracked/{item['id']}")
        assert c.get("/api/tracked").json() == [] and db.rows("SELECT * FROM price_history") == []


def test_alerts_api_seen(monkeypatch):
    feed(monkeypatch, offers(("A", 1000)), offers(("A", 800)))
    item = tracking.add(PATH, "AirPods")
    tracking.check(item["id"])
    with client() as c:
        a = c.get("/api/alerts").json()
        assert a["unseen"] == 1 and a["items"][0]["new_price"] == 800
        assert c.get("/api/glance").json()["latest_alert"]["new_price"] == 800
        c.post("/api/alerts/seen")
        assert c.get("/api/alerts").json()["unseen"] == 0


def test_missed_check(monkeypatch):
    tz = ZoneInfo(config.TIMEZONE)
    now = datetime(2026, 10, 22, 10, 0, tzinfo=tz)
    assert scheduler.last_slot(now) == datetime(2026, 10, 22, 9, 0, tzinfo=tz)
    assert scheduler.last_slot(datetime(2026, 10, 22, 7, 0, tzinfo=tz)) == datetime(2026, 10, 21, 18, 0, tzinfo=tz)
    assert not scheduler.missed_check(now)                 # nothing tracked
    feed(monkeypatch, offers(("A", 1)))
    tracking.add(PATH, "x")
    assert scheduler.missed_check(now)
    db.set_meta("track_last_run", datetime(2026, 10, 22, 9, 0, 5, tzinfo=tz).isoformat())
    assert not scheduler.missed_check(now)


def test_backup_writes_local_copy():
    db.set_meta("x", "1")
    target = backup.run()
    assert target.exists() and target.name.startswith("commerceos-")
    assert not backup.CLOUD_DIR.exists()                  # no passphrase: nothing goes to iCloud


def test_price_check_from_earlier_searches_and_tracking():
    from backend import api
    path = PATH
    def save(day, low):
        db.execute("INSERT INTO searches(query, scope, kind, product, result, created_at) VALUES(?,?,?,?,?,?)",
                   ("airpods", "all", "quick", "", db.dumps({"product": {"path": path}, "offers": [{"price": low}]}),
                    f"2026-10-{day:02d}T10:00:00+00:00"))
    assert api._price_check(path, 1000, "2026-10-20T10:00:00+00:00") is None          # nothing known yet
    save(10, 1200)
    save(15, 1100)
    c = api._price_check(path, 1000, "2026-10-20T10:00:00+00:00")
    assert c["verdict"] == "lowest" and c["days"] == 11 and c["points"] == 2 and c["low"] == 1100   # 10th → 20th
    assert api._price_check(path, 1300, "2026-10-20T10:00:00+00:00")["verdict"] == "above"
    assert api._price_check(path, 1110, "2026-10-20T10:00:00+00:00")["verdict"] == "below"    # avg 1150: -3 %
    assert api._price_check(path, 1140, "2026-10-20T10:00:00+00:00")["verdict"] == "typical"  # -1 %
