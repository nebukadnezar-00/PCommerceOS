"""Shared fixtures: every test runs against a throw-away SQLite file and never touches the network."""
import socket
from pathlib import Path

import pytest

from backend import backup, config, db, health, mailbox, net, scheduler, sites, stores

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    real_connect = socket.socket.connect
    def connect(sock, address, *a, **k):
        # loopback only: on Windows asyncio's event loop wires itself up through a localhost socket pair
        if isinstance(address, tuple) and address and address[0] in ("127.0.0.1", "::1", "localhost"):
            return real_connect(sock, address, *a, **k)
        raise RuntimeError("Testler ağa çıkamaz")
    def guard(*a, **k):
        raise RuntimeError("Testler ağa çıkamaz")
    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket, "create_connection", guard)
    # address checks resolve names; answer with a public address unless a test says otherwise
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))])
    # curl runs outside Python's socket guard: tests never start it
    def no_curl(*a, **k):
        raise RuntimeError("Testler curl çalıştıramaz")
    monkeypatch.setattr(net.subprocess, "run", no_curl)
    monkeypatch.setattr(stores, "search", lambda q: [])          # the third source finds nothing unless a test says so
    monkeypatch.setattr(health, "_state", {"ok": None, "checked_at": 0.0, "error": None, "running": False})
    monkeypatch.setattr(health, "_probe", lambda: None)
    monkeypatch.setattr(health, "_parse", {"ok": None, "checked_at": 0.0, "error": None, "running": False})
    monkeypatch.setattr(health, "_parse_probe", lambda: None)


@pytest.fixture(autouse=True)
def fake_keychain(tmp_path, monkeypatch):
    """Tests never touch the real Keychain, the shared AI settings or FinanceOS's .env."""
    from backend import providers
    store = {}
    monkeypatch.setattr(providers, "keychain_get", lambda s: store.get(s))
    monkeypatch.setattr(providers, "keychain_set", lambda s, v: store.__setitem__(s, v))
    monkeypatch.setattr(providers, "keychain_delete", lambda s: store.pop(s, None))
    monkeypatch.setattr(providers, "SETTINGS_FILE", tmp_path / "os-suite-ai.json")
    monkeypatch.setattr(providers, "SHARED", True)            # the shared layout, wherever tests run
    monkeypatch.setattr(providers, "_env_gemini", lambda name="GEMINI_API_KEY": "")
    providers._cache.clear()
    return store


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    db.close()
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(sites, "LOGO_DIR", tmp_path / "logos")
    monkeypatch.setattr(backup, "LOCAL_DIR", tmp_path / "backups")
    monkeypatch.setattr(backup, "CLOUD_DIR", tmp_path / "icloud" / "CommerceOS Yedek")
    monkeypatch.setattr(backup, "SETTINGS_FILE", tmp_path / "backup.json")
    monkeypatch.setattr(backup, "passphrase", lambda: None)       # tests never read the Keychain
    monkeypatch.setattr(backup, "_cloud_error", None)
    monkeypatch.setattr(mailbox, "credentials", lambda: None)     # nor the mail password
    monkeypatch.setattr(mailbox, "_configured_cache", None)
    monkeypatch.setattr(scheduler, "start", lambda: None)         # no jobs, no catch-up in tests
    monkeypatch.setattr(scheduler, "stop", lambda: None)
    db.init()
    db.set_meta("seeded", "test")                      # the app's startup must not add default stores
    monkeypatch.setattr(sites, "missing_logos", lambda: None)
    yield tmp_path / "test.db"
    db.close()


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def fake_secrets(monkeypatch):
    """Tests never read or write the real secret store (Keychain / Credential Manager)."""
    from backend import platform_os
    store = {}
    monkeypatch.setattr(platform_os, "secret_get", lambda s, a=None: store.get((s, a or "os-suite")))
    monkeypatch.setattr(platform_os, "secret_set", lambda s, a, v: store.__setitem__((s, a or "os-suite"), v))
    monkeypatch.setattr(platform_os, "secret_delete", lambda s, a=None: store.pop((s, a or "os-suite"), None))
    monkeypatch.setattr(platform_os, "notify", lambda title, message: None)
    return store
