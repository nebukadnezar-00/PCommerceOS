"""Orders from the user's stores, read from their order emails (IMAP, rules only — no tokens).

Every email from one of the user's stores is parsed for an order number, a status
(alındı → hazırlanıyor → kargoda → teslim edildi / iptal / iade), the product, the total and the
parcel tracking. Emails with the same (store, order number) make one order, and the newest email
sets its status. An email the rules cannot place still shows, as its subject."""
import email
import hashlib
import html
import logging
import re
import threading
from datetime import datetime, timedelta, timezone
from email import policy
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import quote_plus

from . import db, mailbox, sites

log = logging.getLogger("commerceos.orders")

FIRST_SCAN_DAYS = 45
RECENT_DAYS = 30            # delivered / cancelled orders stay this long in the list, then go to the archive
OPEN = ("alindi", "hazirlaniyor", "kargoda")
CLOSED = ("teslim", "iptal", "iade")

_lock = threading.Lock()
_run = {"running": False, "started_at": None, "finished_at": None, "added": 0, "error": None}


# ---------------------------------------------------------------- email → text

class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table", "td"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip, self.links, self.anchors, self._a = [], 0, [], [], None

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self.skip += 1
        if tag in self.BLOCK:
            self.out.append("\n")
        if tag == "a":
            href = dict(attrs).get("href") or ""
            if href.startswith("http"):
                self.links.append(href)
                self._a = [href, ""]

    def handle_endtag(self, tag):
        if tag == "a" and self._a:
            self.anchors.append((self._a[0], " ".join(self._a[1].split())))
            self._a = None
        if tag in ("style", "script", "head"):
            self.skip = max(0, self.skip - 1)
        if tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)
            if self._a:
                self._a[1] += data


def _body(msg):
    """(plain text, links, anchors) of a message; the HTML part is turned into text when there is no
    plain one. anchors are (href, link text) pairs from the HTML."""
    plain = msg.get_body(preferencelist=("plain",))
    part = msg.get_body(preferencelist=("html",))
    links, anchors = [], []
    if part is not None:
        p = _Text()
        p.feed(part.get_content())
        links, anchors = p.links, p.anchors
        text = "".join(p.out)
    else:
        text = ""
    if plain is not None:
        text = plain.get_content()
        links = links or re.findall(r"https?://[^\s<>\"')\]]+", text)
    text = html.unescape(text).replace("\xa0", " ").replace("͏", "").replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip(), links, anchors


# ---------------------------------------------------------------- rules

def _low(s):
    return (s or "").replace("İ", "i").lower()


# checked in this order: a cancel/return email may also say "sipariş"
SUBJECT_STATUS = [
    ("iade", r"iade (edildi|talebi|işlemi|onaylandı|süreci|kodu|tamamlandı)|iaden(iz)? "),
    ("iptal", r"iptal edildi|iptal talebi|iptali"),
    ("teslim", r"teslim edildi|teslim aldı|teslimat tamamlandı|sipariş teslimi|teslim ettik"),
    ("kargoda", r"kargoya verildi|kargoda|yola çıktı|dağıtıma çıktı|gönderildi|kargolandı"),
    ("hazirlaniyor", r"hazırlanıyor|paketleniyor|sipariş(in|iniz)? onaylandı"),
    ("alindi", r"sipariş edildi|siparişiniz alındı|sipariş(iniz)? oluşturuldu|siparişin alındı|"
               r"siparişiniz için teşekkür|sipariş onayı|sipariş(ini|inizi) aldık"),
]
# the body lists every step ("Sipariş edildi / Kargoya verildi / Teslim edildi"), so only a
# sentence about *this* parcel counts there
BODY_STATUS = [
    ("iade", r"(siparişiniz|ürününüz|paketiniz|iadeniz)[^.\n]{0,40}iade"),
    ("iptal", r"(siparişiniz|ürününüz|paketiniz)[^.\n]{0,40}iptal edildi"),
    ("teslim", r"(siparişiniz|paketiniz|ürününüz|kargonuz)[^.\n]{0,40}teslim edildi|siparişini teslim ettik"),
    ("kargoda", r"(siparişiniz|paketiniz|ürününüz|kargonuz)[^.\n]{0,40}(kargoya verildi|yola çıktı|dağıtıma çıktı)"),
    ("hazirlaniyor", r"(siparişiniz|ürününüz)[^.\n]{0,40}hazırlanıyor"),
    ("alindi", r"siparişiniz (alındı|oluşturuldu)|siparişiniz için teşekkür|sipariş(ini|inizi) aldık"),
]
_END = r"(?![a-zçğıöşü])"    # whole word: "kargoya verildi" but not "kargoya verildiğinde"

ORDER_NO = [
    re.compile(r"\b(\d{3}-\d{7}-\d{7})\b"),                                    # Amazon
    re.compile(r"sipari[şs]\s*(?:no|numarası|numaranız|kodu|numarasi)\s*[:#.]?\s*\n?\s*#?([A-Z0-9][A-Z0-9-]{4,})",
               re.I),
    re.compile(r"\b(\d{8,})\s+(?:numaralı|nolu)\b", re.I),                    # Trendyol Go: "11722164726 numaralı"
]
# what was actually charged wins over the order's total (Trendyol Go re-prices market orders)
PAID = re.compile(r"ödeme olarak\s*(\d[\d.,]*)\s*(?:TRY|TL|₺)", re.I)
TOTAL = re.compile(r"(?:genel toplam|ödenen tutar|toplam tutar|toplam)\s*:?\s*\n?\s*(?:₺\s*)?"
                   r"(\d[\d.,]*)\s*(?:TRY|TL|₺)", re.I)
TRACK_NO = re.compile(r"(?:kargo\s*)?(?:takip|gönderi)\s*(?:no|numarası|numaranız|kodu)\s*[:#]?\s*\n?\s*([A-Z0-9]{8,})",
                      re.I)
CARRIERS = {
    "Yurtiçi Kargo": (r"yurti[çc]i", "https://www.yurticikargo.com/tr/online-servisler/gonderi-sorgula?code={no}"),
    "Aras Kargo": (r"aras kargo", "https://kargotakip.araskargo.com.tr/mainpage.aspx?code={no}"),
    "PTT Kargo": (r"ptt kargo", "https://gonderitakip.ptt.gov.tr/Track/Verify?q={no}"),
    "MNG Kargo": (r"mng kargo|dhl ecommerce", None),
    "Sürat Kargo": (r"sürat kargo", None),
    "HepsiJET": (r"hepsi\s?jet", None),
    "Trendyol Express": (r"trendyol express", None),
    "Kolay Gelsin": (r"kolay gelsin", None),
    "UPS": (r"\bups\b", None),
}
TRACK_LINK = re.compile(r"progress-tracker|kargo-?takip|gonderi-?takip|shipment|track", re.I)


def _status(subject, text):
    s = _low(re.sub(r"[\"“].*?[\"”]", "", subject))     # a product name may contain "iade"
    for status, pat in SUBJECT_STATUS:
        if re.search(f"(?:{pat}){_END}", s):
            return status
    t = _low(text)
    for status, pat in BODY_STATUS:
        if re.search(f"(?:{pat}){_END}", t):
            return status
    return None


def _price(raw):
    """'3.499,90' (Turkish), '622.84' (Amazon: dot decimal; its shipping mail may even say
    '622.8399999999999'), '1.250' (thousands)."""
    if "," in raw:
        v = raw.replace(".", "").replace(",", ".")
    elif re.search(r"\.(\d{1,2}|\d{4,})$", raw):
        v = raw.replace(".", "", raw.count(".") - 1)
    else:
        v = raw.replace(".", "")
    try:
        return round(float(v), 2)
    except ValueError:
        return None


def _title(subject, text, anchors=(), domains=()):
    """(title, rank): 2 = product name(s) from the body, 1 = quoted in the subject, None = not found."""
    t = _product_title(text, anchors, domains)
    if t:
        return t[:200], 2
    m = re.search(r"[\"“](.+?)[\"”]", subject)
    if m:
        return m.group(1).strip(" .…")[:200], 1
    return None, None


def _product_title(text, anchors, domains):
    items = re.findall(r"^[|\s]*(\S[^|\n]*?)\s*-?\s*\(Adet:\s*\d+\)", text, re.M)   # Trendyol Go: "Baget - (Adet: 1)"
    if items:
        return items[0] + (f" +{len(items) - 1} ürün" if len(items) > 1 else "")
    m = re.search(r"^\s*\*\s+(.+)\n\s*Miktar:", text, re.M)       # Amazon: "* Ürün adı" / "Miktar: 1"
    if m:
        return m.group(1).strip()
    # Hepsiburada: the product's link text ("…--p-HBCV00007BXNJU"); recommendations carry campaign tags
    names = [t for h, t in anchors if len(t) > 5 and re.search(r"-p-[A-Z0-9]{6,}", h)
             and any(d in h for d in domains) and not re.search(r"adj_campaign|utm_campaign", h)]
    if names:
        names = list(dict.fromkeys(names))
        return names[0] + (f" +{len(names) - 1} ürün" if len(names) > 1 else "")
    m = re.search(r"^\s*(?:ürün adı|ürünler|ürün)\s*(?::|\n)\s*(\S.{2,})$", text, re.M | re.I)
    if m:
        return m.group(1).strip()
    return None


# stores whose emails come from another domain than their web site
SENDER_ALIASES = {
    "tgoyemek.com": ("trendyolgo.com",),        # Uber Eats Trendyol Go
}
# food / quick-market stores often send no "teslim ettik" mail: an order still open this many days
# after it was placed is closed as done (shown as "Tamamlandı", not "Teslim edildi")
AUTO_CLOSE_DAYS = {
    "tgoyemek.com": 1,
}


def sender_domains(site):
    return (site["domain"], *SENDER_ALIASES.get(site["domain"], ()))


def _owns(dom, site):
    return any(dom == d or dom.endswith("." + d) for d in sender_domains(site))


def dkim_ok(msg, site):
    """Gmail's own check that the mail was signed by the store's domain. Mail from Spam or Trash only
    counts with it: that is where fake "your order" mails end up, and their links must not be shown."""
    for h in msg.get_all("Authentication-Results", []) + msg.get_all("ARC-Authentication-Results", []):
        for dom in re.findall(r"dkim=pass[^;]*?header\.[id]=@?([\w.-]+)", str(h), re.I):
            if _owns(dom.lower(), site):
                return True
    return False


def store_of(msg, text, my_sites):
    """The user's store an email belongs to: by sender, else (forwarded mail) by Reply-To or the body."""
    candidates = [parseaddr(msg.get(h, ""))[1] for h in ("From", "Reply-To", "X-Forwarded-For", "Sender")]
    for addr in candidates:
        dom = addr.rsplit("@", 1)[-1].lower()
        for s in my_sites:
            if _owns(dom, s):
                return s
    low = text.lower()
    hits = [s for s in my_sites if s["domain"] in low]
    return max(hits, key=lambda s: low.count(s["domain"])) if hits else None


def parse(raw, my_sites, folder="all"):
    """One email → dict, or None when it is not about an order at one of the user's stores.
    `folder` is where it was found: "all", "spam" or "trash"."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    subject = str(msg.get("Subject", "")).strip()
    text, links, anchors = _body(msg)
    site = store_of(msg, text, my_sites)
    if not site or (folder != "all" and not dkim_ok(msg, site)):
        return None
    status = _status(subject, text)
    order_no = next((m.group(1) for p in ORDER_NO for m in [p.search(text) or p.search(subject)] if m), None)
    if not status and not order_no:
        return None     # newsletters, campaigns, account mails
    try:
        received = parsedate_to_datetime(msg.get("Date")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        received = datetime.now(timezone.utc)
    totals = TOTAL.findall(text)          # the last one: "Ara Toplam" comes before "Toplam"
    paid = PAID.search(text)
    total = paid.group(1) if paid else (totals[-1] if totals else None)
    title, title_rank = _title(subject, text, anchors, sender_domains(site))
    track_no = TRACK_NO.search(text)
    low = _low(text)
    carrier = next((name for name, (pat, _) in CARRIERS.items() if re.search(pat, low)), None)
    url = next((l for l in links if any(d in l for d in sender_domains(site)) and TRACK_LINK.search(l)), None)
    if not url and track_no:
        tmpl = CARRIERS.get(carrier, (None, None))[1]
        no = track_no.group(1)
        url = tmpl.format(no=no) if tmpl else "https://www.google.com/search?q=" + quote_plus(
            f"{carrier or 'kargo'} takip {no}")
    mid = str(msg.get("Message-ID", "")).strip() or "sha1:" + hashlib.sha1(raw).hexdigest()
    return {
        "message_id": mid, "site_id": site["id"], "store": site["name"], "subject": subject[:300],
        "status": status, "order_no": order_no, "title": title, "title_rank": title_rank,
        "total": _price(total) if total else None, "paid": bool(paid),
        "carrier": carrier, "tracking_no": track_no.group(1) if track_no else None, "tracking_url": url,
        "received_at": received.isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------- store

def _key(p):
    # an email without an order number is an order of its own, named by its subject
    return p["order_no"] or "mail:" + hashlib.sha1(p["message_id"].encode()).hexdigest()[:12]


def save(p):
    """Merge one parsed email into its order. Returns the order id. The status is set afterwards from
    the order's emails (restatus), so the order emails are read in makes no difference."""
    key = _key(p)
    o = db.one("SELECT * FROM orders WHERE store=? AND order_no=?", (p["store"], key))
    if not o:
        oid = db.execute(
            "INSERT INTO orders(site_id, store, order_no, title, title_rank, status, ordered_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (p["site_id"], p["store"], key, p["title"] or p["subject"], p["title_rank"] or 0, "alindi",
             p["received_at"], p["received_at"]))
        o = db.one("SELECT * FROM orders WHERE id=?", (oid,))
    newer = p["received_at"] >= (o["updated_at"] or "")
    fields = {}
    for col in ("carrier", "tracking_no", "tracking_url"):
        if p[col] and (newer or not o[col]):
            fields[col] = p[col]
    # what was charged (Trendyol Go re-prices market orders) wins over any listed total
    if p["total"] and (p["paid"] or (not o["total_paid"] and (newer or not o["total"]))):
        fields["total"] = p["total"]
        fields["total_paid"] = 1 if p["paid"] else o["total_paid"]
    if p["title"] and (p["title_rank"] or 0) > (o["title_rank"] or 0):
        fields["title"], fields["title_rank"] = p["title"], p["title_rank"]
    if p["received_at"] < (o["ordered_at"] or p["received_at"]):
        fields["ordered_at"] = p["received_at"]
    if newer:
        fields["updated_at"] = p["received_at"]
    if fields:
        db.execute("UPDATE orders SET %s WHERE id=?" % ", ".join(f"{k}=?" for k in fields),
                   (*fields.values(), o["id"]))
    return o["id"]


def restatus(order_id):
    """Status = the newest of the order's emails that says one (an invoice after "teslim edildi" says none)."""
    o = db.one("SELECT manual FROM orders WHERE id=?", (order_id,))
    last = db.one("SELECT status, received_at FROM order_mails WHERE order_id=? AND status IS NOT NULL "
                  "ORDER BY received_at DESC LIMIT 1", (order_id,))
    if o and last and not o["manual"]:
        db.execute("UPDATE orders SET status=?, delivered_at=?, assumed=0 WHERE id=?",
                   (last["status"], last["received_at"] if last["status"] in CLOSED else None, order_id))


def auto_close(now=None):
    """Close quick-delivery orders that never got a delivery mail (AUTO_CLOSE_DAYS). A real status
    mail arriving later replaces this (restatus)."""
    now = now or datetime.now(timezone.utc)
    for domain, days in AUTO_CLOSE_DAYS.items():
        cutoff = now - timedelta(days=days)
        for o in db.rows("SELECT o.id, o.ordered_at FROM orders o JOIN sites s ON s.id = o.site_id "
                         "WHERE s.domain=? AND o.manual=0 AND o.status IN (%s) AND o.ordered_at < ?"
                         % ",".join("?" * len(OPEN)), (domain, *OPEN, cutoff.isoformat(timespec="seconds"))):
            done = datetime.fromisoformat(o["ordered_at"]) + timedelta(days=days)
            db.execute("UPDATE orders SET status='teslim', delivered_at=?, assumed=1 WHERE id=?",
                       (done.isoformat(timespec="seconds"), o["id"]))


def remember(message_id, order_id, subject, status, received_at):
    db.execute("INSERT OR IGNORE INTO order_mails(message_id, order_id, subject, status, received_at) "
               "VALUES(?,?,?,?,?)", (message_id, order_id, subject, status, received_at))


def ingest(mails, my_sites=None):
    """Parse and store emails (raw bytes, or (raw, folder) pairs from mailbox.fetch); returns how many
    were order emails."""
    my_sites = my_sites if my_sites is not None else sites.all_sites()
    n = 0
    for m in mails:
        raw, folder = (m, "all") if isinstance(m, bytes) else m
        try:
            p = parse(raw, my_sites, folder)
        except Exception:
            log.exception("order email could not be parsed")
            continue
        if not p:
            mid = email.message_from_bytes(raw, policy=policy.default).get("Message-ID", "").strip()
            if mid:
                remember(mid, None, None, None, db.now_iso())   # not an order: never fetch it again
            continue
        if db.one("SELECT 1 FROM order_mails WHERE message_id=?", (p["message_id"],)):
            continue
        oid = save(p)
        remember(p["message_id"], oid, p["subject"], p["status"], p["received_at"])
        restatus(oid)
        n += 1
    return n


# ---------------------------------------------------------------- scan

def _days():
    last = db.get_meta("orders_last_scan")
    if not last:
        return FIRST_SCAN_DAYS
    age = datetime.now(timezone.utc) - datetime.fromisoformat(last)
    return max(2, min(FIRST_SCAN_DAYS, age.days + 2))


def scan(reason="manual"):
    """Read new order emails. Returns False if a scan is already running."""
    with _lock:
        if _run["running"]:
            return False
        _run.update(running=True, started_at=db.now_iso(), added=0, error=None)
    try:
        my = sites.all_sites()
        known = {r["message_id"] for r in db.rows("SELECT message_id FROM order_mails")}
        raws = mailbox.fetch([d for s in my for d in sender_domains(s)], _days(), known)
        _run["added"] = ingest(raws, my)
        auto_close()
        db.set_meta("orders_last_scan", db.now_iso())
        db.set_meta("orders_error", "")
        log.info("order scan (%s): %d emails, %d order emails", reason, len(raws), _run["added"])
    except mailbox.MailError as e:
        _run["error"] = str(e)
        db.set_meta("orders_error", str(e))
        log.warning("order scan: %s", e)
    except Exception as e:
        _run["error"] = "E-postalar okunamadı"
        db.set_meta("orders_error", _run["error"])
        log.exception("order scan")
    finally:
        with _lock:
            _run.update(running=False, finished_at=db.now_iso())
    return True


def start_scan(reason="manual"):
    if _run["running"] or not mailbox.configured():
        return False
    threading.Thread(target=scan, args=(reason,), daemon=True).start()
    return True


def state():
    return {"configured": mailbox.configured(), "provider": mailbox.preset()["host"],
            "service": mailbox.preset()["service"], "running": _run["running"], "open": open_count(),
            "last_scan": db.get_meta("orders_last_scan"), "error": db.get_meta("orders_error") or None}


def open_count():
    auto_close()
    return db.one("SELECT COUNT(*) AS n FROM orders WHERE hidden=0 AND status IN (%s)"
                  % ",".join("?" * len(OPEN)), OPEN)["n"]


# ---------------------------------------------------------------- list / edit

def _public(r):
    out = dict(r)
    out["open"] = r["status"] in OPEN
    if r["order_no"].startswith("mail:"):
        out["order_no"] = None
    out["timeline"] = db.rows("SELECT status, subject, received_at FROM order_mails WHERE order_id=? "
                              "ORDER BY received_at", (r["id"],))
    return out


def all_orders(now=None):
    """Open orders first (newest first), then those closed in the last RECENT_DAYS days."""
    now = now or datetime.now(timezone.utc)
    auto_close(now)
    since = (now - timedelta(days=RECENT_DAYS)).isoformat(timespec="seconds")
    rs = db.rows("SELECT * FROM orders WHERE hidden=0 AND (status IN (%s) OR COALESCE(delivered_at, updated_at) >= ?) "
                 "ORDER BY status NOT IN (%s), updated_at DESC" % (",".join("?" * len(OPEN)), ",".join("?" * len(OPEN))),
                 (*OPEN, since, *OPEN))
    return [_public(r) for r in rs]


def archived(now=None):
    """Closed orders older than RECENT_DAYS, newest first. They stay until the user deletes them,
    even after the email is gone: an order lives in our database once it has been read."""
    now = now or datetime.now(timezone.utc)
    since = (now - timedelta(days=RECENT_DAYS)).isoformat(timespec="seconds")
    rs = db.rows("SELECT * FROM orders WHERE hidden=0 AND status IN (%s) AND COALESCE(delivered_at, updated_at) < ? "
                 "ORDER BY COALESCE(delivered_at, updated_at) DESC" % ",".join("?" * len(CLOSED)), (*CLOSED, since))
    return [_public(r) for r in rs]


def update(order_id, delivered=None, hidden=None):
    """`hidden` is the user's delete: the row stays (hidden) so a later scan does not bring it back."""
    o = db.one("SELECT * FROM orders WHERE id=?", (order_id,))
    if not o:
        return None
    if delivered:
        db.execute("UPDATE orders SET status='teslim', delivered_at=?, manual=1 WHERE id=?", (db.now_iso(), order_id))
    elif delivered is False and o["manual"]:
        # "Geri aç": a hand-marked delivery undone; the emails say where the order stands again
        db.execute("UPDATE orders SET manual=0, delivered_at=NULL, status='alindi', assumed=0 WHERE id=?", (order_id,))
        restatus(order_id)
    if hidden is not None:
        db.execute("UPDATE orders SET hidden=? WHERE id=?", (1 if hidden else 0, order_id))
    return _public(db.one("SELECT * FROM orders WHERE id=?", (order_id,)))
