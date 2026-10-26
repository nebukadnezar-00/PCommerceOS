"""CI: start the app the way a user does (launch.py) and wait for /api/status, then stop the whole
process tree, so nothing is left running to keep the job step open (Windows waits for it).
Usage: python .github/launch_check.py <port>"""
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORT = int(sys.argv[1])
WIN = sys.platform.startswith("win")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
env = {**os.environ, "PORT": str(PORT), "NO_BROWSER": "1", "BACKUP_ICLOUD": "0"}
log = open(ROOT / "launch.log", "wb")
proc = subprocess.Popen([sys.executable, "launch.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                        **({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WIN else {"start_new_session": True}))
ok = False
try:
    deadline = time.time() + 600
    while time.time() < deadline and proc.poll() is None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/status", timeout=3) as r:
                print(r.read(400).decode("utf-8", "replace"))
                ok = r.status == 200
                break
        except Exception:
            time.sleep(2)
finally:
    if WIN:
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    log.close()
if not ok:
    print((ROOT / "launch.log").read_text("utf-8", "replace")[-4000:])
sys.exit(0 if ok else 1)
