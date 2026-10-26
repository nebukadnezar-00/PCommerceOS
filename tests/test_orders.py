from datetime import datetime, timezone

from backend import db, mailbox, orders, scheduler
from tests.conftest import FIXTURES
from tests.test_commerce import client

REAL_CREDENTIALS = mailbox.credentials   # conftest stubs it for every test


def raw(name):
    return (FIXTURES / "orders" / f"{name}.eml").read_bytes()


def add_site(name, domain):
    return db.execute("INSERT INTO sites(name,url,domain,added_at) VALUES(?,?,?,'2026-01-01')",
                      (name, f"https://www.{domain}", domain))


def my_sites():
    return db.rows("SELECT * FROM sites")


AFTER = datetime(2026, 10, 21, tzinfo=timezone.utc)


def test_amazon_order_email():
    add_site("Amazon", "amazon.com.tr")
    p = orders.parse(raw("amazon_ordered"), my_sites())
    assert p["store"] == "Amazon" and p["status"] == "alindi"       # the step list in the body does not count
    assert p["order_no"] == "403-0000000-1111111"
    assert p["title"].startswith("Logitech Pebble 2 Set") and p["title"].endswith("Siyah")
    assert p["total"] == 1974.0 and p["tracking_url"] is None


def test_amazon_emails_make_one_order_that_follows_the_newest():
    add_site("Amazon", "amazon.com.tr")
    # arriving out of order must not move the status backwards
    assert orders.ingest([raw("amazon_shipped"), raw("amazon_ordered")], my_sites()) == 2
    [o] = orders.all_orders(AFTER)
    assert o["status"] == "kargoda" and o["open"] and o["total"] == 1974.0
    assert "progress-tracker" in o["tracking_url"]
    assert o["ordered_at"].startswith("2026-10-06T11:07")
    orders.ingest([raw("amazon_delivered")], my_sites())
    [o] = orders.all_orders(AFTER)
    assert o["status"] == "teslim" and not o["open"] and o["delivered_at"].startswith("2026-10-07")
    assert [t["status"] for t in o["timeline"]] == ["alindi", "kargoda", "teslim"]
    # the same email again changes nothing
    assert orders.ingest([raw("amazon_delivered")], my_sites()) == 0


def test_delivered_orders_move_to_the_archive_after_30_days():
    add_site("Amazon", "amazon.com.tr")
    orders.ingest([raw("amazon_ordered"), raw("amazon_delivered")], my_sites())
    nov1, nov10 = datetime(2026, 11, 1, tzinfo=timezone.utc), datetime(2026, 11, 10, tzinfo=timezone.utc)
    assert len(orders.all_orders(nov1)) == 1 and orders.archived(nov1) == []
    assert orders.all_orders(nov10) == []
    [a] = orders.archived(nov10)
    assert a["status"] == "teslim" and a["order_no"] == "403-0000000-1111111"


def test_deleted_order_stays_deleted_when_more_mail_arrives():
    add_site("Amazon", "amazon.com.tr")
    orders.ingest([raw("amazon_shipped")], my_sites())
    [o] = orders.all_orders(AFTER)
    orders.update(o["id"], hidden=True)
    orders.ingest([raw("amazon_delivered"), raw("amazon_shipped")], my_sites())   # later + the same email again
    later = datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert orders.all_orders(AFTER) == [] and orders.archived(later) == []
    assert db.one("SELECT status, hidden FROM orders") == {"status": "teslim", "hidden": 1}


def test_html_only_email_with_carrier_tracking():
    add_site("Trendyol", "trendyol.com")
    p = orders.parse(raw("trendyol_shipped"), my_sites())
    assert p["status"] == "kargoda" and p["order_no"] == "987654321"
    assert p["carrier"] == "Aras Kargo" and p["tracking_no"] == "1234567890123"
    assert p["tracking_url"] == "https://kargotakip.araskargo.com.tr/mainpage.aspx?code=1234567890123"
    assert p["total"] == 3499.9 and p["title"] == "Philips Airfryer XL"


def test_newsletters_and_other_stores_are_skipped():
    add_site("Trendyol", "trendyol.com")
    assert orders.parse(raw("newsletter"), my_sites()) is None
    assert orders.parse(raw("amazon_ordered"), my_sites()) is None          # Amazon is not one of my stores
    assert orders.ingest([raw("newsletter")], my_sites()) == 0
    assert db.one("SELECT order_id FROM order_mails WHERE message_id='<newsletter@test>'") == {"order_id": None}


def test_forwarded_email_is_matched_by_its_body():
    add_site("Amazon", "amazon.com.tr")
    p = orders.parse(raw("forwarded"), my_sites())
    assert p["store"] == "Amazon" and p["status"] == "kargoda" and p["order_no"] == "403-2222222-3333333"
    assert p["title"] == "Dyson V15 Detect"


def test_marked_delivered_by_hand_stays_delivered():
    add_site("Amazon", "amazon.com.tr")
    orders.ingest([raw("amazon_ordered")], my_sites())
    [o] = orders.all_orders(AFTER)
    orders.update(o["id"], delivered=True)
    orders.ingest([raw("amazon_shipped")], my_sites())
    [o] = orders.all_orders(AFTER)
    assert o["status"] == "teslim" and o["manual"]
    orders.update(o["id"], delivered=False)                   # "Geri aç": the emails decide again
    [o] = orders.all_orders(AFTER)
    assert o["status"] == "kargoda" and o["open"] and not o["manual"] and not o["delivered_at"]
    orders.update(o["id"], hidden=True)
    assert orders.all_orders(AFTER) == []


def test_scan_reads_only_new_mail_and_records_errors(monkeypatch):
    add_site("Amazon", "amazon.com.tr")
    seen = {}

    def fake_fetch(domains, days, known):
        seen.update(domains=domains, days=days, known=set(known))
        return [raw("amazon_ordered")]
    monkeypatch.setattr(mailbox, "fetch", fake_fetch)
    assert orders.scan() is True
    assert seen["domains"] == ["amazon.com.tr"] and seen["days"] == orders.FIRST_SCAN_DAYS
    assert orders.open_count() == 1 and db.get_meta("orders_last_scan")
    orders.scan()
    assert seen["days"] == 2 and "<amazon_ordered@test>" in seen["known"]

    def broken(*a):
        raise mailbox.MailError("E-posta girişi reddedildi")
    monkeypatch.setattr(mailbox, "fetch", broken)
    orders.scan()
    assert orders.state()["error"] == "E-posta girişi reddedildi"


def test_api_lists_orders_and_explains_setup(monkeypatch):
    add_site("Amazon", "amazon.com.tr")
    c = client()
    r = c.get("/api/orders").json()
    assert r["state"]["configured"] is False and r["state"]["service"] == "CommerceOS Gmail"
    assert r["items"] == [] and r["archive"] == []
    assert c.post("/api/orders/scan").status_code == 400
    orders.ingest([raw("amazon_shipped")], my_sites())
    r = c.get("/api/orders").json()
    assert r["items"][0]["status"] == "kargoda" and r["state"]["open"] == 1
    assert c.get("/api/glance").json()["orders_open"] == 1
    assert c.get("/api/status").json()["orders"]["open"] == 1
    oid = r["items"][0]["id"]
    assert c.patch(f"/api/orders/{oid}", json={"delivered": True}).json()["status"] == "teslim"
    assert c.patch("/api/orders/999", json={"hidden": True}).status_code == 404


def test_missed_order_scan_is_caught_up():
    tz = scheduler.ZoneInfo("Europe/Istanbul")
    now = datetime(2026, 10, 23, 19, 0, tzinfo=tz)
    assert scheduler.missed_orders(now)
    db.set_meta("orders_last_scan", datetime(2026, 10, 23, 18, 5, tzinfo=tz).isoformat())
    assert not scheduler.missed_orders(now)


def test_keychain_reading(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(mailbox.platform_os, "IS_MAC", True)
    out = SimpleNamespace(returncode=0, stdout='keychain: "x"\n    "acct"<blob>="ben@gmail.com"\n',
                          stderr='password: "abcd efgh ijkl mnop"\n')
    monkeypatch.setattr(mailbox.subprocess, "run", lambda *a, **k: out)
    assert REAL_CREDENTIALS() == ("ben@gmail.com", "abcdefghijklmnop")
    monkeypatch.setattr(mailbox.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=44, stdout="", stderr=""))
    assert REAL_CREDENTIALS() is None


def test_prices_in_both_decimal_styles():
    assert orders._price("622.84") == 622.84          # Amazon TR
    assert orders._price("622.8399999999999") == 622.84
    assert orders._price("3.499,90") == 3499.9
    assert orders._price("1.250") == 1250.0
    assert orders._price("1.250.000,5") == 1250000.5
    assert orders._price("1559") == 1559.0


def test_promo_mentioning_a_refund_is_not_an_order():
    add_site("Migros", "migros.com.tr")
    from email.message import EmailMessage
    m = EmailMessage()
    m["From"], m["Subject"], m["Message-ID"] = "Migros <kampanya@migros.com.tr>", "İlk Siparişine %15 Money İade! 🎁", "<p@x>"
    m["Date"] = "Sat, 03 Oct 2026 08:21:05 +0000"
    m.set_content("Hemen alışverişe başla, ilk siparişine iade kazan.")
    assert orders.parse(bytes(m), my_sites()) is None
    m.replace_header("Subject", "Siparişin iptal edildi")
    assert orders.parse(bytes(m), my_sites())["status"] == "iptal"


def test_trendyol_go_food_order_from_its_mail_domain():
    add_site("Uber Eats Trendyol Go", "tgoyemek.com")        # mails come from mail.trendyolgo.com
    p = orders.parse(raw("tgo_received"), my_sites())
    assert p["store"] == "Uber Eats Trendyol Go" and p["status"] == "alindi"
    assert p["order_no"] == "11722164726"
    assert p["title"] == "Kaşarlı Poğaça +1 ürün"
    assert p["total"] == 250.0                                 # "Toplam", not "Ara Toplam"
    orders.ingest([raw("tgo_received"), raw("tgo_delivered"), raw("tgo_payment")], my_sites())
    [o] = orders.all_orders(AFTER)
    assert o["status"] == "teslim" and o["total"] == 241.95   # what was charged after re-pricing
    assert [t["status"] for t in o["timeline"]] == ["alindi", "teslim", None]


def test_spam_and_trash_count_only_with_the_stores_signature():
    add_site("Uber Eats Trendyol Go", "tgoyemek.com")
    assert orders.parse(raw("tgo_received"), my_sites(), "spam")["order_no"] == "11722164726"
    assert orders.parse(raw("tgo_received"), my_sites(), "trash")
    # a fake "your order" mail in Spam: right sender name, but Gmail could not verify the signature
    assert orders.parse(raw("tgo_spoofed"), my_sites(), "spam") is None
    assert orders.ingest([(raw("tgo_spoofed"), "spam")], my_sites()) == 0
    assert orders.all_orders(AFTER) == []


def test_scan_searches_alias_domains(monkeypatch):
    add_site("Uber Eats Trendyol Go", "tgoyemek.com")
    seen = {}

    def fake_fetch(domains, days, known):
        seen["domains"] = domains
        return [(raw("tgo_received"), "spam")]
    monkeypatch.setattr(mailbox, "fetch", fake_fetch)
    orders.scan()
    assert seen["domains"] == ["tgoyemek.com", "trendyolgo.com"]
    assert db.one("SELECT order_no FROM orders") == {"order_no": "11722164726"}


def test_status_follows_the_newest_mail_that_has_one_whatever_the_read_order():
    add_site("Uber Eats Trendyol Go", "tgoyemek.com")
    # the payment update (no status, newest) is read first, the delivery mail last
    orders.ingest([raw("tgo_payment"), raw("tgo_received"), raw("tgo_delivered")], my_sites())
    [o] = orders.all_orders(AFTER)
    assert o["status"] == "teslim" and o["total"] == 241.95
    assert o["title"] == "Kaşarlı Poğaça +1 ürün"            # the item list, not a mail's subject


def test_hepsiburada_order_received_is_not_shipped():
    add_site("Hepsiburada", "hepsiburada.com")
    p = orders.parse(raw("hb_received"), my_sites(), "trash")
    assert p["status"] == "alindi"                            # "kargoya verildiğinde" is not "kargoya verildi"
    assert p["order_no"] == "4100000001" and p["total"] == 8459.0
    assert p["title"] == "Crucial CT1000X9SSD9 1TB Portable SSD"   # not the recommended ASUS screen


def test_flight_booking_is_not_an_order():
    add_site("Flypgs", "flypgs.com")
    assert orders.parse(raw("flight"), my_sites()) is None


def test_food_order_without_delivery_mail_closes_after_a_day():
    add_site("Uber Eats Trendyol Go", "tgoyemek.com")
    add_site("Amazon", "amazon.com.tr")
    orders.ingest([raw("tgo_received"), raw("amazon_ordered")], my_sites())      # tgo placed 18.10 06:32
    same_day = datetime(2026, 10, 18, 20, 0, tzinfo=timezone.utc)
    assert {o["store"]: o["status"] for o in orders.all_orders(same_day)} == {
        "Uber Eats Trendyol Go": "alindi", "Amazon": "alindi"}
    next_day = datetime(2026, 10, 19, 7, 0, tzinfo=timezone.utc)
    got = {o["store"]: o for o in orders.all_orders(next_day)}
    assert got["Uber Eats Trendyol Go"]["status"] == "teslim" and got["Uber Eats Trendyol Go"]["assumed"]
    assert got["Uber Eats Trendyol Go"]["delivered_at"].startswith("2026-10-19T06:32")
    assert got["Amazon"]["status"] == "alindi"                # only the quick-delivery stores
    # a real delivery mail arriving later replaces the guess
    orders.ingest([raw("tgo_delivered")], my_sites())
    o = next(o for o in orders.all_orders(next_day) if o["store"] == "Uber Eats Trendyol Go")
    assert o["status"] == "teslim" and not o["assumed"]


def test_open_orders_are_rescanned_on_their_own(monkeypatch):
    started = []
    monkeypatch.setattr(mailbox, "configured", lambda: True)
    monkeypatch.setattr(orders, "start_scan", lambda reason="manual": started.append(reason))
    scheduler.active_orders_scan()                     # nothing open: no scan
    assert started == []
    add_site("Amazon", "amazon.com.tr")
    orders.ingest([raw("amazon_ordered")], my_sites())
    monkeypatch.setattr(orders, "auto_close", lambda now=None: None)
    scheduler.active_orders_scan()
    assert started == ["active"]


def test_credentials_on_windows_are_one_item(monkeypatch, fake_secrets):
    monkeypatch.setattr(mailbox.platform_os, "IS_MAC", False)
    mailbox._keychain_write("ali@gmail.com", "abcdefghijklmnop")
    assert REAL_CREDENTIALS() == ("ali@gmail.com", "abcdefghijklmnop")
    mailbox._keychain_delete()
    assert REAL_CREDENTIALS() is None
