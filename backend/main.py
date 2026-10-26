import logging
import re
import threading
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import api, backup, config, db, providers, scheduler, sites

providers.set_app("CommerceOS")     # key names when it runs on its own

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app):
    db.init()
    sites.seed_defaults()
    sites.normalize_positions()
    # logos need the network; the page works (initials) until they arrive
    threading.Thread(target=sites.missing_logos, daemon=True).start()
    scheduler.start()
    yield
    scheduler.stop()


app = FastAPI(title="CommerceOS", lifespan=lifespan)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _hostname(host_header):
    """'localhost:8002' → 'localhost', '[::1]:8002' → '[::1]'."""
    h = (host_header or "").lower()
    return h.split("]")[0] + "]" if h.startswith("[") else h.split(":")[0]


@app.middleware("http")
async def local_only(request, call_next):
    """Serve only this Mac's own pages: reject foreign Host names (DNS rebinding) and state-changing
    requests sent by other web sites (a cross-site POST can skip the CORS preflight)."""
    if _hostname(request.headers.get("host")) not in config.ALLOWED_HOSTS:
        return PlainTextResponse("Bu adresten erişime izin verilmiyor", status_code=403)
    if request.method not in SAFE_METHODS:
        origin = request.headers.get("origin")
        if request.headers.get("sec-fetch-site") == "cross-site" or (
                origin and (urlsplit(origin).hostname or "") not in {h.strip("[]") for h in config.ALLOWED_HOSTS}):
            return PlainTextResponse("Başka bir siteden gelen istek reddedildi", status_code=403)
    return await call_next(request)


app.include_router(api.router)
app.include_router(providers.make_router())
app.include_router(backup.make_router())                # ⚙ Ayarlar → Yedek


# ------------------------------------------------------------- frontend

NO_CACHE = {"Cache-Control": "no-cache"}  # always revalidate, so code updates show up immediately


@app.middleware("http")
async def no_cache_static(request, call_next):
    resp = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


app.mount("/static", StaticFiles(directory=config.FRONTEND_DIR), name="static")


def _versioned(html):
    """Append ?v=<mtime> to local assets so a browser never mixes old and new files."""
    def repl(m):
        path = config.FRONTEND_DIR / m.group(2)
        v = int(path.stat().st_mtime) if path.exists() else 0
        return f'{m.group(1)}/static/{m.group(2)}?v={v}"'
    return re.sub(r'((?:src|href)=")/static/([\w.\-/]+)"', repl, html)


@app.get("/")
def index():
    html = (config.FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(_versioned(html), headers=NO_CACHE)
