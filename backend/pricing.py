"""List prices of the AI models, in US dollars per 1M tokens (input, output), to estimate what deep
search costs. Only prices known for certain are listed; any other model's price is entered in
⚙ Ayarlar → Kullanım ve maliyet (kept in meta). Gemini bills its thinking tokens as output, and the
output count recorded for Gemini already includes them. Google Search grounding, which deep search
uses, is billed apart (free up to a daily limit) and is not in these figures."""
from . import db

LIST_PRICES = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-flash-lite": (0.10, 0.40),
    "gemini-2.5-pro": (1.25, 10.00),     # prompts up to 200k tokens; deep search stays far below
    # the other providers' default models (providers.PROVIDERS); web search tool fees are not included
    "claude-sonnet-5-5": (2.00, 10.00),
    "gpt-6-luna": (0.10, 0.50),
    "google/gemini-2.5-flash": (0.30, 2.50),     # OpenRouter, same as Google's list price
    "sonar": (1.00, 1.00),                       # Perplexity; plus a per-request search fee
}


def custom():
    return db.loads(db.get_meta("model_prices"), {}) or {}


def price(model):
    """(input, output) USD per 1M tokens, or None when the price is not known."""
    p = custom().get(model) or LIST_PRICES.get(model)
    return (float(p[0]), float(p[1])) if p else None


def cost(model, prompt_tokens, output_tokens):
    p = price(model)
    if not p:
        return None
    return round((prompt_tokens * p[0] + output_tokens * p[1]) / 1_000_000, 6)


def set_custom(prices):
    """{model: [input, output] | None}: a None removes that model's own price."""
    cur = custom()
    for model, p in (prices or {}).items():
        model = str(model).strip()[:80]
        if not model:
            continue
        if p is None:
            cur.pop(model, None)
            continue
        a, b = float(p[0]), float(p[1])
        if not (0 <= a <= 1000 and 0 <= b <= 1000):
            raise ValueError("Fiyat 0 ile 1000 $ arasında olmalı")
        cur[model] = [a, b]
    db.set_meta("model_prices", db.dumps(cur))
