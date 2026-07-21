@echo off
title Open-AwA Dev

echo ================================================================
echo   Open-AwA Dev Start
echo   Backend : http://localhost:8000
echo   Frontend: http://localhost:5173
echo ================================================================
echo.

:: ---- Python check ----
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERR] Python not found
    pause
    exit /b 1
)

:: ---- Node check ----
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERR] Node.js not found
    pause
    exit /b 1
)

:: ---- Kill leftover Node processes + clear locked cache ----
echo [0] Cleaning up previous Vite cache...
taskkill /f /im node.exe >nul 2>&1
:: wait for file handles to release
timeout /t 2 /nobreak >nul
:: remove ALL possible Vite cache locations
:: bin/dev.bat 上溯 1 级到项目根；前端在 lib/frontend/
for %%d in (
    "%~dp0..\.vite-cache"
    "%~dp0..\lib\frontend\node_modules\.vite"
    "%~dp0..\lib\frontend\node_modules\.vite-cache"
) do (
    if exist %%d (
        rmdir /s /q %%d 2>nul
        if exist %%d (
            echo       WARNING: Could not delete %%d, using --force flag
        )
    )
)

:: ---- Backend ----
echo [1/2] Starting backend (port 8000) ...
echo       DEV_FAST_START=1

pushd "%~dp0..\lib\backend"
set DEV_FAST_START=1
start "Open-AwA-Backend" python main.py
popd

:: ---- Frontend ----
echo [2/2] Starting frontend (port 5173) ...

if not exist "%~dp0..\lib\frontend\node_modules" (
    echo       Installing frontend dependencies...
    pushd "%~dp0..\lib\frontend"
    call npm install
    popd
)

pushd "%~dp0..\lib\frontend"
start "Open-AwA-Frontend" cmd /c "npx vite --host 0.0.0.0 --port 5173 --force"
popd

echo.
echo ================================================================
echo   Done. Open http://localhost:5173
echo   Close each CMD window to stop the service.
echo ================================================================
echo.
pause
