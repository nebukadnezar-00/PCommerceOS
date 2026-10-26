"""⚙ Ayarlar → Yedek: passphrase (write-only), folder, run now; writes only from this computer."""
import pytest
from fastapi.testclient import TestClient

from backend import backup, db, main, providers

REAL_PASSPHRASE = backup.passphrase           # conftest stubs it for every test


@pytest.fixture
def client(monkeypatch, fake_secrets):
    monkeypatch.setattr(providers, "is_local", lambda request: True)
    monkeypatch.setattr(backup, "passphrase", REAL_PASSPHRASE)
    return TestClient(main.app, base_url="http://localhost")


def test_passphrase_is_stored_never_returned_and_unlocks_the_cloud_copy(client, fake_secrets):
    b = client.get("/api/settings/backup").json()
    assert not b["passphrase_set"] and b["editable"] and b["store"]
    assert client.put("/api/settings/backup", json={"passphrase": "kısa"}).status_code == 400
    r = client.put("/api/settings/backup", json={"passphrase": "uzun bir şifre"})
    assert r.status_code == 200 and r.json()["passphrase_set"] and "uzun" not in r.text
    assert fake_secrets[("CommerceOS Yedek", "os-suite")] == "uzun bir şifre"
    db.set_meta("x", "1")
    backup.CLOUD_DIR.parent.mkdir()                   # the cloud drive is there
    r = client.post("/api/settings/backup/run").json()
    assert r["message"].startswith("Yedeklendi") and r["last_local"] and r["last_cloud"]
    enc = next(backup.CLOUD_DIR.glob("commerceos-*.db.enc"))
    assert b"SQLite format" not in enc.read_bytes()[:64]


def test_reuses_the_financeos_passphrase(client, fake_secrets):
    fake_secrets[("FinanceOS Yedek", "os-suite")] = "ortak şifre 1"
    assert client.get("/api/settings/backup").json()["passphrase_set"]


def test_folder_choice(client, tmp_path):
    r = client.put("/api/settings/backup", json={"dir": str(tmp_path / "Dropbox" / "Yedek")})
    assert r.status_code == 400                       # its parent does not exist
    (tmp_path / "Dropbox").mkdir()
    monkey = backup.CLOUD_DIR
    backup.CLOUD_DIR = None
    try:
        r = client.put("/api/settings/backup", json={"dir": str(tmp_path / "Dropbox" / "Yedek")}).json()
        assert r["custom_dir"] and r["cloud_dir"].endswith("Yedek")
        assert not client.put("/api/settings/backup", json={"default_dir": True}).json()["custom_dir"]
    finally:
        backup.CLOUD_DIR = monkey


def test_writes_only_from_this_computer(monkeypatch, fake_secrets):
    monkeypatch.setattr(providers, "is_local", lambda request: False)
    c = TestClient(main.app, base_url="http://localhost")
    assert c.get("/api/settings/backup").json()["editable"] is False
    assert c.put("/api/settings/backup", json={"passphrase": "uzun bir şifre"}).status_code == 403
    assert c.post("/api/settings/backup/run").status_code == 403
    assert fake_secrets == {}
