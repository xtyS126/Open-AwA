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

:: ---- Backend ----
echo [1/2] Starting backend (port 8000) ...
echo       DEV_FAST_START=1

pushd "%~dp0backend"
set DEV_FAST_START=1
start "Open-AwA-Backend" python main.py
popd

:: ---- Frontend ----
echo [2/2] Starting frontend (port 5173) ...

:: clean Vite deps cache to avoid Windows file-lock EPERM
if exist "%~dp0.vite-cache" (
    echo       Cleaning Vite cache...
    rmdir /s /q "%~dp0.vite-cache" 2>nul
)
if exist "%~dp0frontend\node_modules\.vite" (
    rmdir /s /q "%~dp0frontend\node_modules\.vite" 2>nul
)
if exist "%~dp0frontend\node_modules\.vite-cache" (
    rmdir /s /q "%~dp0frontend\node_modules\.vite-cache" 2>nul
)

if not exist "%~dp0frontend\node_modules" (
    echo       Installing frontend dependencies...
    pushd "%~dp0frontend"
    call npm install
    popd
)

pushd "%~dp0frontend"
start "Open-AwA-Frontend" npm run dev
popd

echo.
echo ================================================================
echo   Done. Open http://localhost:5173
echo   Close each CMD window to stop the service.
echo ================================================================
echo.
pause
