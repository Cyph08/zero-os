@echo off
REM ============================================================
REM  Restart the Zero OS backend cleanly.
REM  Kills whatever is holding port 8000, then relaunches the
REM  API from the correct virtualenv (K:\Zero\.venv).
REM
REM  If you see "Access is denied" when it tries to kill the old
REM  process, RIGHT-CLICK this file and choose "Run as administrator".
REM ============================================================

echo.
echo [1/3] Stopping any backend currently on port 8000...
set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    echo       Killing PID %%a
    taskkill /F /PID %%a >nul 2>&1
    set FOUND=1
)
if "%FOUND%"=="0" echo       Nothing was running on 8000.

echo [2/3] Waiting for the port to free up...
timeout /t 2 /nobreak >nul

echo [3/3] Starting Zero backend (localhost:8000) from K:\Zero\.venv ...
echo       Leave this window open. Press Ctrl+C here to stop the backend.
echo.
cd /d K:\Zero\.zero
"K:\Zero\.venv\Scripts\python.exe" -m uvicorn api.main:app --host 127.0.0.1 --port 8000

echo.
echo Backend stopped. Press any key to close.
pause >nul
