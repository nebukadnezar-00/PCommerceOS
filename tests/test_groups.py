import sqlite3

import pytest

from backend import ai, akakce, config, db, sites
from tests.test_commerce import client, fake_akakce


def add_site(name, domain, group_id=None):
    return db.execute("INSERT INTO sites(name,url,domain,group_id,added_at) VALUES(?,?,?,?,'2026-01-01')",
                      (name, f"https://{domain}", domain, group_id))


def test_group_crud_and_delete_keeps_sites():
    with client() as c:
        g = c.post("/api/groups", json={"name": " Elektronik "}).json()
        assert g["name"] == "Elektronik" and g["collapsed"] == 0
        assert c.post("/api/groups", json={"name": "elektronik"}).status_code == 400
        assert c.post("/api/groups", json={"name": "Diğer"}).status_code == 400
        assert c.post("/api/groups", json={"name": "  "}).status_code == 400
        hb = add_site("Hepsiburada", "hepsiburada.com", g["id"])
        assert c.patch(f"/api/groups/{g['id']}", json={"name": "Teknoloji", "collapsed": True}).json() \
            == {"id": g["id"], "name": "Teknoloji", "position": 1, "collapsed": 1}
        c.delete(f"/api/groups/{g['id']}")
        assert c.get("/api/groups").json() == []
        assert sites.get(hb)["group_id"] is None          # the store stays, in "Diğer"


def test_move_between_groups_and_order():
    a, b, d = add_site("A", "a.com"), add_site("B", "b.com"), add_site("D", "d.com")
    with client() as c:
        g = c.post("/api/groups", json={"name": "Market"}).json()
        g2 = c.post("/api/groups", json={"name": "Seyahat"}).json()
        assert c.put("/api/sites/order", json={"ids": [d, a], "group_id": g["id"], "regroup": True}).json()["ok"]
        listed = c.get("/api/sites").json()
        assert [(s["name"], s["group_id"]) for s in listed] == [("D", g["id"]), ("A", g["id"]), ("B", None)]
        c.put("/api/groups/order", json={"ids": [g2["id"], g["id"]]})
        c.put("/api/sites/order", json={"ids": [b], "group_id": g2["id"], "regroup": True})
        assert [s["name"] for s in c.get("/api/sites").json()] == ["B", "D", "A"]   # groups' order first
        assert c.put("/api/sites/order", json={"ids": [a], "group_id": 999, "regroup": True}).status_code == 400
        assert c.put("/api/sites/order", json={"ids": [a, d]}).json()["ok"]        # plain reorder keeps groups
        assert sites.get(a)["group_id"] == g["id"]


def test_group_scope_narrows_quick_results(monkeypatch):
    n = {"search": 0, "offers": 0}
    fake_akakce(monkeypatch, n)
    with client() as c:
        g = c.post("/api/groups", json={"name": "Elektronik"}).json()
        add_site("Hepsiburada", "hepsiburada.com", g["id"])
        add_site("Trendyol", "trendyol.com")
        mine = c.get("/api/search", params={"q": "airpods pro 2", "scope": "mine"}).json()
        assert {o["store"] for o in mine["offers"]} == {"Hepsiburada", "Trendyol"}
        grp = c.get("/api/search", params={"q": "airpods pro 2", "scope": f"mine:{g['id']}"}).json()
        assert {o["store"] for o in grp["offers"]} == {"Hepsiburada"} and grp["scope"] == f"mine:{g['id']}"
        assert n["offers"] == 1                                                     # same cached page
        assert c.get("/api/search", params={"q": "airpods pro 2", "scope": "mine:999"}).status_code == 400
        assert c.get("/api/search", params={"q": "airpods pro 2", "scope": "mine:x"}).status_code == 400


def test_group_scope_in_deep_prompt(monkeypatch):
    seen = {}

    def fake_deep(q, scope, my):
        seen["scope"], seen["names"] = scope, [s["name"] for s in my]
        seen["text"] = ai._scope_text(scope, my)
        return {"summary": "", "offers": [], "sources": [], "tokens": 10}
    monkeypatch.setattr(ai, "deep_search", fake_deep)
    with client() as c:
        g = c.post("/api/groups", json={"name": "Market"}).json()
        add_site("Migros", "migros.com.tr", g["id"])
        add_site("Teknosa", "teknosa.com")
        c.post("/api/search/deep", json={"q": "deterjan", "scope": f"mine:{g['id']}"})
        assert seen["names"] == ["Migros"] and "SADECE" in seen["text"] and "teknosa" not in seen["text"]
        g2 = c.post("/api/groups", json={"name": "Boş"}).json()
        assert c.post("/api/search/deep", json={"q": "deterjan", "scope": f"mine:{g2['id']}"}).status_code == 400


def test_tracking_with_group_scope_tracks_as_mine(monkeypatch):
    n = {"search": 0, "offers": 0}
    fake_akakce(monkeypatch, n)
    with client() as c:
        g = c.post("/api/groups", json={"name": "Elektronik"}).json()
        add_site("Hepsiburada", "hepsiburada.com", g["id"])
        r = c.get("/api/search", params={"q": "airpods pro 2", "scope": f"mine:{g['id']}"}).json()
        item = c.post("/api/tracked", json={"path": r["product"]["path"], "title": "x", "scope": f"mine:{g['id']}"}).json()
        assert item["scope"] == "mine"
        again = c.get("/api/search", params={"q": "airpods pro 2", "scope": f"mine:{g['id']}"}).json()
        assert again["tracked_id"] == item["id"]


def test_old_database_gets_group_column(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE sites (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT NOT NULL, "
                "domain TEXT NOT NULL UNIQUE, search_url TEXT, logo TEXT, position INTEGER, added_at TEXT NOT NULL)")
    con.execute("INSERT INTO sites(name,url,domain,added_at) VALUES('n11','https://n11.com','n11.com','2026-01-01')")
    con.commit()
    con.close()
    db.close()
    monkeypatch.setattr(config, "DB_PATH", path)
    db.init()
    assert sites.all_sites()[0]["group_id"] is None and sites.all_sites()[0]["name"] == "n11"


def test_one_order_across_groups_for_the_strip():
    a, b, d = add_site("A", "a.com"), add_site("B", "b.com"), add_site("D", "d.com")
    with client() as c:
        g = c.post("/api/groups", json={"name": "Market"}).json()
        c.put("/api/sites/order", json={"ids": [d], "group_id": g["id"], "regroup": True})
        # the strip puts B first, across groups; nobody changes group
        assert c.put("/api/sites/order", json={"ids": [b, a, d]}).json()["ok"]
        by_pos = sorted(c.get("/api/sites").json(), key=lambda s: s["position"])
        assert [s["name"] for s in by_pos] == ["B", "A", "D"] and sites.get(d)["group_id"] == g["id"]
        # the drawer reorders one group: the other stores keep their slots
        e = add_site("E", "e.com")
        c.put("/api/sites/order", json={"ids": [e, d], "group_id": g["id"], "regroup": True})
        by_pos = sorted(c.get("/api/sites").json(), key=lambda s: s["position"])
        assert [s["name"] for s in by_pos] == ["B", "A", "E", "D"]


def test_old_per_group_positions_are_renumbered():
    a, b = add_site("A", "a.com"), add_site("B", "b.com")
    db.execute("UPDATE sites SET position=1")
    sites.normalize_positions()
    assert sorted(s["position"] for s in sites.all_sites()) == [1, 2]
