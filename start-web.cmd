@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" -c "import aioquic, aiohttp" >nul 2>&1
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" -X utf8 minecraft_web.py %*
if errorlevel 1 goto fail
exit /b 0
:fail
echo FreeP2P 실행 실패. 위 오류와 Python 설치 상태를 확인하세요.
pause
exit /b 1
