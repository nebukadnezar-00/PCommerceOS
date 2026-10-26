from datetime import datetime, timezone

from backend import ai, db, pricing, providers, usage
from tests.test_commerce import client

NOW = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)          # 12:00 in Istanbul


def row(at, prompt, output, provider=None, model=None, backup=0):
    db.execute("INSERT INTO token_usage(prompt_tokens, output_tokens, total_tokens, created_at, provider, model, section, backup) "
               "VALUES(?,?,?,?,?,?,?,?)", (prompt, output, prompt + output, at, provider, model, "deep" if provider else None, backup))


def test_cost_per_model_and_unknown_price():
    assert pricing.cost("gemini-2.5-flash", 1_000_000, 1_000_000) == 2.80
    assert pricing.cost("claude-opus-5-5", 1000, 1000) is None
    pricing.set_custom({"claude-opus-5-5": [5, 25]})
    assert pricing.cost("claude-opus-5-5", 1_000_000, 0) == 5.0
    pricing.set_custom({"claude-opus-5-5": None})
    assert pricing.price("claude-opus-5-5") is None


def test_periods_turn_at_local_midnight_and_old_rows_are_gemini():
    row("2026-10-24T20:59:00+00:00", 100, 100)                    # 23:59 Istanbul, yesterday; an old row
    row("2026-10-24T21:00:00+00:00", 1000, 2000, "gemini", "gemini-2.5-flash")   # 00:00 today
    row("2026-10-25T08:00:00+00:00", 500, 500, "anthropic", "claude-opus-5-5", backup=1)
    row("2026-10-18T21:30:00+00:00", 10, 10, "gemini", "gemini-2.5-flash")      # 19 Oct local: in the week
    row("2026-10-18T20:30:00+00:00", 10, 10, "gemini", "gemini-2.5-flash")      # 18 Oct local: not in it
    today = usage.summary("today", NOW)
    assert today["requests"] == 2 and today["backup"] == 1 and today["unpriced"] == 1
    assert today["cost"] == round((1000 * 0.30 + 2000 * 2.50) / 1e6, 6)
    week = usage.summary("week", NOW)
    assert week["requests"] == 4 and week["tokens"] == 200 + 3000 + 1000 + 20
    [deep] = [s for s in week["sections"] if s["key"] == "deep"]
    assert deep["requests"] == 4 and all(not s["requests"] for s in week["sections"] if s["key"] != "deep")
    assert [m["model"] for m in week["models"]] == ["gemini-2.5-flash", "claude-opus-5-5"]
    assert usage.summary("month", NOW)["requests"] == 5


def test_chart_series_per_period():
    row("2026-10-24T21:00:00+00:00", 1000, 2000, "gemini", "gemini-2.5-flash")   # 00:00 today
    row("2026-10-25T08:30:00+00:00", 1000, 2000, "gemini", "gemini-2.5-flash")   # 11:30 today
    row("2026-08-01T09:00:00+00:00", 1000, 2000, "gemini", "gemini-2.5-flash")   # 85 days ago
    lengths = {p: len(usage.summary(p, NOW)["series"]) for p in usage.PERIODS}
    assert lengths == {"today": 24, "week": 7, "month": 30, "quarter": 13}
    today = usage.summary("today", NOW)["series"]
    assert today[0]["requests"] == 1 and today[11]["requests"] == 1 and today[0]["label"] == "00:00"
    for p in usage.PERIODS:
        u = usage.summary(p, NOW)
        assert sum(b["requests"] for b in u["series"]) == u["requests"]
        assert round(sum(b["cost"] for b in u["series"]), 6) == u["cost"]


def test_backup_is_recorded_when_the_primary_did_not_answer(monkeypatch):
    monkeypatch.setattr(providers, "load_settings", lambda: {"primary": {"provider": "gemini"}, "backup": {"provider": "anthropic"}})
    ai._usage(providers.Reply("x", "anthropic", "claude-opus-5-5", usage=(10, 20)))
    ai._usage(providers.Reply("x", "gemini", "gemini-2.5-flash", usage=(10, 20)))
    assert [r["backup"] for r in db.rows("SELECT backup FROM token_usage ORDER BY id")] == [1, 0]


def test_usage_endpoints(monkeypatch):
    row(db.now_iso(), 1000, 1000, "gemini", "gemini-2.5-flash")
    with client() as c:
        u = c.get("/api/usage", params={"period": "today"}).json()
        assert u["requests"] == 1 and len(u["sections"]) == 5 and len(u["series"]) == 24
        assert c.get("/api/usage", params={"period": "90d"}).status_code == 400
        # a model's own price is saved only from this Mac (the test client is not a loopback address)
        prices = {"prices": {"claude-opus-5-5": [5, 25]}}
        assert c.put("/api/usage/settings", json=prices).status_code == 403
        monkeypatch.setattr(providers, "is_local", lambda request: True)
        assert c.put("/api/usage/settings", json=prices).status_code == 200
        assert c.put("/api/usage/settings", json={"prices": {"x": [-1, 2]}}).status_code == 400
