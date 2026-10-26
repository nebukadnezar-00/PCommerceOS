"""Rehber: each step counts as done from what the user actually set up or used."""
from fastapi.testclient import TestClient

from backend import db, main, mailbox, providers, sites


def client():
    return TestClient(main.app, base_url="http://127.0.0.1:8002")


def done(c):
    return {s["id"] for s in c.get("/api/guide").json()["steps"] if s["done"]}


def test_steps_follow_real_use(monkeypatch, fake_keychain):
    monkeypatch.setattr(mailbox, "configured", lambda: False)
    with client() as c:
        g = c.get("/api/guide").json()
        assert [s["id"] for s in g["steps"]] == ["sites", "ai", "search", "track", "mail"]
        assert done(c) == set() and not g["seen"]

        db.execute("INSERT INTO searches(query, scope, kind, product, result, tokens, created_at) VALUES(?,?,?,?,?,?,?)",
                   ("airpods", "all", "quick", "", "{}", 0, db.now_iso()))
        assert done(c) == {"search"}
        db.execute("INSERT INTO tracked(path, title, scope, created_at) VALUES(?,?,?,?)", ("/x.html", "X", "all", db.now_iso()))
        assert done(c) == {"search", "track"}

        fake_keychain["OS Suite · Google Gemini"] = "AIzaTESTKEY123456"
        providers.save_settings({"primary": {"provider": "gemini", "model": "gemini-2.5-flash"}, "backup": None})
        monkeypatch.setattr(mailbox, "configured", lambda: True)
        assert done(c) == {"search", "track", "ai", "mail"}


def test_site_changes_and_tamam_finish_the_first_step(monkeypatch):
    monkeypatch.setattr(mailbox, "configured", lambda: False)
    sites.seed_defaults()
    ids = [s["id"] for s in sites.all_sites()]
    with client() as c:
        assert "sites" not in done(c)
        assert c.put("/api/sites/order", json={"ids": ids[::-1]}).status_code == 200
        assert "sites" in done(c)
        db.execute("DELETE FROM meta WHERE key='guide'")
        assert "sites" in {s["id"] for s in c.put("/api/guide", json={"done": "sites"}).json()["steps"] if s["done"]}
        assert c.put("/api/guide", json={"done": "nope"}).status_code == 400


def test_seen_is_kept(monkeypatch):
    monkeypatch.setattr(mailbox, "configured", lambda: False)
    with client() as c:
        c.put("/api/guide", json={"seen": True})
        assert c.get("/api/guide").json()["seen"]
