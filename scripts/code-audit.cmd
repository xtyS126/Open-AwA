@echo off
REM Open-AwA 代码审计快捷入口
REM 用法: code-audit [skip-ocr] [skip-tests] [frontend-only] [backend-only] [verbose]

set ARGS=
if "%1"=="skip-ocr"       (set ARGS=%ARGS% -SkipOcr & shift)
if "%1"=="skip-tests"     (set ARGS=%ARGS% -SkipTests & shift)
if "%1"=="frontend-only"  (set ARGS=%ARGS% -FrontendOnly & shift)
if "%1"=="backend-only"   (set ARGS=%ARGS% -BackendOnly & shift)
if "%1"=="verbose"        (set ARGS=%ARGS% -Verbose & shift)

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0code-audit.ps1" %ARGS%
exit /b %ERRORLEVEL%
