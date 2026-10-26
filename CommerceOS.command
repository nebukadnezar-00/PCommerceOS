#!/bin/bash
# Double-click to start CommerceOS (macOS). Needs Python 3.9 or newer (python3).
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 bulunamadı: https://www.python.org/downloads/"
  open "https://www.python.org/downloads/"
  exit 1
fi
exec python3 launch.py
