@echo off
REM ============================================================
REM  Stop the Zero OS backend (and with it the Telegram bot).
REM  Use this when Zero was started hidden by the autostart
REM  launcher and there is no window to close.
REM ============================================================

echo.
echo Stopping Zero backend on port 8000...
set FOUND=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    echo    Killing PID %%a
    taskkill /F /PID %%a >nul 2>&1
    set FOUND=1
)
if "%FOUND%"=="0" (
    echo    Zero was not running.
) else (
    echo    Zero stopped. The Telegram bot is now offline.
)
echo.
pause
