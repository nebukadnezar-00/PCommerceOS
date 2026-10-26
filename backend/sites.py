"""The user's stores: add one from its address, work out its name, logo and search link, keep the logo.

Adding a store reads its home page once (name, icons, OpenSearch). Big Turkish stores answer bots
with 403, so every step has a fallback: a known name/search template, then Google's favicon service
and a Google `site:` search. No AI is involved."""
import html
import logging
import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import quote_plus, urljoin, urlsplit

import requests

from . import config, db, net

log = logging.getLogger("commerceos.sites")

LOGO_DIR = config.DB_PATH.parent / "logos"
MAX_LOGO = 512 * 1024
GOOGLE_FAVICON = "https://www.google.com/s2/favicons?domain={domain}&sz=128"
GOOGLE_SITE_SEARCH = "https://www.google.com/search?q=site%3A{domain}+{{q}}"

# domain → (display name, search template). Used when the store blocks our request or says little.
KNOWN = {
    "trendyol.com": ("Trendyol", "https://www.trendyol.com/sr?q={q}"),
    "hepsiburada.com": ("Hepsiburada", "https://www.hepsiburada.com/ara?q={q}"),
    "amazon.com.tr": ("Amazon TR", "https://www.amazon.com.tr/s?k={q}"),
    "n11.com": ("n11", "https://www.n11.com/arama?q={q}"),
    "mediamarkt.com.tr": ("MediaMarkt", "https://www.mediamarkt.com.tr/tr/search.html?query={q}"),
    "teknosa.com": ("Teknosa", "https://www.teknosa.com/arama/?s={q}"),
    "vatanbilgisayar.com": ("Vatan Bilgisayar", "https://www.vatanbilgisayar.com/arama/{q}/"),
    "ciceksepeti.com": ("Çiçeksepeti", "https://www.ciceksepeti.com/arama?query={q}"),
    "idefix.com": ("idefix", "https://www.idefix.com/arama?q={q}"),
    "pttavm.com": ("PttAVM", "https://www.pttavm.com/arama?q={q}"),
    "a101.com.tr": ("A101", "https://www.a101.com.tr/arama?k={q}"),
    "migros.com.tr": ("Migros", "https://www.migros.com.tr/arama?q={q}"),
    "boyner.com.tr": ("Boyner", "https://www.boyner.com.tr/arama?q={q}"),
    "itopya.com": ("İtopya", "https://www.itopya.com/AramaSonuclari?text={q}"),
}

IMAGE_MAGIC = ((b"\x89PNG\r\n\x1a\n", "png"), (b"\xff\xd8\xff", "jpg"), (b"GIF8", "gif"),
               (b"\x00\x00\x01\x00", "ico"))
IMAGE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "ico": "image/x-icon",
               "webp": "image/webp"}


class SiteError(ValueError):
    pass


# ---------------------------------------------------------------- addresses

def normalize_url(raw):
    """'Trendyol.com/abc' → ('https://www.trendyol.com', 'trendyol.com')."""
    raw = (raw or "").strip()
    if not raw:
        raise SiteError("Site adresi boş")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.I):
        raw = "https://" + raw
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme not in ("http", "https") or not re.match(r"^[a-z0-9.-]+\.[a-z]{2,}$", host):
        raise SiteError("Geçerli bir site adresi girin (ör. trendyol.com)")
    domain = host[4:] if host.startswith("www.") else host
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}", domain


def fold(s):
    """Lower-case ASCII letters and digits only: 'MediaMarkt', 'mediamarkt.com.tr' → 'mediamarkt…'.
    Turkish İ/ı are mapped first so 'İtopya' and 'itopya' agree."""
    s = (s or "").replace("İ", "i").replace("ı", "i")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


def domain_key(domain):
    """'amazon.com.tr' → 'amazon', 'n11.com' → 'n11'."""
    return fold(domain.split(".")[0])


def match_site(store, sites):
    """The user's site an Akakçe/Gemini store name ('Hepsiburada', 'Amazon.com.tr', 'A101') belongs to."""
    f = fold(store)
    if not f:
        return None
    for s in sites:
        key = domain_key(s["domain"])
        if f == fold(s["name"]) or f == fold(s["domain"]) or (len(key) >= 3 and f.startswith(key)):
            return s
    return None


def search_link(site, query):
    return (site.get("search_url") or GOOGLE_SITE_SEARCH.format(domain=site["domain"])).replace(
        "{q}", quote_plus(query))


# ---------------------------------------------------------------- home page

class _Head(HTMLParser):
    """Collects <title>, og:site_name, icon links and the OpenSearch link."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.og_name, self.icons, self.opensearch = "", "", [], None
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag == "meta" and a.get("property", a.get("name", "")).lower() == "og:site_name":
            self.og_name = a.get("content", "").strip()
        elif tag == "link" and a.get("href"):
            rel = a.get("rel", "").lower().split()
            if "search" in rel and "opensearchdescription" in a.get("type", ""):
                self.opensearch = a["href"]
            elif "apple-touch-icon" in rel or "apple-touch-icon-precomposed" in rel:
                self.icons.append((2, _size(a.get("sizes")) or 180, a["href"]))
            elif "icon" in rel and "svg" not in a.get("type", "") and not a["href"].lower().endswith(".svg"):
                self.icons.append((1, _size(a.get("sizes")), a["href"]))

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and len(self.title) < 300:
            self.title += data


def _size(sizes):
    m = re.match(r"(\d+)x\d+", (sizes or "").strip())
    return int(m.group(1)) if m else 0


def _name_from_title(title, domain):
    """'Trendyol: Online Alışveriş Sitesi | Moda…' → the part that names the store."""
    parts = [p.strip() for p in re.split(r"\s+[|\-–—:·]\s+|:\s", html.unescape(title or "")) if p.strip()]
    key = domain_key(domain)
    for p in parts:
        if key and key in fold(p) and len(p) <= 40:
            return p
    return parts[0] if parts and len(parts[0]) <= 40 else ""


def inspect(url, domain):
    """Read the home page: {'name', 'icons': [abs urls best first], 'opensearch': abs url or None}.
    A store that refuses us (403, Cloudflare) just yields empty values."""
    try:
        r = net.get(url, max_bytes=800_000)
        ok = r.status_code < 400 and "html" in r.headers.get("content-type", "")
    except (requests.RequestException, net.Blocked) as e:
        log.info("home page %s: %s", url, e)
        return {"name": "", "icons": [], "opensearch": None}
    if not ok:
        return {"name": "", "icons": [], "opensearch": None}
    p = _Head()
    try:
        p.feed(r.text[:800_000])
    except Exception:  # broken markup: use what was collected
        pass
    base = r.url
    icons = [urljoin(base, href) for _, _, href in sorted(p.icons, key=lambda t: (-t[0], -t[1]))]
    name = p.og_name if 0 < len(p.og_name) <= 40 else _name_from_title(p.title, domain)
    return {"name": name, "icons": icons, "opensearch": urljoin(base, p.opensearch) if p.opensearch else None}


def opensearch_template(url):
    """The store's own search link from its OpenSearch description, with {q} for the query."""
    try:
        r = net.get(url, max_bytes=200_000)
    except (requests.RequestException, net.Blocked):
        return None
    if r.status_code >= 400:
        return None
    for m in re.finditer(r"<Url\b([^>]*)>", r.text, re.I):
        attrs = dict(re.findall(r'(\w+)\s*=\s*"([^"]*)"', m.group(1)))
        if attrs.get("type", "text/html") == "text/html" and "{searchTerms}" in attrs.get("template", ""):
            t = html.unescape(attrs["template"]).replace("{searchTerms}", "{q}")
            t = re.sub(r"[&?][\w.-]+=\{[^}]*\?\}", "", t)       # optional parameters
            if t.startswith("https://") or t.startswith("http://"):
                return t
    return None


# ---------------------------------------------------------------- logos

def _image_ext(body, ctype):
    for magic, ext in IMAGE_MAGIC:
        if body.startswith(magic):
            return ext
    if body[:4] == b"RIFF" and body[8:12] == b"WEBP":
        return "webp"
    return None


def _download_logo(url):
    try:
        r = net.get(url, max_bytes=MAX_LOGO + 1)
    except (requests.RequestException, net.Blocked) as e:
        log.info("logo %s: %s", url, e)
        return None
    if r.status_code != 200 or len(r.content) > MAX_LOGO or len(r.content) < 100:
        return None
    ext = _image_ext(r.content, r.headers.get("content-type", ""))
    return (r.content, ext) if ext else None


def fetch_logo(domain, icons):
    """Download the best logo and keep it as data/logos/<domain>.<ext>; returns the file name or None.
    Order: the store's apple-touch-icon(s), Google's 128 px favicon, the store's other icons, /favicon.ico."""
    apple = [u for u in icons if "apple" in u.lower()]
    others = [u for u in icons if u not in apple]
    candidates = apple[:2] + [GOOGLE_FAVICON.format(domain=domain)] + others[:2] + [f"https://{domain}/favicon.ico"]
    for url in candidates:
        got = _download_logo(url)
        if got:
            body, ext = got
            LOGO_DIR.mkdir(parents=True, exist_ok=True)
            for old in LOGO_DIR.glob(f"{domain}.*"):
                old.unlink()
            name = f"{domain}.{ext}"
            tmp = LOGO_DIR / (name + ".tmp")
            tmp.write_bytes(body)
            tmp.replace(LOGO_DIR / name)
            return name
    return None


def logo_path(site):
    if not site.get("logo"):
        return None
    p = LOGO_DIR / site["logo"]
    return p if p.exists() else None


def logo_type(path):
    return IMAGE_TYPES.get(path.suffix.lstrip("."), "application/octet-stream")


# ---------------------------------------------------------------- store list

def all_sites():
    # group by group (in the groups' order, "Diğer" last), then each group's own order
    return db.rows("SELECT s.* FROM sites s LEFT JOIN site_groups g ON g.id = s.group_id "
                   "ORDER BY g.id IS NULL, g.position, g.id, s.position IS NULL, s.position, s.id")


def get(site_id):
    return db.one("SELECT * FROM sites WHERE id=?", (site_id,))


def add(raw_url, group_id=None):
    url, domain = normalize_url(raw_url)
    if db.one("SELECT id FROM sites WHERE domain=?", (domain,)):
        raise SiteError("Bu site zaten ekli")
    net.check_url(url)
    info = inspect(url, domain)
    known_name, known_search = KNOWN.get(domain, ("", None))
    name = known_name or info["name"] or domain.split(".")[0].capitalize()
    search = known_search or (opensearch_template(info["opensearch"]) if info["opensearch"] else None)
    logo = fetch_logo(domain, info["icons"])
    if group_id is not None and not get_group(group_id):
        group_id = None
    site_id = db.execute(
        "INSERT INTO sites(name, url, domain, search_url, logo, group_id, position, added_at) VALUES(?,?,?,?,?,?,"
        "(SELECT COALESCE(MAX(position), 0) + 1 FROM sites),?)",
        (name, url, domain, search, logo, group_id, db.now_iso()))
    return get(site_id)


def remove(site_id):
    site = get(site_id)
    if not site:
        return False
    db.execute("DELETE FROM sites WHERE id=?", (site_id,))
    for old in LOGO_DIR.glob(f"{site['domain']}.*"):
        old.unlink()
    return True


def rename(site_id, name):
    name = (name or "").strip()[:40]
    if not name:
        raise SiteError("İsim boş olamaz")
    db.execute("UPDATE sites SET name=? WHERE id=?", (name, site_id))
    return get(site_id)


def refresh_logo(site_id):
    site = get(site_id)
    if not site:
        return None
    info = inspect(site["url"], site["domain"])
    logo = fetch_logo(site["domain"], info["icons"])
    db.execute("UPDATE sites SET logo=? WHERE id=?", (logo, site_id))
    return get(site_id)


# `position` is one order across all stores: the strip under the top bar shows it as it is, the
# drawer shows it group by group. Reordering some stores reuses the slots they already held, so the
# others keep theirs (the strip's order survives an edit in the drawer and vice versa).
def _slots(c, ids):
    q = ",".join("?" * len(ids))
    have = [r[0] for r in c.execute(f"SELECT position FROM sites WHERE id IN ({q})", ids).fetchall()]
    top = c.execute("SELECT COALESCE(MAX(position), 0) FROM sites").fetchone()[0]
    missing = sum(1 for p in have if p is None)              # a store without a slot gets one at the end
    return sorted(p for p in have if p is not None) + list(range(top + 1, top + 1 + missing))


def normalize_positions():
    """One distinct position per store (older databases numbered each group from 1): renumbered in the
    order the stores are shown in now, so nothing visibly moves."""
    with db.tx() as c:
        rows = c.execute("SELECT position, COUNT(*) FROM sites GROUP BY position").fetchall()
        if all(p is not None and n == 1 for p, n in rows):
            return
    for pos, s in enumerate(all_sites(), 1):
        db.execute("UPDATE sites SET position=? WHERE id=?", (pos, s["id"]))


def reorder(ids):
    """`ids` in their new order, taking the slots they held (all stores: the whole order)."""
    ids = [i for i in dict.fromkeys(ids)]
    with db.tx() as c:
        for pos, sid in zip(_slots(c, ids), ids):
            c.execute("UPDATE sites SET position=? WHERE id=?", (pos, sid))


def seed_defaults():
    """First start only: add the popular Turkish stores, in one open group (later deletions are
    respected). Rows go in without the network; missing_logos() fetches their logos afterwards."""
    if db.get_meta("seeded"):
        return
    group = db.one("SELECT id FROM site_groups WHERE name=? COLLATE NOCASE", (config.DEFAULT_GROUP,))
    gid = group["id"] if group else add_group(config.DEFAULT_GROUP)["id"]
    for pos, raw in enumerate(config.DEFAULT_SITES, 1):
        url, domain = normalize_url(raw)
        name, search = KNOWN.get(domain, (domain, None))
        db.execute("INSERT OR IGNORE INTO sites(name, url, domain, search_url, group_id, position, added_at) "
                   "VALUES(?,?,?,?,?,?,?)", (name, url, domain, search, gid, pos, db.now_iso()))
    db.set_meta("seeded", db.now_iso())


def missing_logos():
    """Retry logos that could not be fetched (e.g. first start while offline)."""
    for s in all_sites():
        if not logo_path(s):
            try:
                refresh_logo(s["id"])
            except Exception:
                log.exception("logo retry %s", s["domain"])


# ---------------------------------------------------------------- groups

def all_groups():
    return db.rows("SELECT * FROM site_groups ORDER BY position IS NULL, position, id")


def get_group(group_id):
    return db.one("SELECT * FROM site_groups WHERE id=?", (group_id,))


def _group_name(name):
    name = re.sub(r"\s+", " ", (name or "").strip())[:30]
    if not name:
        raise SiteError("Grup adı boş olamaz")
    if fold(name) == "diger":
        raise SiteError('"Diğer" grubu zaten var: gruba konmayan siteler orada durur')
    return name


def add_group(name):
    name = _group_name(name)
    if db.one("SELECT id FROM site_groups WHERE name=? COLLATE NOCASE", (name,)):
        raise SiteError("Bu adda bir grup var")
    gid = db.execute("INSERT INTO site_groups(name, position) VALUES(?, (SELECT COALESCE(MAX(position), 0) + 1 FROM site_groups))",
                     (name,))
    return get_group(gid)


def update_group(group_id, name=None, collapsed=None):
    if not get_group(group_id):
        return None
    if name is not None:
        name = _group_name(name)
        if db.one("SELECT id FROM site_groups WHERE name=? COLLATE NOCASE AND id<>?", (name, group_id)):
            raise SiteError("Bu adda bir grup var")
        db.execute("UPDATE site_groups SET name=? WHERE id=?", (name, group_id))
    if collapsed is not None:
        db.execute("UPDATE site_groups SET collapsed=? WHERE id=?", (1 if collapsed else 0, group_id))
    return get_group(group_id)


def remove_group(group_id):
    """The group's stores move to "Diğer" (kept, not deleted)."""
    with db.tx() as c:
        c.execute("UPDATE sites SET group_id=NULL WHERE group_id=?", (group_id,))
        c.execute("DELETE FROM site_groups WHERE id=?", (group_id,))


def reorder_groups(ids):
    with db.tx() as c:
        for pos, gid in enumerate(ids, 1):
            c.execute("UPDATE site_groups SET position=? WHERE id=?", (pos, gid))


def move(ids, group_id):
    """`ids` is the complete new order of one group's stores (NULL group = "Diğer")."""
    if group_id is not None and not get_group(group_id):
        raise SiteError("Grup bulunamadı")
    ids = [i for i in dict.fromkeys(ids)]
    with db.tx() as c:
        for pos, sid in zip(_slots(c, ids), ids):
            c.execute("UPDATE sites SET position=?, group_id=? WHERE id=?", (pos, group_id, sid))


# ---------------------------------------------------------------- search scope

SCOPE_RE = re.compile(r"^(all|mine|mine:\d+)$")


def scope_sites(scope, my_sites=None):
    """The stores a scope counts: "mine" = all of them, "mine:3" = group 3 only ("all" → all of them too,
    for matching store names; filtering is the caller's business)."""
    my = my_sites if my_sites is not None else all_sites()
    if scope and scope.startswith("mine:"):
        gid = int(scope.split(":", 1)[1])
        return [s for s in my if s.get("group_id") == gid]
    return my
