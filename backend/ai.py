"""Deep search: the AI provider chosen in ⚙ Ayarlar (Gemini, Claude, …) searches the web for current prices in Turkey.

This is the only part of CommerceOS that spends tokens, and only when the user presses "Derin ara".
Thinking is off and the answer is a short JSON list. Every product link Gemini gives is checked
without AI afterwards; a dead one is replaced by the store's own search link, so no made-up page
is ever offered."""
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from . import config, db, net, providers, sites, usage

log = logging.getLogger("commerceos.ai")

class AIUnavailable(RuntimeError):
    pass


def _usage(rep, section="deep"):
    # the slot that answered: the backup when the primary failed (or has no key)
    primary = (providers.load_settings().get("primary") or {}).get("provider")
    db.execute("INSERT INTO token_usage(prompt_tokens, output_tokens, total_tokens, created_at, provider, model, section, backup) "
               "VALUES(?,?,?,?,?,?,?,?)", (rep.usage[0], rep.usage[1], sum(rep.usage), db.now_iso(), rep.provider, rep.model,
                                           section, int(bool(primary) and rep.provider != primary)))


def _call(prompt):
    """The AI provider chosen in ⚙ Ayarlar (backup on failure); web search on, low effort."""
    try:
        return providers.generate(prompt, search=True, light=True, on_usage=_usage)
    except providers.NoProvider as e:
        raise AIUnavailable(str(e)) from e


def _extract_json(text):
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("JSON bulunamadı")
    return json.loads(text[start:text.rfind("}") + 1])


PROMPT = """Türkiye'de alışveriş yapan biri için fiyat araştırması yap. Google araması ile şu ürünün
GÜNCEL satış fiyatlarını bul: "{query}"
Bugün: {today}.

{scope}

Kurallar:
- Yalnızca Türkiye'de satış yapan mağazalar ve TL fiyatlar. Fiyatı bulamadığın mağazayı yazma.
- Her fiyat o mağazanın KENDİ sayfasındaki fiyat olsun. Akakçe/Cimri gibi karşılaştırma sitelerindeki
  "en ucuz" fiyatı, hangi mağazaya ait olduğunu görmeden bir mağazaya yazma.
- Ürün genel bir kategori ise (ör. "kablosuz kulaklık") en çok tercih edilen 3-5 modeli seç ve
  her biri için en uygun teklifleri ver.
- "url" sadece aramada gerçekten gördüğün ürün sayfası olsun; emin değilsen boş bırak.
- En fazla 12 teklif. Metinler TÜRKÇE ve kısa.

YALNIZCA şu JSON'u döndür (başka metin yazma):
```json
{{
  "summary": "1-2 cümle: en uygun seçenek ve fiyat aralığı",
  "offers": [
    {{"store": "Mağaza adı", "title": "Ürün adı (model/varyant)", "price": 12345.67,
      "currency": "TL", "url": "https://...", "note": "kargo/stok/kampanya notu ya da boş"}}
  ]
}}
```"""


def _scope_text(scope, my_sites):
    if scope.startswith("mine") and my_sites:
        names = ", ".join(f"{s['name']} ({s['domain']})" for s in my_sites)
        return f"SADECE şu mağazalara bak, başka mağaza yazma: {names}."
    return "Türkiye'deki tüm büyük ve güvenilir e-ticaret sitelerine bak."


def _check_link(url):
    """True when the page exists (or the store just refuses bots); False on 404/410 or a bad address."""
    try:
        r = net.get(url, max_bytes=2048)
        return r.status_code not in (404, 410)
    except net.Blocked:
        return False
    except requests.RequestException:
        return True  # timeouts and resets say nothing about the page itself


def _fix_links(offers, my_sites, query):
    """Replace missing or dead links with the store's search page (or a Google search)."""
    urls = [o.get("url") or "" for o in offers]
    with ThreadPoolExecutor(max_workers=6) as pool:
        alive = list(pool.map(lambda u: bool(u) and u.startswith("http") and _check_link(u), urls))
    for o, ok in zip(offers, alive):
        o["link_checked"] = ok
        if not ok:
            site = sites.match_site(o["store"], my_sites)
            o["url"] = sites.search_link(site, query) if site else (
                "https://www.google.com/search?q=" + requests.utils.quote(f"{o['store']} {o['title'] or query}"))
            o["link_fallback"] = True


def deep_search(query, scope, my_sites):
    """{'summary', 'offers': [...], 'sources': [...], 'tokens'} — offers cheapest first."""
    today = datetime.now(ZoneInfo("Europe/Istanbul")).strftime("%d.%m.%Y")
    prompt = PROMPT.format(query=query, today=today, scope=_scope_text(scope, my_sites))
    resp = _call(prompt)
    tokens = sum(resp.usage)
    try:
        data = _extract_json(resp.text)
    except (ValueError, TypeError):
        raise RuntimeError("Yapay zekâ yanıtı okunamadı, tekrar deneyin")

    offers = []
    for o in data.get("offers") or []:
        try:
            price = float(str(o.get("price")).replace(",", "."))
        except (TypeError, ValueError):
            continue
        if price <= 0 or not o.get("store"):
            continue
        offers.append({"store": str(o["store"])[:60], "title": str(o.get("title") or "")[:200],
                       "price": price, "currency": str(o.get("currency") or "TL")[:5],
                       "url": str(o.get("url") or "").strip(), "note": str(o.get("note") or "")[:200]})
    if scope.startswith("mine"):   # my_sites is already narrowed to the scope's stores
        offers = [o for o in offers if sites.match_site(o["store"], my_sites)]
    offers.sort(key=lambda o: o["price"])
    _fix_links(offers, my_sites, query)

    sources = []
    try:
        gm = resp.raw.candidates[0].grounding_metadata if resp.raw is not None else None
        for ch in (gm.grounding_chunks or []) if gm else []:
            if ch.web and ch.web.uri:
                sources.append({"title": ch.web.title or ch.web.domain or "Kaynak", "url": ch.web.uri})
    except (AttributeError, IndexError):
        pass
    if resp.raw is None:
        sources = list({s["url"]: s for s in resp.sources}.values())
    return {"summary": str(data.get("summary") or "")[:500], "offers": offers,
            "sources": sources[:10], "tokens": tokens}


def tokens_this_month():
    # the month turns at local midnight (rows are stored in UTC)
    r = db.one("SELECT COALESCE(SUM(total_tokens), 0) AS n, COUNT(*) AS c FROM token_usage WHERE created_at >= ?",
               (usage.since("month_cal"),))
    return {"tokens": r["n"], "searches": r["c"], "cost": usage.cost_since(usage.since("month_cal"))}
