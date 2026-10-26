"""AI providers: which one is primary / backup, their API keys, a token-free connection test, one
generate() call over all of them (primary first, backup on failure) and the Ayarlar API.

ONE FILE, COPIED AS-IS into every OS Suite app (FinanceOS/backend, CommerceOS/backend, …) —
change it in FinanceOS and copy it over. It imports nothing from the module around it but its sibling
platform_os.py (also a shared copy).
Keys live in the system's secret store (macOS Keychain, Windows Credential Manager), never in a file,
never sent to a browser. Two layouts:
- shared (`os-suite-ai.json` beside the app folders): one choice for every module in
  that file, keys under "OS Suite · <Provider>";
- standalone (the app on its own, on any OS): the choice in the module's data/ai.json, keys under
  "<App> · <Provider>" (set_app()).
Before anything is saved, a GEMINI_API_KEY from .env counts as the primary provider (old setups)."""
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException, Request
from google import genai
from google.genai import types
from pydantic import BaseModel

from . import platform_os

log = logging.getLogger("os-suite.providers")

MODULE_ROOT = Path(__file__).resolve().parents[1]          # the app's own folder
WORKSPACE = MODULE_ROOT.parent                             # "the folder holding the apps"
SHARED = (WORKSPACE / "os-suite-ai.json").exists()
SETTINGS_FILE = WORKSPACE / "os-suite-ai.json" if SHARED else MODULE_ROOT / "data" / "ai.json"
APP_NAME = MODULE_ROOT.name                                # standalone key names; the module sets it


def set_app(name):
    """The app's own name for its keys when it runs on its own ("CommerceOS · Google Gemini")."""
    global APP_NAME
    APP_NAME = name
KEYCHAIN_ACCOUNT = "os-suite"
CACHE_SEC = 60
SLOTS = ("primary", "backup")

# id: name, key hint, default model (cheap, text, shown pre-selected; changed only under "Gelişmiş"), web search?, adapter, base URL, how the test works
PROVIDERS = {
    "gemini": {"name": "Google Gemini", "hint": "AIza…", "model": "gemini-2.5-flash", "search": True,
               "adapter": "gemini", "color": "#4285f4"},
    "anthropic": {"name": "Anthropic Claude", "hint": "sk-ant-…", "model": "claude-sonnet-5-5", "search": True,
                  "adapter": "anthropic", "color": "#d97757"},
    "openai": {"name": "OpenAI", "hint": "sk-…", "model": "gpt-6-luna", "search": True, "adapter": "openai",
               "base": "https://api.openai.com/v1", "color": "#10a37f"},
    "openrouter": {"name": "OpenRouter", "hint": "sk-or-…", "model": "google/gemini-2.5-flash", "search": True, "adapter": "compat",
                   "base": "https://openrouter.ai/api/v1", "color": "#6467f2"},
    "perplexity": {"name": "Perplexity", "hint": "pplx-…", "model": "sonar", "search": True, "adapter": "compat",
                   "base": "https://api.perplexity.ai", "color": "#20b8cd"},
}

KEY_RE = re.compile(r"^[A-Za-z0-9._\-:+/=]{8,400}$")      # also keeps `security -i` input safe


class NoProvider(RuntimeError):
    pass


class ProviderError(RuntimeError):
    """A provider call failed; `kind` says how (key, credit, quota, model, network, server, other)."""
    def __init__(self, kind, message, status=None):
        super().__init__(message)
        self.kind, self.status = kind, status


MESSAGES = {
    "key": "Anahtar geçersiz ya da bu işlem için yetkisi yok.",
    "credit": "Kredi/bakiye bitmiş. Sağlayıcının panelinden bakiye yükle ya da ücretsiz bir anahtar kullan.",
    "quota": "Kota ya da istek limiti dolmuş; bir süre sonra tekrar dene.",
    "model": "Model bulunamadı ya da bu anahtarla kullanılamıyor.",
    "network": "Sağlayıcıya ulaşılamadı (internet bağlantısı yok ya da sunucu yanıt vermiyor).",
    "server": "Sağlayıcı tarafında geçici bir hata var; biraz sonra tekrar dene.",
    "other": "Beklenmeyen bir hata oluştu.",
}


def classify(status, text=""):
    t = (text or "").lower()
    if status == 402 or "credit" in t or "billing" in t or "insufficient_quota" in t or "prepayment" in t:
        return "credit"
    if status in (401, 403) or "api key" in t or "api_key" in t or "unauthorized" in t or "permission" in t:
        return "key"
    if status == 429 or "rate limit" in t or "rate_limit" in t or "quota" in t or "resource_exhausted" in t:
        return "quota"
    if status == 404 or "not found" in t or ("model" in t and status == 400):
        return "model"
    if status and status >= 500:
        return "server"
    return "other"


# ------------------------------------------------------------ keychain

_lock = threading.Lock()
_cache = {}            # name -> (time, value)


def _service(provider):
    return f"{'OS Suite' if SHARED else APP_NAME} · {PROVIDERS[provider]['name']}"


def keychain_get(service):
    return platform_os.secret_get(service, KEYCHAIN_ACCOUNT)


def keychain_set(service, secret):
    if not KEY_RE.match(secret):
        raise ValueError("Anahtar beklenmeyen karakterler içeriyor")
    platform_os.secret_set(service, KEYCHAIN_ACCOUNT, secret)


def keychain_delete(service):
    platform_os.secret_delete(service, KEYCHAIN_ACCOUNT)


def _env_gemini(name="GEMINI_API_KEY"):
    """Old setups: the module's environment/.env, else FinanceOS/.env (where the key used to live)."""
    v = os.environ.get(name, "").strip()
    if not v and SHARED and MODULE_ROOT.name != "FinanceOS":
        try:
            from dotenv import dotenv_values
            v = (dotenv_values(WORKSPACE / "FinanceOS" / ".env").get(name) or "").strip()
        except Exception:
            v = ""
    return v


def get_key(provider):
    """The provider's key: Keychain first; for Gemini the old .env value as a fallback."""
    with _lock:
        hit = _cache.get(provider)
        if hit and time.time() - hit[0] < CACHE_SEC:
            return hit[1]
    key = keychain_get(_service(provider))
    if not key and provider == "gemini":
        key = _env_gemini() or None
    with _lock:
        _cache[provider] = (time.time(), key)
    return key


def set_key(provider, key):
    keychain_set(_service(provider), key)
    with _lock:
        _cache.pop(provider, None)


def delete_key(provider):
    keychain_delete(_service(provider))
    with _lock:
        _cache.pop(provider, None)


def masked(provider):
    k = get_key(provider)
    if not k:
        return {"masked": None, "source": None}
    from_env = provider == "gemini" and not keychain_get(_service(provider))
    return {"masked": f"•••• {k[-4:]}", "source": ".env" if from_env else platform_os.secret_store_name()}


# ------------------------------------------------------------ primary / backup choice

def _default_settings():
    if _env_gemini():
        return {"primary": {"provider": "gemini", "model": _env_gemini("GEMINI_MODEL") or PROVIDERS["gemini"]["model"]},
                "backup": None}
    return {"primary": None, "backup": None}


def load_settings():
    try:
        data = json.loads(SETTINGS_FILE.read_text())
    except (OSError, ValueError):
        return _default_settings()
    out = {}
    for slot in SLOTS:
        s = data.get(slot)
        out[slot] = s if isinstance(s, dict) and s.get("provider") in PROVIDERS else None
    return out


def save_settings(settings):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2))
    os.chmod(tmp, 0o600)
    tmp.replace(SETTINGS_FILE)


def chain():
    """[(provider, model, key)] to try in order: primary, then backup (only ones with a key)."""
    out = []
    for slot in SLOTS:
        s = load_settings()[slot]
        if not s:
            continue
        key = get_key(s["provider"])
        if key and (s["provider"], s.get("model")) not in [(p, m) for p, m, _ in out]:
            out.append((s["provider"], s.get("model") or PROVIDERS[s["provider"]]["model"], key))
    return out


def ready():
    return bool(chain())


def migrate_env_key():
    """First save: move a GEMINI_API_KEY from .env into the Keychain and blank it in .env."""
    key = _env_gemini()
    if not key or keychain_get(_service("gemini")):
        return
    set_key("gemini", key)
    env = MODULE_ROOT / ".env"
    try:
        lines = env.read_text().splitlines()
        env.write_text("\n".join("GEMINI_API_KEY=" if l.startswith("GEMINI_API_KEY=") else l for l in lines) + "\n")
    except OSError:
        log.warning("could not blank GEMINI_API_KEY in .env")
    os.environ["GEMINI_API_KEY"] = ""


# ------------------------------------------------------------ connection test (no tokens)

def _http(method, url, **kw):
    try:
        r = requests.request(method, url, timeout=15, **kw)
    except requests.RequestException as e:
        raise ProviderError("network", MESSAGES["network"]) from e
    if r.status_code >= 400:
        kind = classify(r.status_code, r.text[:500])
        raise ProviderError(kind, f"{MESSAGES[kind]} (HTTP {r.status_code})", r.status_code)
    return r


def test(provider, key=None, model=None):
    """Check a key without generating anything. Returns {ok, message, models}."""
    p = PROVIDERS[provider]
    key = key or get_key(provider)
    if not key:
        return {"ok": False, "kind": "key", "message": "Anahtar girilmemiş.", "models": []}
    model = model or p["model"]
    try:
        models = [m for m in _list_models(provider, key) if _is_text(m)]
    except ProviderError as e:
        return {"ok": False, "kind": e.kind, "message": str(e), "models": []}
    if model and models and model not in models:
        return {"ok": False, "kind": "model", "message": f"{model} bu anahtarla bulunamadı.", "models": models}
    note = "0 token" if provider != "perplexity" else "en fazla 1 token"
    return {"ok": True, "kind": None, "models": models,
            "message": f"Bağlantı başarılı · {model or 'model seç'} erişilebilir · {note}"}


# Model ids that cannot answer a text prompt: speech, images, video, embeddings, live audio, moderation
NOT_TEXT = ("tts", "image", "imagen", "veo", "embed", "audio", "live", "realtime", "transcribe", "whisper",
            "dall-e", "moderation", "aqa", "robotics", "computer-use", "lyria", "sora", "babbage", "davinci")


def _is_text(model):
    m = model.lower()
    return not any(w in m for w in NOT_TEXT)


def _list_models(provider, key):
    p = PROVIDERS[provider]
    if provider == "gemini":
        r = _http("GET", "https://generativelanguage.googleapis.com/v1beta/models",
                  params={"pageSize": 200}, headers={"x-goog-api-key": key})
        return sorted(m["name"].split("/", 1)[-1] for m in r.json().get("models", [])
                      if "generateContent" in m.get("supportedGenerationMethods", []))
    if provider == "anthropic":
        import anthropic
        try:
            page = anthropic.Anthropic(api_key=key, max_retries=0, timeout=15).models.list(limit=100)
        except anthropic.APIConnectionError as e:
            raise ProviderError("network", MESSAGES["network"]) from e
        except anthropic.APIStatusError as e:
            kind = classify(e.status_code, str(e.message))
            raise ProviderError(kind, f"{MESSAGES[kind]} (HTTP {e.status_code})", e.status_code) from e
        return [m.id for m in page.data]
    if provider == "openrouter":
        _http("GET", f"{p['base']}/key", headers={"Authorization": f"Bearer {key}"})      # validates the key
        r = _http("GET", f"{p['base']}/models")
        return sorted(m["id"] for m in r.json().get("data", [])
                      if (m.get("architecture") or {}).get("output_modalities", ["text"]) == ["text"])
    if provider == "perplexity":
        _http("POST", f"{p['base']}/chat/completions", headers={"Authorization": f"Bearer {key}"},
              json={"model": p["model"], "max_tokens": 1, "messages": [{"role": "user", "content": "ok"}]})
        return ["sonar", "sonar-pro", "sonar-reasoning", "sonar-reasoning-pro", "sonar-deep-research"]
    r = _http("GET", f"{p['base']}/models", headers={"Authorization": f"Bearer {key}"})      # openai
    return sorted(m["id"] for m in r.json().get("data", []))


def public_list():
    return [{"id": k, "name": v["name"], "hint": v["hint"], "model": v["model"], "search": v["search"], "color": v["color"]} for k, v in PROVIDERS.items()]


# ------------------------------------------------------------ generation

NO_THINKING = types.ThinkingConfig(thinking_budget=0)


class Reply:
    """What a provider answered: text, web sources [{title, url}], and the raw Gemini response
    (its grounding data maps sources to stocks)."""
    def __init__(self, text, provider, model, sources=(), raw=None, parsed=None, usage=(0, 0)):
        self.text, self.provider, self.model = text or "", provider, model
        self.sources, self.raw, self.parsed, self.usage = list(sources), raw, parsed, usage


def _schema_hint(schema):
    fields = ", ".join(f"{n} ({getattr(f.annotation, '__name__', str(f.annotation))})"
                       for n, f in schema.model_fields.items())
    return f"\n\nYALNIZCA her öğesi şu alanlara sahip bir JSON dizisi döndür (başka metin yazma): {fields}"


# ------------------------------------------------------------ adapters

_gemini_clients = {}


def _gemini(model, key, prompt, search, schema, light):
    cl = _gemini_clients.get(key) or _gemini_clients.setdefault(key, genai.Client(api_key=key))
    kw = {}
    if search:
        kw["tools"] = [types.Tool(google_search=types.GoogleSearch())]
    if schema:
        kw.update(response_mime_type="application/json", response_schema=list[schema])
    if light and "flash" in model:
        kw["thinking_config"] = NO_THINKING       # simple classification: thinking tokens are wasted here
    try:
        resp = cl.models.generate_content(model=model, contents=prompt, config=types.GenerateContentConfig(**kw))
    except Exception as e:
        status = getattr(e, "code", None)
        kind = classify(status if isinstance(status, int) else None, str(e)) if status or "API" in str(e) else "network"
        raise ProviderError(kind, f"{MESSAGES[kind]} ({str(e)[:160]})", status) from e
    um = getattr(resp, "usage_metadata", None)
    p = (um.prompt_token_count or 0) if um else 0
    total = (um.total_token_count or 0) if um else 0
    return Reply(resp.text, "gemini", model, raw=resp, parsed=getattr(resp, "parsed", None) if schema else None,
                 usage=(p, max(0, total - p)))


# web search with dynamic filtering needs a recent model; older ones take the basic tool
_NEW_SEARCH = ("claude-opus-5", "claude-sonnet-5", "claude-opus-4-8", "claude-opus-4-7", "claude-opus-4-6",
               "claude-sonnet-4-6")


def _anthropic(model, key, prompt, search, schema, light):
    import anthropic
    cl = anthropic.Anthropic(api_key=key, max_retries=1, timeout=600)
    messages = [{"role": "user", "content": prompt + (_schema_hint(schema) if schema else "")}]
    kw = {"model": model, "max_tokens": 4000 if light else 16000}
    if search:
        kind = "web_search_20260209" if model.startswith(_NEW_SEARCH) else "web_search_20250305"
        kw["tools"] = [{"type": kind, "name": "web_search", "max_uses": 8}]
    if light:
        kw["output_config"] = {"effort": "low"}
    try:
        for _ in range(4):                    # a long web search may pause the turn; continue it
            with cl.messages.stream(messages=messages, **kw) as stream:
                msg = stream.get_final_message()
            if msg.stop_reason != "pause_turn":
                break
            messages = messages[:1] + [{"role": "assistant", "content": msg.content}]
    except anthropic.APIConnectionError as e:
        raise ProviderError("network", MESSAGES["network"]) from e
    except anthropic.APIStatusError as e:
        kind = classify(e.status_code, str(e.message))
        raise ProviderError(kind, f"{MESSAGES[kind]} (HTTP {e.status_code})", e.status_code) from e
    if msg.stop_reason == "refusal":
        raise ProviderError("other", "Model bu isteği yanıtlamadı (güvenlik reddi).")
    text = "".join(b.text for b in msg.content if b.type == "text")
    sources = []
    for b in msg.content:
        if b.type == "web_search_tool_result" and isinstance(b.content, list):
            sources += [{"title": r.title or "kaynak", "url": r.url} for r in b.content if getattr(r, "url", None)]
    return Reply(text, "anthropic", model, sources=sources,
                 usage=(msg.usage.input_tokens or 0, msg.usage.output_tokens or 0))


def _post(url, key, body, timeout=600):
    try:
        r = requests.post(url, json=body, timeout=timeout,
                          headers={"Authorization": f"Bearer {key}"} if key != "local" else {})
    except requests.RequestException as e:
        raise ProviderError("network", MESSAGES["network"]) from e
    if r.status_code >= 400:
        kind = classify(r.status_code, r.text[:500])
        raise ProviderError(kind, f"{MESSAGES[kind]} (HTTP {r.status_code})", r.status_code)
    return r.json()


def _openai(model, key, prompt, search, schema, light):
    """OpenAI Responses API (its web search tool lives there)."""
    body = {"model": model, "input": prompt + (_schema_hint(schema) if schema else "")}
    if search:
        body["tools"] = [{"type": "web_search"}]
    d = _post(f"{PROVIDERS['openai']['base']}/responses", key, body)
    text, sources = "", []
    for item in d.get("output", []):
        for c in item.get("content", []) if item.get("type") == "message" else []:
            text += c.get("text", "")
            sources += [{"title": a.get("title") or "kaynak", "url": a["url"]}
                        for a in c.get("annotations", []) if a.get("url")]
    u = d.get("usage") or {}
    return Reply(text, "openai", model, sources=sources, usage=(u.get("input_tokens", 0), u.get("output_tokens", 0)))


def _compat(provider):
    """OpenAI-compatible chat completions: OpenRouter, Perplexity."""
    def call(model, key, prompt, search, schema, light):
        m = f"{model}:online" if search and provider == "openrouter" and not model.endswith(":online") else model
        d = _post(f"{PROVIDERS[provider]['base']}/chat/completions", key,
                  {"model": m, "messages": [{"role": "user", "content": prompt + (_schema_hint(schema) if schema else "")}]})
        msg = (d.get("choices") or [{}])[0].get("message") or {}
        sources = [{"title": a["url_citation"].get("title") or "kaynak", "url": a["url_citation"]["url"]}
                   for a in msg.get("annotations") or [] if a.get("url_citation", {}).get("url")]
        sources += [{"title": s.get("title") or "kaynak", "url": s["url"]} for s in d.get("search_results") or [] if s.get("url")]
        sources += [{"title": "kaynak", "url": u} for u in d.get("citations") or [] if isinstance(u, str)]
        u = d.get("usage") or {}
        return Reply(msg.get("content"), provider, model, sources=sources,
                     usage=(u.get("prompt_tokens", 0), u.get("completion_tokens", 0)))
    return call


ADAPTERS = {"gemini": _gemini, "anthropic": _anthropic, "openai": _openai, "compat": None}


def generate(prompt, *, search=False, schema=None, light=False, on_usage=None):
    """Run the prompt on the primary provider, then the backup if the primary fails.

    search: let the model search the web; schema: a pydantic model, the answer is a JSON list of it;
    light: a simple task (classification) — no/low reasoning effort; on_usage(reply) records tokens."""
    links = chain()
    if not links:
        raise NoProvider("Yapay zekâ sağlayıcısı tanımlı değil (⚙ Ayarlar → Yapay zekâ)")
    errors = []
    for provider, model, key in links:
        adapter = PROVIDERS[provider]["adapter"]
        fn = _compat(provider) if adapter == "compat" else ADAPTERS[adapter]
        for attempt in range(2):
            try:
                rep = fn(model, key, prompt, search and PROVIDERS[provider]["search"], schema, light)
            except ProviderError as e:
                log.warning("%s attempt %d failed: %s", provider, attempt + 1, e)
                if e.kind in ("server", "network") and attempt == 0:
                    time.sleep(5)
                    continue
                errors.append(f"{PROVIDERS[provider]['name']}: {e}")
                break
            if on_usage:
                try:
                    on_usage(rep)
                except Exception:
                    log.exception("token usage not recorded")
            if errors:
                log.info("answered by backup %s after: %s", provider, " · ".join(errors))
            return rep
    raise RuntimeError("Yapay zekâ hatası — " + " · ".join(errors))




# ------------------------------------------------------------ Ayarlar API (shared by every module)

LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def is_local(request: Request):
    host = request.client.host if request.client else ""
    fwd = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    return host in LOOPBACK and all(h in LOOPBACK for h in fwd)


def _require_local(request):
    if not is_local(request):
        raise HTTPException(403, "Ayarlar yalnızca uygulamanın çalıştığı bilgisayardan değiştirilebilir")


def _slot(slot):
    if slot not in SLOTS:
        raise HTTPException(400, "Geçersiz yuva")
    return slot


def _provider(pid):
    if pid not in PROVIDERS:
        raise HTTPException(400, "Bilinmeyen sağlayıcı")
    return pid


def state(request):
    settings = load_settings()
    slots = {}
    for slot in SLOTS:
        s = settings[slot]
        if not s:
            slots[slot] = None
            continue
        p = PROVIDERS[s["provider"]]
        slots[slot] = {"provider": s["provider"], "name": p["name"], "model": s.get("model") or p["model"],
                       "search": p["search"], "color": p["color"], **masked(s["provider"])}
    return {"slots": slots, "providers": public_list(), "editable": is_local(request)}


class TestIn(BaseModel):
    provider: str
    key: Optional[str] = None
    model: Optional[str] = None


class SlotIn(BaseModel):
    provider: str
    model: Optional[str] = None
    key: Optional[str] = None       # empty: keep the stored key
    force: bool = False             # save even when the test fails


def _clean_key(key):
    key = (key or "").strip()
    if key and not KEY_RE.match(key):
        raise HTTPException(400, "Anahtar beklenmeyen karakterler içeriyor; kopyalarken boşluk ya da satır sonu kalmış olabilir")
    return key or None


def make_router():
    """The /api/settings/ai endpoints; each module includes this router."""
    router = APIRouter()

    @router.get("/api/settings/ai")
    def get_ai(request: Request):
        return state(request)


    @router.post("/api/settings/ai/test")
    def test_ai(t: TestIn, request: Request):
        _require_local(request)
        return test(_provider(t.provider), _clean_key(t.key), (t.model or "").strip() or None)


    @router.put("/api/settings/ai/{slot}")
    def put_slot(slot: str, s: SlotIn, request: Request):
        _require_local(request)
        slot, pid = _slot(slot), _provider(s.provider)
        key, model = _clean_key(s.key), (s.model or "").strip() or PROVIDERS[pid]["model"]
        if not model:
            raise HTTPException(400, "Bir model seç")
        result = test(pid, key, model)
        if not result["ok"] and not s.force:
            raise HTTPException(400, result["message"])
        settings = load_settings()       # before the migration: an .env-only setup counts here
        migrate_env_key()
        if key:
            set_key(pid, key)
        settings[slot] = {"provider": pid, "model": model}
        save_settings(settings)
        return {**state(request), "test": result}


    @router.delete("/api/settings/ai/{slot}")
    def delete_slot(slot: str, request: Request):
        _require_local(request)
        settings = load_settings()
        gone = settings[_slot(slot)]
        settings[slot] = None
        migrate_env_key()
        save_settings(settings)
        others = {s["provider"] for s in settings.values() if s}
        if gone and gone["provider"] not in others:
            delete_key(gone["provider"])       # nobody uses it any more
        return state(request)


    @router.post("/api/settings/ai/swap")
    def swap(request: Request):
        _require_local(request)
        settings = load_settings()
        settings["primary"], settings["backup"] = settings["backup"], settings["primary"]
        migrate_env_key()
        save_settings(settings)
        return state(request)

    return router
