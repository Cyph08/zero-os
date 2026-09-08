@echo off
cd /d K:\Zero\.zero
echo ============================================
echo  Zero OS Backend Startup
echo ============================================
echo.

rem --- Ensure deps are installed in uv venv ---
echo [1/2] Syncing dependencies (uv pip install)...
uv pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo WARN: uv pip install failed, continuing anyway...
)
echo.

rem --- Start server ---
echo [2/2] Starting uvicorn at http://localhost:8000...
echo.

if exist ".venv\Scripts\uvicorn.exe" (
    .venv\Scripts\uvicorn.exe api.main:app --host 0.0.0.0 --port 8000 --reload
) else (
    uv run python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
)

pause
