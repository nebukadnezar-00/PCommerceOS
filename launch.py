"""Starts CommerceOS on its own, on Windows or macOS: CommerceOS.bat / CommerceOS.command run this.

First run: makes a virtual environment (.venv) and installs requirements.txt into it (again whenever
that file changes), copies .env.example to .env. Then it starts the server on 127.0.0.1, opens the
browser when it answers, and keeps running until this window is closed (Ctrl+C). If the app is
already running it only opens the browser. Uses nothing but the standard library."""
import hashlib
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

APP = "CommerceOS"
PORT = int(os.environ.get("PORT", "8002"))
MIN_PY = (3, 9)

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
WIN = sys.platform.startswith("win")
VPY = VENV / ("Scripts/python.exe" if WIN else "bin/python")
URL = f"http://localhost:{PORT}"


for _stream in (sys.stdout, sys.stderr):      # Windows consoles default to a code page without ı, ş, İ
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def say(msg):
    print(msg, flush=True)


def up():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/status", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def ensure_venv():
    req = ROOT / "requirements.txt"
    digest = hashlib.sha256(req.read_bytes()).hexdigest()
    stamp = VENV / ".requirements.sha256"
    if VPY.exists() and stamp.exists() and stamp.read_text().strip() == digest:
        return
    if not VPY.exists():
        say("İlk açılış: Python ortamı kuruluyor (bir kez, birkaç dakika sürebilir)…")
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
    say("Gerekli paketler kuruluyor…")
    subprocess.run([str(VPY), "-m", "pip", "install", "-q", "--upgrade", "pip"], check=True)
    subprocess.run([str(VPY), "-m", "pip", "install", "-q", "-r", str(req)], check=True)
    stamp.write_text(digest)
    say("✓ Paketler hazır")


def main():
    if sys.version_info < MIN_PY:
        say(f"{APP} için Python {MIN_PY[0]}.{MIN_PY[1]} ya da daha yenisi gerekli (bu: {sys.version.split()[0]}).")
        webbrowser.open("https://www.python.org/downloads/")
        return 1
    os.chdir(ROOT)
    if up():
        say(f"{APP} zaten açık → {URL}")
        webbrowser.open(URL)
        return 0
    try:
        ensure_venv()
    except subprocess.CalledProcessError:
        say("Paketler kurulamadı. İnternet bağlantını kontrol edip yeniden dene.")
        return 1
    env_file, example = ROOT / ".env", ROOT / ".env.example"
    if not env_file.exists() and example.exists():
        env_file.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    (ROOT / "data").mkdir(exist_ok=True)

    say(f"{APP} başlatılıyor → {URL}")
    server = subprocess.Popen([str(VPY), "-W", "ignore", "-m", "uvicorn", "backend.main:app",
                               "--host", "127.0.0.1", "--port", str(PORT)], cwd=ROOT,
                              env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    for _ in range(120):
        if server.poll() is not None:
            say("Sunucu açılamadı; yukarıdaki hataya bak.")
            return server.returncode or 1
        if up():
            break
        time.sleep(0.5)
    if not os.environ.get("NO_BROWSER"):
        webbrowser.open(URL)
    say("Açık. Kapatmak için bu pencereyi kapat ya da Ctrl+C'ye bas.")
    try:
        return server.wait()
    except KeyboardInterrupt:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        return 0


if __name__ == "__main__":
    sys.exit(main())
