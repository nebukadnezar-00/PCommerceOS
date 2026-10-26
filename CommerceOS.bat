@echo off
rem Double-click to start CommerceOS (Windows). Needs Python 3.9 or newer: https://www.python.org/downloads/
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
for %%v in (3.13 3.12 3.11 3) do (
  py -%%v -c "import sys" >nul 2>nul && (py -%%v launch.py & goto :done)
)
python -c "import sys; sys.exit(sys.version_info < (3, 9))" >nul 2>nul && (python launch.py & goto :done)
echo Python bulunamadi. Python 3.13 kurup (kurulumda "Add python.exe to PATH" isaretli olsun) yeniden cift tikla.
start "" https://www.python.org/downloads/
:done
pause
