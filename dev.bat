@echo off
chcp 65001 >nul
title Open-AwA 一键调试启动

echo ================================================================
echo   Open-AwA 开发环境一键启动
echo   后端: http://localhost:8000
echo   前端: http://localhost:5173
echo ================================================================
echo.

:: ---- 检查 Python ----
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.11+
    pause
    exit /b 1
)

:: ---- 检查 Node.js ----
where node >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Node.js，请先安装 Node.js 18+
    pause
    exit /b 1
)

:: ---- 后端 ----
echo [1/2] 启动后端 (端口 8000) ...
echo         模式: 开发快启 (DEV_FAST_START=1)
echo         跳过: 插件市场 seed / 插件加载 / 微信自动回复

set DEV_FAST_START=1
start "Open-AwA Backend" cmd /k "cd /d "%~dp0" && python -m openawa.main"

:: ---- 前端 ----
echo [2/2] 启动前端 (端口 5173) ...

:: 检查 node_modules 是否存在
if not exist "%~dp0frontend\node_modules" (
    echo         首次运行，安装前端依赖...
    cd /d "%~dp0frontend"
    call npm install
)

start "Open-AwA Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo ================================================================
echo   启动完成！
echo   浏览器访问 http://localhost:5173 即可开始调试
echo   关闭窗口即可停止对应服务
echo ================================================================
echo.
pause
