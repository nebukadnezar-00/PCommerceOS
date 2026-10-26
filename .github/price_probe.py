"""CI, information only: can this machine reach the main price source, and which way gets through?"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from backend import net  # noqa: E402

URL = "https://www.akakce.com/arama/?q=airpods"
for name, fn in (("system curl", net._curl_once), ("browser-like", net._browser_like_once)):
    if name == "browser-like" and not net._has_cffi():
        print(name, "not installed")
        continue
    try:
        status, body, location = fn(URL, 3_000_000, 10, 20)
        print(f"{name}: HTTP {status}, {len(body)} bytes{f', redirect {location}' if location else ''}")
    except Exception as e:
        print(f"{name}: {type(e).__name__}: {e}")
try:
    status, body = net.curl_get(URL, connect_timeout=10, max_time=20)
    print(f"curl_get (what the app uses): HTTP {status}, {len(body)} bytes")
except Exception as e:
    print(f"curl_get: {type(e).__name__}: {e}")
