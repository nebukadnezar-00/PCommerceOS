import pytest

from backend import mailbox, orders, providers
from backend.mailbox import MailError
from tests.test_commerce import client

GOOD = "abcd efgh ijkl mnop"


@pytest.fixture
def fake(monkeypatch):
    """A fake Gmail (accepts only GOOD) and a fake Keychain: nothing real is touched."""
    kc, scans = {}, []
    def login(user, pw):
        if pw != GOOD.replace(" ", ""):
            raise MailError("Şifre kabul edilmedi: adresi ve uygulama şifresini kontrol et")
        return {"all": '"[Gmail]/Tüm Postalar"', "spam": '"[Gmail]/Spam"', "trash": '"[Gmail]/Çöp Kutusu"'}
    monkeypatch.setattr(mailbox, "_login", login)
    monkeypatch.setattr(mailbox, "_keychain_write", lambda u, p: kc.update(user=u, pw=p))
    monkeypatch.setattr(mailbox, "_keychain_delete", lambda: kc.clear())
    monkeypatch.setattr(mailbox, "credentials", lambda: (kc["user"], kc["pw"]) if kc else None)
    monkeypatch.setattr(mailbox, "account", lambda: kc.get("user"))
    monkeypatch.setattr(orders, "start_scan", lambda reason="manual": scans.append(reason) or True)
    monkeypatch.setattr(providers, "is_local", lambda request: True)
    return kc, scans


def test_wrong_password_writes_nothing(fake):
    kc, scans = fake
    with client() as c:
        r = c.put("/api/settings/mail", json={"user": "ali@gmail.com", "password": "qwertyuiopasdfgh"})
        assert r.status_code == 400 and "kabul edilmedi" in r.json()["detail"]
        assert kc == {} and scans == []


def test_saving_tests_first_then_stores_and_scans(fake):
    kc, scans = fake
    with client() as c:
        t = c.post("/api/settings/mail/test", json={"user": "ali@gmail.com", "password": GOOD}).json()
        assert t["ok"] and "Spam ve Çöp kutusu" in t["message"] and kc == {}
        r = c.put("/api/settings/mail", json={"user": "ali@gmail.com", "password": GOOD}).json()
        assert kc == {"user": "ali@gmail.com", "pw": "abcdefghijklmnop"} and scans == ["setup"]
        assert r["configured"] and r["user"] == "al***@gmail.com"
        assert GOOD.replace(" ", "") not in str(r) and GOOD not in str(c.get("/api/settings/mail").json())


def test_not_an_app_password_or_address(fake):
    with pytest.raises(MailError, match="16 harfli"):
        mailbox.test("ali@gmail.com", "benimGmailSifrem1!")
    with pytest.raises(MailError, match="Gmail adresi"):
        mailbox.test("ali", GOOD)


def test_remove_keeps_orders(fake, monkeypatch):
    kc, _ = fake
    mailbox.save("ali@gmail.com", GOOD)
    assert mailbox.configured()
    with client() as c:
        assert c.delete("/api/settings/mail").json()["configured"] is False
    assert kc == {}


def test_writes_only_from_this_mac(fake, monkeypatch):
    monkeypatch.setattr(providers, "is_local", lambda request: False)
    with client() as c:
        assert c.put("/api/settings/mail", json={"user": "ali@gmail.com", "password": GOOD}).status_code == 403
        assert c.delete("/api/settings/mail").status_code == 403
        assert c.get("/api/settings/mail").json()["editable"] is False
