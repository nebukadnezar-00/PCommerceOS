"""What the AI has cost, for ⚙ Ayarlar → Kullanım ve maliyet: totals, each part of CommerceOS, and
each provider/model, over today or the last 7, 30 or 90 days (local time), with the cost per hour, day
or week for a chart. Only deep search spends tokens; the other parts are listed with "token yok" so
that is visible too."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import db, pricing

TZ = ZoneInfo("Europe/Istanbul")
PERIODS = ("today", "week", "month", "quarter")
DAYS = {"week": 7, "month": 30, "quarter": 90}
# rows from before provider/model were recorded: deep search on the only setup there was then
OLD = {"provider": "gemini", "model": "gemini-2.5-flash", "section": "deep"}
SECTIONS = [("deep", "Derin ara", True), ("quick", "Hızlı arama", False), ("tracking", "Fiyat takibi", False),
            ("cart", "Sepet", False), ("orders", "Siparişlerim", False)]


def _start(period, now=None):
    """The period's first moment, local time: today since midnight; the others the last N days, today included."""
    now = (now or datetime.now(timezone.utc)).astimezone(TZ)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight if period == "today" else midnight - timedelta(days=DAYS[period] - 1)


def since(period, now=None):
    """The period's start as a UTC ISO string (rows store UTC). "month_cal" is the calendar month
    (the status line's "bu ay")."""
    if period == "month_cal":
        now = (now or datetime.now(timezone.utc)).astimezone(TZ)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        start = _start(period, now)
    return start.astimezone(timezone.utc).isoformat(timespec="seconds")


def _buckets(period, now=None):
    """The chart's bars: (start, label) — hours for today, days for 7/30 days, weeks for 90 days."""
    start = _start(period, now)
    if period == "today":
        return [(start + timedelta(hours=i), f"{i:02d}:00") for i in range(24)], timedelta(hours=1)
    if period == "quarter":
        return [(start + timedelta(weeks=i), (start + timedelta(weeks=i)).strftime("%d.%m")) for i in range(13)], timedelta(weeks=1)
    return [(start + timedelta(days=i), (start + timedelta(days=i)).strftime("%d.%m")) for i in range(DAYS[period])], timedelta(days=1)


def cost_since(start_iso):
    """Total estimated cost of the rows from `start_iso` on (rows without a known price add nothing)."""
    total = 0.0
    for r in db.rows("SELECT * FROM token_usage WHERE created_at >= ?", (start_iso,)):
        total += pricing.cost(r["model"] or OLD["model"], r["prompt_tokens"], r["output_tokens"]) or 0.0
    return round(total, 6)


def summary(period="month", now=None):
    rows = db.rows("SELECT * FROM token_usage WHERE created_at >= ? ORDER BY id", (since(period, now),))
    buckets, step = _buckets(period, now)
    series = [{"start": b.isoformat(timespec="seconds"), "label": label, "cost": 0.0, "tokens": 0, "requests": 0}
              for b, label in buckets]
    total = {"cost": 0.0, "prompt": 0, "output": 0, "requests": 0, "backup": 0, "unpriced": 0}
    by_section, by_model = {}, {}
    for r in rows:
        provider, model, section = r["provider"] or OLD["provider"], r["model"] or OLD["model"], r["section"] or OLD["section"]
        cost = pricing.cost(model, r["prompt_tokens"], r["output_tokens"])
        for bucket in (total, by_section.setdefault(section, {"cost": 0.0, "prompt": 0, "output": 0, "requests": 0, "unpriced": 0}),
                       by_model.setdefault((provider, model), {"cost": 0.0, "prompt": 0, "output": 0, "requests": 0, "unpriced": 0})):
            bucket["prompt"] += r["prompt_tokens"]
            bucket["output"] += r["output_tokens"]
            bucket["requests"] += 1
            if cost is None:
                bucket["unpriced"] += 1
            else:
                bucket["cost"] += cost
        if r["backup"]:
            total["backup"] += 1
        at = datetime.fromisoformat(r["created_at"]).astimezone(TZ)
        i = int((at - buckets[0][0]) // step)
        if 0 <= i < len(series):
            series[i]["cost"] += cost or 0.0
            series[i]["tokens"] += r["prompt_tokens"] + r["output_tokens"]
            series[i]["requests"] += 1
    tokens = total["prompt"] + total["output"]
    sections = []
    for key, name, spends in SECTIONS:
        s = by_section.get(key)
        sections.append({"key": key, "name": name, "spends": spends, "requests": s["requests"] if s else 0,
                         "tokens": s["prompt"] + s["output"] if s else 0, "cost": round(s["cost"], 6) if s else 0.0,
                         "unpriced": s["unpriced"] if s else 0})
    models = [{"provider": p, "model": m, "requests": v["requests"], "tokens": v["prompt"] + v["output"],
               "share": round((v["prompt"] + v["output"]) / tokens, 4) if tokens else 0,
               "cost": round(v["cost"], 6), "price": pricing.price(m), "unpriced": v["unpriced"]}
              for (p, m), v in sorted(by_model.items(), key=lambda kv: -(kv[1]["prompt"] + kv[1]["output"]))]
    return {"period": period, "since": since(period, now), "cost": round(total["cost"], 6),
            "prompt_tokens": total["prompt"], "output_tokens": total["output"], "tokens": tokens,
            "requests": total["requests"], "backup": total["backup"], "unpriced": total["unpriced"],
            "sections": sections, "models": models,
            "series": [dict(b, cost=round(b["cost"], 6)) for b in series]}
